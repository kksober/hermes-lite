"""Tests for M12 P3/P4: find_files tool and read_file max_bytes limit."""
from __future__ import annotations


def test_find_files_glob_match(tmp_path) -> None:
    from hermes_lite.coding.context import list_files
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x=1")
    (tmp_path / "src" / "utils.py").write_text("y=2")
    (tmp_path / "src" / "readme.md").write_text("doc")

    result = list_files(ws, pattern="**/*.py")
    assert result["ok"] is True
    assert result["count"] == 2
    assert any("app.py" in f for f in result["files"])
    assert any("utils.py" in f for f in result["files"])


def test_find_files_no_match(tmp_path) -> None:
    from hermes_lite.coding.context import list_files
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "readme.md").write_text("doc")

    result = list_files(ws, pattern="**/*.py")
    assert result["ok"] is True
    assert result["count"] == 0


def test_find_files_respects_limit(tmp_path) -> None:
    from hermes_lite.coding.context import list_files
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    for i in range(10):
        (tmp_path / f"file_{i}.txt").write_text("data")

    result = list_files(ws, pattern="*.txt", limit=3)
    assert result["ok"] is True
    assert result["count"] <= 3
    assert result.get("truncated") is True


def test_read_file_max_bytes_exceeded(tmp_path) -> None:
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "large.py").write_text("x" * 10_000)

    # Direct workspace read — no size limit at this level
    result = ws.read_text("large.py")
    assert result["ok"] is True

    # The tool-level limit is tested via the registry
    # Verify file size detection works
    size = (tmp_path / "large.py").stat().st_size
    assert size > 5_000  # file is large enough

    # Read with very small max_bytes should fail via tool
    from hermes_lite.tools.coding import register_coding_tools
    from hermes_lite.tools.registry import ToolRegistry
    from hermes_lite.coding.permissions import PermissionPolicy

    registry = ToolRegistry()
    policy = PermissionPolicy(interactive=False)
    register_coding_tools(registry, ws, policy)

    # Call read_file tool with tiny max_bytes
    import json
    raw = registry.dispatch("read_file", {"path": "large.py", "max_bytes": 500})
    outer = json.loads(raw)
    output = json.loads(outer["result"])
    assert output["ok"] is False
    assert output["error"] == "file_too_large"
    assert output["size"] >= 10_000


def test_read_file_within_max_bytes(tmp_path) -> None:
    from hermes_lite.tools.coding import register_coding_tools
    from hermes_lite.tools.registry import ToolRegistry
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "small.py").write_text("x = 1\ny = 2\nz = 3\n")

    registry = ToolRegistry()
    policy = PermissionPolicy(interactive=False)
    register_coding_tools(registry, ws, policy)

    import json
    raw = registry.dispatch("read_file", {"path": "small.py", "max_bytes": 1_000_000})
    outer = json.loads(raw)
    output = json.loads(outer["result"])
    assert output["ok"] is True
    assert "numbered_content" in output
    assert "x = 1" in output["numbered_content"]
