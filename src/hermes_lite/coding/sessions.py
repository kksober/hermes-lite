"""Long-running command sessions with optional PTY support.

Supports start / read / write_stdin / stop / list operations on background
processes.  Every session runs inside the workspace boundary and is subject
to the active permission policy.

Orphan prevention
------------------
- Each process is launched in its own process group via ``os.setsid``.
- ``SessionManager`` registers an ``atexit`` handler that sends ``SIGKILL``
  to every known process group.
- Stop escalation: ``SIGTERM`` → wait → ``SIGKILL``.
"""

from __future__ import annotations

import atexit
import os
import pty
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from hermes_lite.coding.audit import AuditLogger
from hermes_lite.coding.permissions import PermissionPolicy
from hermes_lite.coding.workspace import Workspace


@dataclass
class CommandSession:
    """A single running background command."""

    session_id: str
    command: str
    cwd: str
    process: subprocess.Popen[bytes]
    started_at: float
    pty_enabled: bool = False
    master_fd: int | None = None
    pgid: int | None = None

    # Output buffer — lines list with lock
    _lines: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _eof: bool = False
    _exit_code: int | None = None
    _reader_exc: str | None = None

    max_output_lines: int = 2000

    def append_line(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
            if len(self._lines) > self.max_output_lines:
                self._lines = self._lines[-self.max_output_lines :]

    def read_lines(self, offset: int = 0, limit: int = 100) -> dict[str, object]:
        with self._lock:
            total = len(self._lines)
            start = max(offset, 0)
            end = min(start + max(limit, 1), total)
            snippet = self._lines[start:end]
        return {
            "offset": start,
            "limit": limit,
            "total_lines": total,
            "lines": snippet,
            "eof": self._eof,
            "exit_code": self._exit_code,
        }

    def mark_eof(self, exit_code: int | None) -> None:
        with self._lock:
            self._eof = True
            self._exit_code = exit_code

    def mark_reader_error(self, exc: str) -> None:
        with self._lock:
            self._reader_exc = exc
            self._eof = True

    @property
    def running(self) -> bool:
        with self._lock:
            if not self._eof and self.process is not None:
                poll = self.process.poll()
                if poll is not None:
                    self._eof = True
                    self._exit_code = poll
            return not self._eof


def _reader_thread(session: CommandSession, stream: Any) -> None:
    """Read lines from *stream* and feed them into the session buffer."""
    try:
        for line in iter(stream.readline, b""):
            decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
            session.append_line(decoded)
    except Exception as exc:
        session.mark_reader_error(str(exc))
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _pty_reader_thread(session: CommandSession, fd: int) -> None:
    """Read from a PTY master fd and feed lines into the session buffer."""
    buf = b""
    try:
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                session.append_line(line.decode("utf-8", errors="replace").rstrip("\r"))
        # flush remaining buffer
        if buf:
            session.append_line(buf.decode("utf-8", errors="replace").rstrip("\r"))
    except Exception as exc:
        session.mark_reader_error(str(exc))
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


class SessionManager:
    """Manages long-running background command sessions.

    Parameters
    ----------
    workspace:
        Workspace boundary — all commands run inside it.
    permission_policy:
        Active permission policy for command authorization.
    audit:
        Optional audit logger.  Created automatically if not provided.
    default_timeout_seconds:
        Default per-command timeout; ``None`` means no timeout.
    max_output_lines:
        Maximum lines retained per session buffer.
    """

    def __init__(
        self,
        workspace: Workspace,
        permission_policy: PermissionPolicy,
        *,
        audit: AuditLogger | None = None,
        default_timeout_seconds: float | None = None,
        max_output_lines: int = 2000,
    ) -> None:
        self.workspace = workspace
        self.permission_policy = permission_policy
        self.audit = audit or AuditLogger()
        self.default_timeout_seconds = default_timeout_seconds
        self.max_output_lines = max_output_lines
        self._sessions: dict[str, CommandSession] = {}
        self._lock = threading.Lock()
        atexit.register(self.cleanup)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def start(
        self,
        command: str,
        *,
        cwd: str = ".",
        pty: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Start a command in the background.

        Returns session metadata including ``session_id``.
        """
        decision = self.permission_policy.decide_command(command)
        if decision.denied:
            return {
                "ok": False,
                "error": "permission_denied",
                "reason": decision.reason,
                "message": decision.message,
            }

        cwd_check = self.workspace.resolve(cwd, operation="read")
        if not cwd_check.ok:
            data = cwd_check.to_dict()
            data.update({"ok": False})
            return data
        if not cwd_check.path.exists() or not cwd_check.path.is_dir():
            return {"ok": False, "error": "cwd_invalid", "cwd": str(cwd_check.path)}

        session_id = uuid.uuid4().hex[:12]
        try:
            args = __import__("shlex").split(command)
        except ValueError as exc:
            return {"ok": False, "error": "invalid_command", "message": str(exc)}

        started = time.perf_counter()

        if pty:
            return self._start_pty(session_id, args, cwd_check, started, timeout_seconds)
        else:
            return self._start_pipe(session_id, args, cwd_check, started, timeout_seconds)

    def read(
        self,
        session_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, object]:
        """Read buffered output from a running or finished session."""
        session = self._get(session_id)
        if session is None:
            return {"ok": False, "error": "session_not_found", "session_id": session_id}
        lines = session.read_lines(offset=offset, limit=limit)
        elapsed_ms = int((time.perf_counter() - session.started_at) * 1000)
        return {
            "ok": True,
            "session_id": session_id,
            "command": session.command,
            "running": session.running,
            **lines,
            "elapsed_ms": elapsed_ms,
        }

    def write_stdin(self, session_id: str, text: str) -> dict[str, object]:
        """Send text to a running session's stdin."""
        session = self._get(session_id)
        if session is None:
            return {"ok": False, "error": "session_not_found", "session_id": session_id}
        if not session.running:
            return {"ok": False, "error": "session_ended", "session_id": session_id}
        try:
            if session.pty_enabled and session.master_fd is not None:
                os.write(session.master_fd, text.encode("utf-8"))
            elif session.process.stdin is not None:
                session.process.stdin.write(text.encode("utf-8"))
                session.process.stdin.flush()
            else:
                return {"ok": False, "error": "no_stdin", "session_id": session_id}
        except OSError as exc:
            return {"ok": False, "error": "write_stdin_failed", "message": str(exc)}
        self.audit.record("stdin_write", "write_stdin", session.command, "allow", f"session={session_id}")
        return {"ok": True, "session_id": session_id, "bytes": len(text.encode("utf-8"))}

    def stop(self, session_id: str, *, force: bool = False) -> dict[str, object]:
        """Stop a running session.

        Sends ``SIGTERM``, waits up to 5 seconds, then escalates to ``SIGKILL``.
        If *force* is ``True``, sends ``SIGKILL`` immediately.
        """
        session = self._get(session_id)
        if session is None:
            return {"ok": False, "error": "session_not_found", "session_id": session_id}
        if not session.running:
            return {"ok": True, "session_id": session_id, "was_running": False, "message": "Already stopped."}

        pgid = session.pgid
        if pgid is None:
            return self._stop_process(session, force)

        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.killpg(pgid, sig)
        except OSError:
            # process group may already be gone
            pass

        if not force:
            # wait for graceful exit
            deadline = time.perf_counter() + 5.0
            while time.perf_counter() < deadline:
                if not session.running:
                    break
                time.sleep(0.1)
            if session.running:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except OSError:
                    pass

        session.mark_eof(-1 if force else None)
        self.audit.record("session_stop", "stop_command", session.command, "allow", f"session={session_id}")
        return {"ok": True, "session_id": session_id, "was_running": True}

    def list_sessions(self) -> dict[str, object]:
        """Return metadata for all sessions (running and finished)."""
        result: list[dict[str, object]] = []
        with self._lock:
            for sid, session in self._sessions.items():
                result.append({
                    "session_id": sid,
                    "command": session.command,
                    "cwd": session.cwd,
                    "pty_enabled": session.pty_enabled,
                    "running": session.running,
                    "elapsed_ms": int((time.perf_counter() - session.started_at) * 1000),
                })
        return {"ok": True, "sessions": result, "count": len(result)}

    def cleanup(self) -> None:
        """Kill all running sessions.  Called automatically at process exit."""
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if not session.running:
                continue
            try:
                if session.pgid is not None:
                    os.killpg(session.pgid, signal.SIGKILL)
                else:
                    session.process.kill()
                # reap the process to update exit state
                try:
                    session.process.wait(timeout=2)
                except Exception:
                    pass
            except Exception:
                pass
            session.mark_eof(-1)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _get(self, session_id: str) -> CommandSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def _register(self, session: CommandSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def _start_pipe(
        self,
        session_id: str,
        args: list[str],
        cwd_check: Any,
        started: float,
        timeout_seconds: float | None,
    ) -> dict[str, object]:
        try:
            proc = subprocess.Popen(
                args,
                cwd=cwd_check.path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
            )
        except FileNotFoundError:
            return {"ok": False, "error": "missing_command", "command": " ".join(args)}
        except OSError as exc:
            return {"ok": False, "error": "spawn_failed", "message": str(exc)}

        session = CommandSession(
            session_id=session_id,
            command=" ".join(args),
            cwd=str(cwd_check.path),
            process=proc,
            started_at=started,
            pty_enabled=False,
            pgid=os.getpgid(proc.pid),
            max_output_lines=self.max_output_lines,
        )
        if proc.stdout is not None:
            t = threading.Thread(target=_reader_thread, args=(session, proc.stdout), daemon=True)
            t.start()

        self._register(session)
        self.audit.record("session_start", "start_command", session.command, "allow", f"session={session_id}")

        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        if timeout is not None:
            t = threading.Timer(timeout, self._timeout_session, args=[session_id])
            t.daemon = True
            t.start()

        return {
            "ok": True,
            "session_id": session_id,
            "command": session.command,
            "cwd": session.cwd,
            "pty_enabled": False,
            "started_at": started,
        }

    def _start_pty(
        self,
        session_id: str,
        args: list[str],
        cwd_check: Any,
        started: float,
        timeout_seconds: float | None,
    ) -> dict[str, object]:
        master_fd, slave_fd = pty.openpty()
        try:
            proc = subprocess.Popen(
                args,
                cwd=cwd_check.path,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid,
            )
        except FileNotFoundError:
            os.close(master_fd)
            os.close(slave_fd)
            return {"ok": False, "error": "missing_command", "command": " ".join(args)}
        except OSError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            return {"ok": False, "error": "spawn_failed", "message": str(exc)}

        os.close(slave_fd)

        session = CommandSession(
            session_id=session_id,
            command=" ".join(args),
            cwd=str(cwd_check.path),
            process=proc,
            started_at=started,
            pty_enabled=True,
            master_fd=master_fd,
            pgid=os.getpgid(proc.pid),
            max_output_lines=self.max_output_lines,
        )

        t = threading.Thread(target=_pty_reader_thread, args=(session, master_fd), daemon=True)
        t.start()

        self._register(session)
        self.audit.record("session_start", "start_command", session.command, "allow", f"session={session_id} pty=true")

        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        if timeout is not None:
            t = threading.Timer(timeout, self._timeout_session, args=[session_id])
            t.daemon = True
            t.start()

        return {
            "ok": True,
            "session_id": session_id,
            "command": session.command,
            "cwd": session.cwd,
            "pty_enabled": True,
            "started_at": started,
        }

    def _timeout_session(self, session_id: str) -> None:
        """Called by Timer to stop a session that exceeds its timeout."""
        session = self._get(session_id)
        if session is None or not session.running:
            return
        self.stop(session_id, force=True)

    def _stop_process(self, session: CommandSession, force: bool) -> dict[str, object]:
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            session.process.send_signal(sig)
        except Exception:
            pass
        if not force:
            try:
                session.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    session.process.kill()
                except Exception:
                    pass
        session.mark_eof(-1 if force else session.process.poll())
        self.audit.record("session_stop", "stop_command", session.command, "allow", f"session={session.session_id}")
        return {"ok": True, "session_id": session.session_id, "was_running": True}
