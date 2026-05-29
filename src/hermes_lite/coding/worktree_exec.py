"""Git worktree execution for isolated subagent tasks.

Creates temporary worktrees for safe, auditable task execution with
review gates.  Never performs destructive automatic merges — results
are always presented for human approval.

Clean-room implementation — no OpenCode patterns referenced.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_lite.coding.audit import AuditLogger
from hermes_lite.coding.permissions import PermissionPolicy
from hermes_lite.coding.workspace import Workspace


# ---------------------------------------------------------------------------
# data types
# ---------------------------------------------------------------------------


@dataclass
class WorktreeTask:
    """A single subagent task to execute in a worktree."""

    task_id: str
    role: str  # planner, builder, reviewer
    description: str
    status: str = "pending"
    result: dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0
    completed_at: float = 0.0
    log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "role": self.role,
            "description": self.description,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": int((self.completed_at - self.started_at) * 1000) if self.completed_at else 0,
            "result": self.result,
            "log_lines": len(self.log),
        }


@dataclass
class WorktreeRun:
    """A complete worktree execution run with multiple tasks."""

    run_id: str
    worktree_path: Path
    branch_name: str
    tasks: list[WorktreeTask] = field(default_factory=list)
    status: str = "pending"
    review_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "worktree_path": str(self.worktree_path),
            "branch_name": self.branch_name,
            "status": self.status,
            "tasks": [t.to_dict() for t in self.tasks],
            "review": self.review_result,
        }


# ---------------------------------------------------------------------------
# executor
# ---------------------------------------------------------------------------


class WorktreeExecutor:
    """Create and manage git worktrees for isolated task execution.

    Parameters
    ----------
    workspace:
        The main workspace.
    permission_policy:
        Permission policy applied inside worktrees.
    audit:
        Audit logger.
    worktree_base:
        Parent directory for worktrees (default: workspace_root/.hermes/worktrees).
    """

    def __init__(
        self,
        workspace: Workspace,
        permission_policy: PermissionPolicy,
        *,
        audit: AuditLogger | None = None,
        worktree_base: str | Path | None = None,
    ) -> None:
        self.workspace = workspace
        self.permission_policy = permission_policy
        self.audit = audit or AuditLogger()
        self.worktree_base = Path(worktree_base) if worktree_base else workspace.root / ".hermes" / "worktrees"

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def create_run(self, task_description: str, roles: list[str] | None = None) -> dict[str, object]:
        """Create a worktree run with task scaffolding.

        Does NOT execute — use :meth:`execute_step` for each task.
        """
        if not self._has_git():
            return {"ok": False, "error": "git_not_available"}
        if not self._is_git_repo():
            return {"ok": False, "error": "not_git_repo"}

        run_id = uuid.uuid4().hex[:12]
        branch = f"codex/task-{run_id}"

        # Create the worktree
        result = self._create_worktree(branch)
        if not result["ok"]:
            return result

        roles = roles or ["planner", "builder", "reviewer"]
        tasks = []
        for role in roles:
            tasks.append(WorktreeTask(
                task_id=uuid.uuid4().hex[:8],
                role=role,
                description=task_description,
            ))

        run = WorktreeRun(
            run_id=run_id,
            worktree_path=Path(result["worktree_path"]),
            branch_name=branch,
            tasks=tasks,
            status="created",
        )

        self.audit.record(
            "worktree_create", "worktree", str(run.worktree_path),
            "allow", f"run={run_id} branch={branch}",
        )

        return {"ok": True, "run": run.to_dict()}

    def execute_step(
        self,
        run: WorktreeRun,
        task_index: int,
        *,
        commands: list[str] | None = None,
        timeout_seconds: float = 120.0,
    ) -> dict[str, object]:
        """Execute a single step in the worktree run.

        Parameters
        ----------
        run:
            The active worktree run.
        task_index:
            Index into ``run.tasks``.
        commands:
            Shell commands to execute.  If ``None``, the task is marked as
            ``awaiting_input`` (for LLM-driven execution).
        timeout_seconds:
            Per-command timeout.
        """
        if task_index < 0 or task_index >= len(run.tasks):
            return {"ok": False, "error": "invalid_task_index"}

        task = run.tasks[task_index]
        run.status = "running"

        if commands is None:
            task.status = "awaiting_input"
            task.log.append("Task awaits LLM-driven execution in worktree.")
            return {"ok": True, "task": task.to_dict(), "worktree_path": str(run.worktree_path)}

        task.status = "in_progress"
        task.started_at = time.perf_counter()

        results = []
        for cmd in commands:
            task.log.append(f"RUN: {cmd}")
            try:
                proc = subprocess.run(
                    shlex.split(cmd),
                    cwd=run.worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                results.append({
                    "command": cmd,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[:5000],
                    "stderr": proc.stderr[:2000],
                })
                task.log.append(f"exit={proc.returncode}")
                if proc.returncode != 0:
                    task.status = "failed"
                    task.completed_at = time.perf_counter()
                    task.result = {"ok": False, "error": "command_failed", "results": results}
                    run.status = "failed"
                    return {"ok": False, "task": task.to_dict(), "run_status": run.status}
            except subprocess.TimeoutExpired:
                task.status = "timeout"
                task.completed_at = time.perf_counter()
                task.result = {"ok": False, "error": "timeout", "results": results}
                run.status = "failed"
                return {"ok": False, "task": task.to_dict(), "run_status": run.status}

        task.status = "completed"
        task.completed_at = time.perf_counter()
        task.result = {"ok": True, "results": results}

        return {"ok": True, "task": task.to_dict(), "run_status": run.status}

    def review_gate(self, run: WorktreeRun) -> dict[str, object]:
        """Review the worktree diff and produce a merge suggestion.

        Does NOT merge — returns structured review for human approval.
        """
        if run.status not in ("running", "awaiting_review"):
            return {"ok": False, "error": "run_not_ready_for_review", "status": run.status}

        # Get diff from the worktree branch vs base
        try:
            proc = subprocess.run(
                ["git", "diff", "--stat", f"HEAD...{run.branch_name}"],
                cwd=run.worktree_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            stat = proc.stdout.strip()
        except Exception:
            stat = ""

        try:
            proc = subprocess.run(
                ["git", "diff", f"HEAD...{run.branch_name}"],
                cwd=run.worktree_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff = proc.stdout[:10000]
        except Exception:
            diff = ""

        try:
            proc = subprocess.run(
                ["git", "log", "--oneline", f"HEAD..{run.branch_name}"],
                cwd=run.worktree_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            commits = proc.stdout.strip()
        except Exception:
            commits = ""

        review = {
            "ok": True,
            "branch": run.branch_name,
            "stat": stat,
            "diff_preview": diff[:5000],
            "commits": commits,
            "merge_suggestion": (
                f"Branch '{run.branch_name}' is ready for review. "
                f"Run: git merge {run.branch_name}  after approval."
            ),
            "destructive_actions": [],
            "test_results": self._run_tests_in_worktree(run),
        }

        run.review_result = review
        run.status = "awaiting_review"

        self.audit.record(
            "worktree_review", "review", str(run.worktree_path),
            "allow", f"branch={run.branch_name}",
            review=review,
        )

        return {"ok": True, "review": review, "run_status": run.status}

    def cleanup(self, run: WorktreeRun) -> dict[str, object]:
        """Remove the worktree and its branch.

        This is a destructive operation — call only after merge or discard.
        """
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(run.worktree_path)],
                cwd=self.workspace.root,
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                ["git", "branch", "-D", run.branch_name],
                cwd=self.workspace.root,
                capture_output=True,
                timeout=5,
            )
        except Exception as exc:
            return {"ok": False, "error": "cleanup_failed", "message": str(exc)}

        run.status = "cleaned_up"
        self.audit.record(
            "worktree_cleanup", "cleanup", str(run.worktree_path),
            "allow", f"branch={run.branch_name}",
        )
        return {"ok": True, "run_status": run.status}

    def list_runs(self, runs: list[WorktreeRun]) -> dict[str, object]:
        """List worktree runs."""
        return {
            "ok": True,
            "runs": [r.to_dict() for r in runs],
            "count": len(runs),
        }

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _has_git(self) -> bool:
        return shutil.which("git") is not None

    def _is_git_repo(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.workspace.root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0 and result.stdout.strip() == "true"
        except Exception:
            return False

    def _create_worktree(self, branch: str) -> dict[str, Any]:
        self.worktree_base.mkdir(parents=True, exist_ok=True)
        wt_path = self.worktree_base / branch.replace("/", "-")

        # Clean up any stale worktree
        if wt_path.exists():
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(wt_path)],
                    cwd=self.workspace.root,
                    capture_output=True,
                    timeout=10,
                )
            except Exception:
                pass
            try:
                shutil.rmtree(wt_path, ignore_errors=True)
            except Exception:
                pass

        try:
            proc = subprocess.run(
                ["git", "worktree", "add", "-b", branch, str(wt_path)],
                cwd=self.workspace.root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                return {"ok": False, "error": "worktree_create_failed", "stderr": proc.stderr}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "worktree_timeout"}
        except Exception as exc:
            return {"ok": False, "error": "worktree_failed", "message": str(exc)}

        return {"ok": True, "worktree_path": str(wt_path), "branch": branch}

    def _run_tests_in_worktree(self, run: WorktreeRun) -> dict[str, Any]:
        """Try to discover and run tests in the worktree."""
        test_result: dict[str, Any] = {"ran": False, "message": "No test discovery attempted."}
        # Try pytest
        if (run.worktree_path / "tests").exists() or (run.worktree_path / "test").exists():
            try:
                proc = subprocess.run(
                    ["python", "-m", "pytest", "-p", "no:cacheprovider", "-q"],
                    cwd=run.worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                test_result = {
                    "ran": True,
                    "runner": "pytest",
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[:3000],
                }
            except Exception as exc:
                test_result = {"ran": False, "error": str(exc)}
        return test_result
