"""Subprocess runner for coding-agent commands."""

from __future__ import annotations

import shlex
import subprocess
import time

from hermes_lite.coding.permissions import PermissionPolicy
from hermes_lite.coding.workspace import Workspace


class CommandRunner:
    """Run bounded commands inside a workspace."""

    def __init__(
        self,
        workspace: Workspace,
        permission_policy: PermissionPolicy,
        *,
        timeout_seconds: float = 30.0,
        max_output_chars: int = 12_000,
    ) -> None:
        self.workspace = workspace
        self.permission_policy = permission_policy
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    def run(
        self,
        command: str,
        *,
        cwd: str = ".",
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """Run a command after policy and workspace checks."""
        decision = self.permission_policy.decide_command(command)
        if not decision.allowed:
            result = decision.to_dict()
            result.update({"ok": False, "error": "permission_denied", "reason": decision.reason})
            return result

        cwd_check = self.workspace.resolve(cwd, operation="read")
        if not cwd_check.ok:
            result = cwd_check.to_dict()
            result.update({"ok": False})
            return result
        if not cwd_check.path.exists():
            return {"ok": False, "error": "cwd_not_found", "cwd": str(cwd_check.path)}
        if not cwd_check.path.is_dir():
            return {"ok": False, "error": "cwd_not_directory", "cwd": str(cwd_check.path)}

        try:
            args = shlex.split(command)
        except ValueError as exc:
            return {"ok": False, "error": "invalid_command", "message": str(exc)}

        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                args,
                cwd=cwd_check.path,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return {
                "ok": False,
                "error": "missing_command",
                "command": command,
                "cwd": str(cwd_check.path),
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as exc:
            stdout = self._coerce_output(exc.stdout)
            stderr = self._coerce_output(exc.stderr)
            stdout, stdout_truncated = self._truncate(stdout)
            stderr, stderr_truncated = self._truncate(stderr)
            return {
                "ok": False,
                "error": "timeout",
                "command": command,
                "cwd": str(cwd_check.path),
                "exit_code": None,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": True,
                "timeout_seconds": timeout,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "truncated": stdout_truncated or stderr_truncated,
            }

        stdout, stdout_truncated = self._truncate(completed.stdout)
        stderr, stderr_truncated = self._truncate(completed.stderr)
        return {
            "ok": completed.returncode == 0,
            "command": command,
            "args": args,
            "cwd": str(cwd_check.path),
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": False,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "truncated": stdout_truncated or stderr_truncated,
        }

    def _truncate(self, text: str) -> tuple[str, bool]:
        if len(text) <= self.max_output_chars:
            return text, False
        return text[: self.max_output_chars], True

    def _coerce_output(self, output: str | bytes | None) -> str:
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return output
