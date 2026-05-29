"""Tests for coding tool registration and JSON contracts."""

from __future__ import annotations

import json


def _dispatch_result(registry, name: str, args: dict):
    outer = json.loads(registry.dispatch(name, args))
    assert "result" in outer
    return json.loads(outer["result"])


def test_coding_tools_register_expected_tools(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.tools.coding import register_coding_tools
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_coding_tools(registry, Workspace(tmp_path), PermissionPolicy())

    names = {tool["name"] for tool in registry.list_tools()}
    assert "workspace_status" in names
    assert "apply_patch" in names
    assert "project_map" in names
    assert "subagent_plan" in names


def test_coding_file_tools_round_trip(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.tools.coding import register_coding_tools
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_coding_tools(registry, Workspace(tmp_path), PermissionPolicy())

    write_result = _dispatch_result(registry, "write_file", {"path": "app.py", "content": "alpha\n"})
    read_result = _dispatch_result(registry, "read_file", {"path": "app.py"})
    patch_result = _dispatch_result(
        registry,
        "apply_patch",
        {"path": "app.py", "old_text": "alpha", "new_text": "beta"},
    )
    search_result = _dispatch_result(registry, "search_text", {"query": "beta"})

    assert write_result["ok"] is True
    assert read_result["content"].endswith("alpha\n")
    assert patch_result["ok"] is True
    assert search_result["matches"][0]["path"] == "app.py"


def test_coding_run_command_tool_denies_destructive_command(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.tools.coding import register_coding_tools
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_coding_tools(registry, Workspace(tmp_path), PermissionPolicy())

    result = _dispatch_result(registry, "run_command", {"command": "rm -rf build"})

    assert result["ok"] is False
    assert result["error"] == "permission_denied"


def test_coding_analysis_tools_return_stable_shapes(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.tools.coding import register_coding_tools
    from hermes_lite.tools.registry import ToolRegistry

    (tmp_path / "module.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    registry = ToolRegistry()
    register_coding_tools(registry, Workspace(tmp_path), PermissionPolicy())

    status = _dispatch_result(registry, "workspace_status", {})
    project_map = _dispatch_result(registry, "project_map", {})
    diagnostics = _dispatch_result(registry, "python_diagnostics", {"path": "module.py"})
    symbols = _dispatch_result(registry, "python_symbols", {"path": "module.py"})
    plan = _dispatch_result(registry, "subagent_plan", {"task": "fix a bug"})

    assert status["ok"] is True
    assert project_map["languages"]["Python"] == 1
    assert diagnostics["ok"] is True
    assert symbols["symbols"][0]["name"] == "run"
    assert [task["role"] for task in plan["tasks"]] == ["planner", "builder", "reviewer"]
