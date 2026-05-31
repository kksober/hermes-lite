"""Tests for coding extensibility and subagent planning."""

from __future__ import annotations

import json


def test_external_tool_config_loads_from_workspace(tmp_path) -> None:
    from hermes_lite.coding.extensibility import load_external_tools
    from hermes_lite.coding.workspace import Workspace

    config_dir = tmp_path / ".hermes"
    config_dir.mkdir()
    (config_dir / "tools.json").write_text(
        json.dumps({
            "tools": [
                {
                    "name": "lint",
                    "description": "Run lint",
                    "command": "python -m ruff check .",
                }
            ]
        }),
        encoding="utf-8",
    )

    result = load_external_tools(Workspace(tmp_path))

    assert result["ok"] is True
    assert result["tools"][0]["name"] == "lint"


def test_hook_status_loads_hooks_without_running_them(tmp_path) -> None:
    from hermes_lite.coding.extensibility import hook_status
    from hermes_lite.coding.workspace import Workspace

    config_dir = tmp_path / ".hermes"
    config_dir.mkdir()
    (config_dir / "hooks.json").write_text(
        json.dumps({"hooks": [{"event": "post_test", "command": "echo done"}]}),
        encoding="utf-8",
    )

    result = hook_status(Workspace(tmp_path))

    assert result["ok"] is True
    assert result["hooks"][0]["event"] == "post_test"
    assert result["hooks"][0]["enabled"] is True


def test_subagent_plan_includes_clean_room_roles() -> None:
    from hermes_lite.coding.subagents import create_subagent_plan

    plan = create_subagent_plan("fix tests")

    assert [task.role for task in plan.tasks] == ["planner", "builder", "reviewer"]
    assert plan.clean_room is True
    assert "fix tests" in plan.to_dict()["task"]


def test_create_and_persist_plan(tmp_path) -> None:
    from hermes_lite.coding.subagents import create_subagent_plan, save_plan, load_plan, list_plans

    plan = create_subagent_plan("add login")
    result = save_plan(plan, str(tmp_path))
    assert result["ok"] is True
    plan_id = result["plan_id"]

    loaded = load_plan(plan_id, str(tmp_path))
    assert loaded["ok"] is True
    assert loaded["plan"]["task"] == "add login"

    listed = list_plans(str(tmp_path))
    assert listed["total"] == 1


def test_load_plan_missing(tmp_path) -> None:
    from hermes_lite.coding.subagents import load_plan

    result = load_plan("nonexistent", str(tmp_path))
    assert result["ok"] is False
    assert result["error"] == "plan_not_found"


def test_worktree_status_reports_plain_checkout(tmp_path) -> None:
    from hermes_lite.coding.git import GitClient
    from hermes_lite.coding.workspace import Workspace

    result = GitClient(Workspace(tmp_path)).worktree_status()

    assert result["ok"] is True
    assert result["is_git_repo"] is False
    assert result["worktrees"] == []
