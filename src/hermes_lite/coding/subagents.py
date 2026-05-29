"""Clean-room subagent planning primitives."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubagentTask:
    """A role-scoped task for future multi-agent execution."""

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

    def to_dict(self) -> dict[str, object]:
        return {
            "task": self.task,
            "clean_room": self.clean_room,
            "worktree_recommended": self.worktree_recommended,
            "tasks": [task.to_dict() for task in self.tasks],
        }


def create_subagent_plan(task: str) -> SubagentPlan:
    """Create a clean-room planner/builder/reviewer plan."""
    cleaned = task.strip() or "coding task"
    return SubagentPlan(
        task=cleaned,
        tasks=[
            SubagentTask("planner", cleaned, "Inspect the repository and produce a minimal implementation plan."),
            SubagentTask("builder", cleaned, "Implement the approved plan with focused tests and minimal edits."),
            SubagentTask("reviewer", cleaned, "Review the diff, run verification, and identify regressions."),
        ],
    )


def create_worktree_task(task: str, branch: str) -> dict[str, object]:
    """Return metadata for future isolated worktree execution."""
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
