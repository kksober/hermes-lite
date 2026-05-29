"""Clean-room subagent planning and orchestration primitives.

Supports:
- :class:`SubagentPlan` — planner/builder/reviewer task bundles
- :class:`WorktreeExecutor` — isolated git worktree execution
- :func:`create_subagent_plan` — deterministic plan generation
- :func:`execute_subagent_plan` — orchestrate a plan through a WorktreeExecutor
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from hermes_lite.coding.permissions import PermissionPolicy
from hermes_lite.coding.worktree_exec import WorktreeExecutor, WorktreeRun, WorktreeTask
from hermes_lite.coding.workspace import Workspace


@dataclass(frozen=True)
class SubagentTask:
    """A role-scoped task for multi-agent execution."""

    role: str
    task: str
    goal: str
    status: str = "pending"

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "task": self.task,
            "goal": self.goal,
            "status": self.status,
        }


@dataclass(frozen=True)
class SubagentPlan:
    """A deterministic planner/builder/reviewer task bundle."""

    task: str
    tasks: list[SubagentTask]
    clean_room: bool = True
    worktree_recommended: bool = True
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "task": self.task,
            "clean_room": self.clean_room,
            "worktree_recommended": self.worktree_recommended,
            "tasks": [task.to_dict() for task in self.tasks],
        }


# ---------------------------------------------------------------------------
# plan creation
# ---------------------------------------------------------------------------


def create_subagent_plan(task: str) -> SubagentPlan:
    """Create a clean-room planner/builder/reviewer plan."""
    cleaned = task.strip() or "coding task"
    return SubagentPlan(
        task=cleaned,
        tasks=[
            SubagentTask(
                "planner",
                cleaned,
                "Inspect the repository and produce a minimal implementation plan.",
            ),
            SubagentTask(
                "builder",
                cleaned,
                "Implement the approved plan with focused tests and minimal edits.",
            ),
            SubagentTask(
                "reviewer",
                cleaned,
                "Review the diff, run verification, and identify regressions.",
            ),
        ],
    )


def create_worktree_task(task: str, branch: str) -> dict[str, object]:
    """Return metadata for isolated worktree execution."""
    return {
        "ok": True,
        "task": task,
        "branch": branch,
        "recommended_prefix": "codex/",
        "commands": [
            f"git switch -c {branch}",
            "run focused tests",
            "run full verification",
        ],
    }


# ---------------------------------------------------------------------------
# plan execution (with WorktreeExecutor)
# ---------------------------------------------------------------------------


def execute_subagent_plan(
    plan: SubagentPlan,
    workspace: Workspace,
    permission_policy: PermissionPolicy,
    *,
    executor: WorktreeExecutor | None = None,
    auto_cleanup: bool = False,
) -> dict[str, object]:
    """Execute a SubagentPlan using a WorktreeExecutor.

    This is the main orchestration entry point.  It:
    1. Creates an isolated worktree
    2. Executes each task step (currently as awaiting_input for LLM driving)
    3. Runs the review gate
    4. Returns structured results (no automatic merge)

    Parameters
    ----------
    plan:
        The plan to execute.
    workspace:
        The main workspace.
    permission_policy:
        Active permission policy.
    executor:
        Optional pre-configured executor.
    auto_cleanup:
        If ``True``, remove the worktree after review.  Default ``False``
        (keep worktree for inspection).

    Returns
    -------
    Structured result with run metadata, review gate output, and merge
    suggestion.  The caller must decide whether to merge.
    """
    exec_ = executor or WorktreeExecutor(workspace, permission_policy)

    # 1. Create worktree
    create_result = exec_.create_run(plan.task, roles=[t.role for t in plan.tasks])
    if not create_result.get("ok"):
        return create_result

    raw_run = create_result["run"]
    run = _reconstruct_run(raw_run, exec_)

    # 2. Execute each task
    for i, task in enumerate(plan.tasks):
        step_result = exec_.execute_step(
            run, i,
            commands=None,  # LLM-driven — caller provides commands
        )
        if not step_result.get("ok"):
            return {
                "ok": False,
                "error": "step_execution_failed",
                "step_index": i,
                "step_result": step_result,
                "run": run.to_dict(),
            }

    # 3. Review gate
    review = exec_.review_gate(run)

    # 4. Optional cleanup
    if auto_cleanup:
        exec_.cleanup(run)

    return {
        "ok": True,
        "plan_id": plan.plan_id,
        "run": run.to_dict(),
        "review": review.get("review", {}),
        "merge_suggestion": (
            review.get("review", {}).get("merge_suggestion", "")
            if isinstance(review.get("review"), dict)
            else "Review complete. Manual merge required."
        ),
        "auto_cleanup": auto_cleanup,
    }


def subagent_execute_with_commands(
    task: str,
    workspace: Workspace,
    permission_policy: PermissionPolicy,
    *,
    planner_commands: list[str] | None = None,
    builder_commands: list[str] | None = None,
    reviewer_commands: list[str] | None = None,
) -> dict[str, object]:
    """Execute a subagent workflow with explicit command lists per role.

    This is the concrete execution path: each role gets a list of shell
    commands to run inside the worktree.
    """
    plan = create_subagent_plan(task)
    executor = WorktreeExecutor(workspace, permission_policy)

    create_result = executor.create_run(plan.task, roles=["planner", "builder", "reviewer"])
    if not create_result.get("ok"):
        return create_result

    raw_run = create_result["run"]
    run = _reconstruct_run(raw_run, executor)

    command_map: dict[int, list[str]] = {
        0: planner_commands or ["echo 'Planner: inspect repository'", "ls -la"],
        1: builder_commands or ["echo 'Builder: implement changes'"],
        2: reviewer_commands or ["echo 'Reviewer: check diff'", "git diff --stat"],
    }

    for i, _task in enumerate(plan.tasks):
        cmds = command_map.get(i, [])
        step = executor.execute_step(run, i, commands=cmds)
        if not step.get("ok"):
            return {
                "ok": False,
                "error": "execution_failed",
                "step_index": i,
                "step": step,
                "run": run.to_dict(),
            }

    review = executor.review_gate(run)
    return {
        "ok": True,
        "run": run.to_dict(),
        "review": review.get("review", {}),
        "merge_suggestion": (
            review.get("review", {}).get("merge_suggestion", "")
            if isinstance(review.get("review"), dict)
            else "Review complete. Manual merge required."
        ),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _reconstruct_run(raw_run: dict[str, object], executor: WorktreeExecutor) -> WorktreeRun:
    """Reconstruct a :class:`WorktreeRun` from a raw dictionary returned by
    :meth:`WorktreeExecutor.create_run`."""
    run = WorktreeRun(
        run_id=str(raw_run["run_id"]),
        worktree_path=executor.worktree_base / str(raw_run["branch_name"]).replace("/", "-"),
        branch_name=str(raw_run["branch_name"]),
        status=str(raw_run.get("status", "created")),
    )
    for task_data in raw_run.get("tasks", []):
        if isinstance(task_data, dict):
            run.tasks.append(WorktreeTask(
                task_id=str(task_data.get("task_id", "")),
                role=str(task_data.get("role", "")),
                description=str(task_data.get("description", "")),
                status=str(task_data.get("status", "pending")),
            ))
    return run
