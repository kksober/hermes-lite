"""Tests for long-running command sessions and PTY support."""

from __future__ import annotations

import shlex
import sys
import time


# ---------------------------------------------------------------------------
# SessionManager — start/read/stop (pipe mode)
# ---------------------------------------------------------------------------

def test_session_start_and_read_output(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start(f"{shlex.quote(sys.executable)} -c \"print('hello'); print('world')\"")
    assert result["ok"] is True
    session_id = result["session_id"]

    # wait for process to finish
    time.sleep(0.5)

    output = mgr.read(session_id)
    assert output["ok"] is True
    assert "hello" in "\n".join(output["lines"])


def test_session_read_respects_offset_limit(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start(f"{shlex.quote(sys.executable)} -c \"for i in range(20): print(i)\"")
    assert result["ok"] is True
    session_id = result["session_id"]

    time.sleep(0.5)

    output = mgr.read(session_id, offset=5, limit=3)
    assert output["ok"] is True
    assert output["offset"] == 5
    assert output["limit"] == 3
    assert len(output["lines"]) == 3


def test_session_list_and_stop(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start(f"{shlex.quote(sys.executable)} -c \"import time; time.sleep(30)\"")
    assert result["ok"] is True
    session_id = result["session_id"]

    listed = mgr.list_sessions()
    assert listed["count"] >= 1
    assert any(s["session_id"] == session_id for s in listed["sessions"])

    stop_result = mgr.stop(session_id)
    assert stop_result["ok"] is True
    assert stop_result["was_running"] is True


def test_session_stop_already_stopped_is_noop(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start(f"{shlex.quote(sys.executable)} -c \"print('done')\"")
    session_id = result["session_id"]

    time.sleep(0.5)
    # first stop
    mgr.stop(session_id)
    # second stop
    stop2 = mgr.stop(session_id)
    assert stop2["ok"] is True
    assert stop2.get("was_running") is False


def test_session_read_nonexistent() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        mgr = SessionManager(Workspace(td), PermissionPolicy())
        result = mgr.read("nonexistent")
        assert result["ok"] is False
        assert result["error"] == "session_not_found"


def test_session_stop_nonexistent() -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        mgr = SessionManager(Workspace(td), PermissionPolicy())
        result = mgr.stop("nonexistent")
        assert result["ok"] is False
        assert result["error"] == "session_not_found"


# ---------------------------------------------------------------------------
# SessionManager — permission denied
# ---------------------------------------------------------------------------

def test_session_denies_destructive_command(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start("rm -rf build")
    assert result["ok"] is False
    assert result["error"] == "permission_denied"


# ---------------------------------------------------------------------------
# SessionManager — write_stdin (pipe mode)
# ---------------------------------------------------------------------------

def test_session_write_stdin(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start(
        f"{shlex.quote(sys.executable)} -c \"import sys; print('GOT:', sys.stdin.readline().strip())\""
    )
    assert result["ok"] is True
    session_id = result["session_id"]

    write_result = mgr.write_stdin(session_id, "test data\n")
    assert write_result["ok"] is True

    time.sleep(0.3)
    output = mgr.read(session_id)
    combined = "\n".join(output["lines"])
    assert "test data" in combined


def test_session_write_stdin_nonexistent(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.write_stdin("nonexistent", "data")
    assert result["ok"] is False
    assert result["error"] == "session_not_found"


# ---------------------------------------------------------------------------
# SessionManager — cwd validation
# ---------------------------------------------------------------------------

def test_session_rejects_outside_workspace_cwd(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start("ls", cwd="/etc")
    assert result["ok"] is False
    assert "outside_workspace" in str(result.get("error", ""))


def test_session_rejects_nonexistent_cwd(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start("ls", cwd="nonexistent_subdir")
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# SessionManager — output truncation
# ---------------------------------------------------------------------------

def test_session_output_buffer_truncates(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy(), max_output_lines=5)
    result = mgr.start(
        f"{shlex.quote(sys.executable)} -c \"for i in range(30): print(f'line_{{i}}')\""
    )
    assert result["ok"] is True
    session_id = result["session_id"]

    time.sleep(0.5)
    output = mgr.read(session_id)
    assert output["total_lines"] <= 5


# ---------------------------------------------------------------------------
# SessionManager — cleanup
# ---------------------------------------------------------------------------

def test_session_cleanup_kills_running_processes(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start(f"{shlex.quote(sys.executable)} -c \"import time; time.sleep(60)\"")
    assert result["ok"] is True

    mgr.cleanup()

    # after cleanup, the session should be dead
    listed = mgr.list_sessions()
    for s in listed["sessions"]:
        assert s["running"] is False


# ---------------------------------------------------------------------------
# SessionManager — missing command
# ---------------------------------------------------------------------------

def test_session_missing_command(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start("nonexistent_command_xyz")
    assert result["ok"] is False
    assert result["error"] == "missing_command"


# ---------------------------------------------------------------------------
# SessionManager — timeout
# ---------------------------------------------------------------------------

def test_session_timeout_stops_process(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start(
        f"{shlex.quote(sys.executable)} -c \"import time; time.sleep(30)\"",
        timeout_seconds=0.2,
    )
    assert result["ok"] is True
    session_id = result["session_id"]

    # wait for timeout to fire
    time.sleep(0.5)
    output = mgr.read(session_id)
    assert output["eof"] is True


# ---------------------------------------------------------------------------
# SessionManager — force stop
# ---------------------------------------------------------------------------

def test_session_force_stop_immediate(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    result = mgr.start(f"{shlex.quote(sys.executable)} -c \"import time; time.sleep(60)\"")
    assert result["ok"] is True
    session_id = result["session_id"]

    stop_result = mgr.stop(session_id, force=True)
    assert stop_result["ok"] is True
    assert stop_result["was_running"] is True


# ---------------------------------------------------------------------------
# SessionManager — invalid command syntax
# ---------------------------------------------------------------------------

def test_session_invalid_command_syntax(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.sessions import SessionManager
    from hermes_lite.coding.workspace import Workspace

    mgr = SessionManager(Workspace(tmp_path), PermissionPolicy())
    # unclosed quote — permission policy rejects invalid shell syntax
    result = mgr.start("echo \"unclosed")
    assert result["ok"] is False
    assert result["error"] == "permission_denied"
    assert result["reason"] == "invalid_command"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

def test_cli_workspace_runtime_has_session_manager(tmp_path) -> None:
    from hermes_lite.cli import create_workspace_runtime
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    runtime = create_workspace_runtime(str(tmp_path), registry)

    assert runtime is not None
    assert runtime.session_manager is not None
    assert runtime.audit_logger is not None

    tool_names = {t["name"] for t in registry.list_tools()}
    assert "start_command" in tool_names
    assert "read_command" in tool_names
    assert "write_stdin" in tool_names
    assert "stop_command" in tool_names
    assert "list_sessions" in tool_names


def test_cli_parser_accepts_workspace(tmp_path) -> None:
    from hermes_lite.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["--workspace", str(tmp_path)])
    assert args.workspace == str(tmp_path)
