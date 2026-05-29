"""Tests for coding workspace path safety."""

from __future__ import annotations


def test_workspace_resolves_inside_paths(tmp_path) -> None:
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    check = ws.resolve("src/app.py", operation="write")

    assert check.ok is True
    assert check.path == tmp_path / "src" / "app.py"
    assert check.relative_path == "src/app.py"


def test_workspace_rejects_outside_paths(tmp_path) -> None:
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    check = ws.resolve("../outside.txt", operation="read")

    assert check.ok is False
    assert check.error == "outside_workspace"


def test_workspace_blocks_sensitive_reads_and_writes(tmp_path) -> None:
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)

    assert ws.resolve(".env", operation="read").error == "protected_path"
    assert ws.resolve(".git/config", operation="write").error == "protected_path"
    assert ws.resolve("id_ed25519", operation="write").error == "protected_path"
    assert ws.resolve("cert.pem", operation="write").error == "protected_path"
    assert ws.resolve("node_modules/pkg/index.js", operation="write").error == "protected_path"


def test_workspace_read_write_text(tmp_path) -> None:
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    write_result = ws.write_text("src/app.py", "print('hello')\n")
    read_result = ws.read_text("src/app.py")

    assert write_result["ok"] is True
    assert read_result["ok"] is True
    assert read_result["content"] == "print('hello')\n"


def test_workspace_summary_reports_git_repo(tmp_path) -> None:
    from hermes_lite.coding.workspace import Workspace

    (tmp_path / ".git").mkdir()
    ws = Workspace(tmp_path)
    summary = ws.summary()

    assert summary["root"] == str(tmp_path.resolve())
    assert summary["is_git_repo"] is True
    assert ".git" in summary["protected_names"]
