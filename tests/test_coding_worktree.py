"""Tests for worktree execution and subagent orchestration."""

from __future__ import annotations

import shutil
import subprocess

import pytest


# ---------------------------------------------------------------------------
# Subagent plan / orchestration
# ---------------------------------------------------------------------------

def test_create_subagent_plan_has_three_roles() -> None:
    from hermes_lite.coding.subagents import create_subagent_plan

    plan = create_subagent_plan("fix the login bug")
    roles = [t.role for t in plan.tasks]

    assert roles == ["planner", "builder", "reviewer"]
    assert plan.clean_room is True
    assert plan.worktree_recommended is True


def test_subagent_plan_to_dict() -> None:
    from hermes_lite.coding.subagents import create_subagent_plan

    plan = create_subagent_plan("test task")
    result = plan.to_dict()

    assert result["task"] == "test task"
    assert "plan_id" in result
    assert len(result["tasks"]) == 3


def test_create_worktree_task_metadata() -> None:
    from hermes_lite.coding.subagents import create_worktree_task

    result = create_worktree_task("build feature", "codex/feature-x")
    assert result["ok"] is True
    assert result["branch"] == "codex/feature-x"
    assert "commands" in result


# ---------------------------------------------------------------------------
# WorktreeExecutor — git repo tests
# ---------------------------------------------------------------------------

def test_worktree_executor_create_and_cleanup(tmp_path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")

    from hermes_lite.coding.audit import AuditLogger
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.coding.worktree_exec import WorktreeExecutor

    # Initialize a git repo
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.com", "commit", "--allow-empty", "-m", "init"],
        cwd=tmp_path, capture_output=True,
    )

    ws = Workspace(tmp_path)
    policy = PermissionPolicy()
    executor = WorktreeExecutor(ws, policy, audit=AuditLogger())

    create_result = executor.create_run("test task")
    assert create_result["ok"] is True
    run_data = create_result["run"]
    assert run_data["status"] == "created"

    # Reconstruct run for cleanup
    from pathlib import Path
    from hermes_lite.coding.worktree_exec import WorktreeRun

    run = WorktreeRun(
        run_id=str(run_data["run_id"]),
        worktree_path=Path(run_data["worktree_path"]),
        branch_name=str(run_data["branch_name"]),
    )

    cleanup = executor.cleanup(run)
    assert cleanup["ok"] is True
    assert cleanup["run_status"] == "cleaned_up"


def test_worktree_executor_execute_step(tmp_path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")

    from hermes_lite.coding.audit import AuditLogger
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.coding.worktree_exec import WorktreeExecutor, WorktreeRun

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.com", "commit", "--allow-empty", "-m", "init"],
        cwd=tmp_path, capture_output=True,
    )

    ws = Workspace(tmp_path)
    executor = WorktreeExecutor(ws, PermissionPolicy(), audit=AuditLogger())

    create_result = executor.create_run("test task", roles=["builder"])
    assert create_result["ok"] is True

    run_data = create_result["run"]
    run = WorktreeRun(
        run_id=str(run_data["run_id"]),
        worktree_path=executor.worktree_base / str(run_data["branch_name"]).replace("/", "-"),
        branch_name=str(run_data["branch_name"]),
    )

    from hermes_lite.coding.worktree_exec import WorktreeTask
    run.tasks = [WorktreeTask(task_id="t1", role="builder", description="test")]

    step = executor.execute_step(run, 0, commands=["echo 'hello from worktree'"])
    assert step["ok"] is True
    task_data = step["task"]
    assert task_data["status"] == "completed"

    executor.cleanup(run)


def test_worktree_executor_not_git_repo(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.coding.worktree_exec import WorktreeExecutor

    executor = WorktreeExecutor(Workspace(tmp_path), PermissionPolicy())
    result = executor.create_run("task")
    assert result["ok"] is False
    assert result["error"] in ("git_not_available", "not_git_repo")


def test_worktree_executor_invalid_task_index(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.coding.worktree_exec import WorktreeExecutor, WorktreeRun

    executor = WorktreeExecutor(Workspace(tmp_path), PermissionPolicy())
    run = WorktreeRun(run_id="r1", worktree_path=tmp_path, branch_name="test")

    result = executor.execute_step(run, 99)
    assert result["ok"] is False
    assert result["error"] == "invalid_task_index"


def test_worktree_executor_list_runs_empty(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.coding.worktree_exec import WorktreeExecutor

    executor = WorktreeExecutor(Workspace(tmp_path), PermissionPolicy())
    result = executor.list_runs([])
    assert result["ok"] is True
    assert result["count"] == 0


def test_worktree_executor_review_not_ready(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.coding.worktree_exec import WorktreeExecutor, WorktreeRun

    executor = WorktreeExecutor(Workspace(tmp_path), PermissionPolicy())
    run = WorktreeRun(run_id="r1", worktree_path=tmp_path, branch_name="test", status="created")

    result = executor.review_gate(run)
    assert result["ok"] is False
    assert result["error"] == "run_not_ready_for_review"


# ---------------------------------------------------------------------------
# subagent_execute_with_commands integration
# ---------------------------------------------------------------------------

def test_subagent_execute_with_commands_in_git_repo(tmp_path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")

    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.subagents import subagent_execute_with_commands
    from hermes_lite.coding.workspace import Workspace

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.com", "commit", "--allow-empty", "-m", "init"],
        cwd=tmp_path, capture_output=True,
    )

    result = subagent_execute_with_commands(
        "test task",
        Workspace(tmp_path),
        PermissionPolicy(),
        planner_commands=["echo plannner"],
        builder_commands=["echo builder"],
        reviewer_commands=["echo reviewer"],
    )
    assert result["ok"] is True
    assert "merge_suggestion" in result
    assert "review" in result

    # Clean up the worktree
    run_data = result.get("run", {})
    import shutil as _shutil
    wt_path = run_data.get("worktree_path", "")
    if wt_path and _shutil.which("git"):
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_path)],
            cwd=tmp_path, capture_output=True,
        )
        branch = run_data.get("branch_name", "")
        if branch:
            subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=tmp_path, capture_output=True,
            )
