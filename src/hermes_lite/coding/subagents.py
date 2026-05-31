"""Clean-room subagent planning and orchestration primitives.

Supports:
- :class:`SubagentPlan` — planner/builder/reviewer task bundles
- :class:`WorktreeExecutor` — isolated git worktree execution
- :func:`create_subagent_plan` — deterministic plan generation
- :func:`execute_subagent_plan` — orchestrate a plan through a WorktreeExecutor
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import re
from pathlib import Path

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
# code review
# ---------------------------------------------------------------------------

# Security patterns that trigger findings
_SECURITY_PATTERNS: list[tuple[str, str, str]] = [
    (r"os\.system\(", "os.system", "Prefer subprocess.run over os.system — avoids shell injection."),
    (r"subprocess\.\w+\([^)]*shell\s*=\s*True", "shell=True", "shell=True is a shell injection risk when user input reaches the command."),
    (r"exec\(", "exec()", "exec() on untrusted input is arbitrary code execution."),
    (r"eval\(", "eval()", "eval() on untrusted input is a code injection risk."),
    (r"\.execute\s*\(\s*f['\"]", "SQL execute", "Use parameterised queries — f-strings in SQL are injection-prone."),
    (r"hashlib\.md5\(|hashlib\.sha1\(", "weak hash", "md5/sha1 are cryptographically broken. Use sha256 or better."),
    (r"password\s*=\s*['\"]\w", "hardcoded secret", "Hard-coded credential detected. Use environment variables or a vault."),
    (r"api_key\s*=\s*['\"]\w", "hardcoded key", "API key in source. Use environment variables."),
]

_CORRECTNESS_PATTERNS: list[tuple[str, str, str]] = [
    (r"except\s*:\s*$", "bare except", "Bare 'except:' catches KeyboardInterrupt and SystemExit. Be specific."),
    (r"except\s+Exception\s*:\s*pass\s*$", "silenced exception", "Silenced exception hides errors. At minimum log the error."),
    (r"time\.sleep\(", "time.sleep", "time.sleep in production code may indicate a missing proper wait/retry mechanism."),
]

_STYLE_PATTERNS: list[tuple[str, str, str]] = [
    (r"def \w+\(\):\s*\n\s+pass", "empty function", "Empty function body. Either implement or add a TODO."),
]


@dataclass(frozen=True)
class ReviewChecklist:
    """Structured review checklist categories."""

    security: list[str] = field(default_factory=lambda: [
        "No command injection (shell=True, os.system, eval, exec)",
        "No SQL injection (parameterised queries used)",
        "No hard-coded secrets or API keys",
        "No weak cryptographic primitives (md5, sha1)",
    ])
    correctness: list[str] = field(default_factory=lambda: [
        "No bare except clauses",
        "No silently swallowed exceptions",
        "Edge cases handled (empty input, None, large values)",
        "No race conditions in shared state",
    ])
    style: list[str] = field(default_factory=lambda: [
        "Consistent naming with project conventions",
        "Functions / methods are a manageable size (< 60 lines)",
        "No commented-out code left behind",
    ])
    tests: list[str] = field(default_factory=lambda: [
        "Happy-path test exists",
        "Error-path test exists",
        "Edge case covered (empty, max, boundary)",
    ])

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "security": self.security,
            "correctness": self.correctness,
            "style": self.style,
            "tests": self.tests,
        }


def run_code_review(
    diff_text: str, workspace: Workspace
) -> dict[str, object]:
    """Run an automated code review on a diff.

    Scans the diff for security, correctness, and style issues using
    structural patterns.  Returns structured findings with severity and
    suggestions.
    """
    if not diff_text.strip():
        return {
            "ok": True,
            "findings": [],
            "summary": "No diff to review.",
            "checklist": ReviewChecklist().to_dict(),
        }

    findings: list[dict[str, object]] = []
    added_lines = _extract_added_lines(diff_text)

    for pattern, title, suggestion in _SECURITY_PATTERNS:
        for lineno, line in added_lines:
            if re.search(pattern, line):
                findings.append({
                    "severity": "high",
                    "category": "security",
                    "title": title,
                    "line": lineno,
                    "code": line.strip(),
                    "suggestion": suggestion,
                })

    for pattern, title, suggestion in _CORRECTNESS_PATTERNS:
        for lineno, line in added_lines:
            if re.search(pattern, line):
                findings.append({
                    "severity": "medium",
                    "category": "correctness",
                    "title": title,
                    "line": lineno,
                    "code": line.strip(),
                    "suggestion": suggestion,
                })

    for pattern, title, suggestion in _STYLE_PATTERNS:
        for lineno, line in added_lines:
            if re.search(pattern, line):
                findings.append({
                    "severity": "low",
                    "category": "style",
                    "title": title,
                    "line": lineno,
                    "code": line.strip(),
                    "suggestion": suggestion,
                })

    # Deduplicate by title+line
    seen: set[tuple[str, int]] = set()
    unique: list[dict[str, object]] = []
    for f in findings:
        key = (str(f["title"]), int(f["line"]))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    high = sum(1 for f in unique if f["severity"] == "high")
    medium = sum(1 for f in unique if f["severity"] == "medium")
    low = sum(1 for f in unique if f["severity"] == "low")

    return {
        "ok": True,
        "findings": unique,
        "counts": {"high": high, "medium": medium, "low": low, "total": len(unique)},
        "summary": f"{len(unique)} finding(s): {high} high, {medium} medium, {low} low",
        "checklist": ReviewChecklist().to_dict(),
    }


def _extract_added_lines(diff_text: str) -> list[tuple[int, str]]:
    """Extract added lines with their new file line numbers from a unified diff."""
    result: list[tuple[int, str]] = []
    current_line = 0
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            if m:
                current_line = int(m.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            result.append((current_line, line[1:]))
            current_line += 1
        elif not line.startswith("-") and not line.startswith("---"):
            current_line += 1
    return result


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


# ---------------------------------------------------------------------------
# plan persistence
# ---------------------------------------------------------------------------


def _plans_dir(workspace_root: str) -> Path:
    d = Path(workspace_root) / ".hermes" / "plans"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_plan(plan: SubagentPlan | dict[str, object], workspace_root: str) -> dict[str, object]:
    """Persist a plan to ``.hermes/plans/<plan_id>.json``."""
    if isinstance(plan, SubagentPlan):
        data = plan.to_dict()
    else:
        data = dict(plan)
    plan_id = str(data.get("plan_id", uuid.uuid4().hex[:12]))
    data.setdefault("plan_id", plan_id)
    data.setdefault("status", "draft")

    path = _plans_dir(workspace_root) / f"{plan_id}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "plan_id": plan_id, "path": str(path)}


def load_plan(plan_id: str, workspace_root: str) -> dict[str, object]:
    """Load a persisted plan by ID."""
    path = _plans_dir(workspace_root) / f"{plan_id}.json"
    if not path.exists():
        return {"ok": False, "error": "plan_not_found", "plan_id": plan_id}
    try:
        return {"ok": True, "plan": json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"ok": False, "error": "plan_read_failed", "detail": str(exc)}


def list_plans(workspace_root: str) -> dict[str, object]:
    """List all persisted plans."""
    d = _plans_dir(workspace_root)
    if not d.exists():
        return {"ok": True, "plans": [], "total": 0}
    plans = []
    for f in sorted(d.glob("*.json")):
        try:
            plans.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return {"ok": True, "plans": plans, "total": len(plans)}


def approve_plan(
    plan_id: str, workspace: Workspace, permission_policy: PermissionPolicy,
) -> dict[str, object]:
    """Approve and execute a persisted plan via WorktreeExecutor."""
    loaded = load_plan(plan_id, str(workspace.root))
    if not loaded.get("ok"):
        return loaded

    task = str(loaded.get("plan", {}).get("task", "coding task"))
    executor = WorktreeExecutor(workspace, permission_policy)

    create_result = executor.create_run(task, roles=["planner", "builder", "reviewer"])
    if not create_result.get("ok"):
        return create_result

    raw_run = create_result["run"]
    run = _reconstruct_run(raw_run, executor)

    for i in range(3):
        step = executor.execute_step(run, i, commands=None)
        if not step.get("ok"):
            return {
                "ok": False,
                "error": "step_execution_failed",
                "step_index": i,
                "step": step,
                "plan_id": plan_id,
            }

    review = executor.review_gate(run)

    # Mark plan as executed
    save_plan({"plan_id": plan_id, "status": "executed"}, str(workspace.root))

    return {
        "ok": True,
        "plan_id": plan_id,
        "run": run.to_dict(),
        "review": review.get("review", {}),
    }


# ---------------------------------------------------------------------------
# LLM-driven sub-agent dispatch
# ---------------------------------------------------------------------------

# Tool whitelists per role — each role gets only the tools it needs
_SUBAGENT_TOOLSETS: dict[str, set[str]] = {
    "planner": {
        "read_file", "list_files", "search_text", "repo_map",
        "rank_files", "project_map", "find_test_files", "recent_changes",
        "workspace_status", "workspace_context", "read_rules",
    },
    "builder": {
        "read_file", "write_file", "apply_patch", "apply_unified_diff",
        "edit_file", "patch_dry_run", "diff_summary",
        "run_command", "list_files", "search_text", "git_status", "git_diff",
        "python_diagnostics", "python_symbols",
        "discover_tests", "run_tests",
    },
    "reviewer": {
        "read_file", "git_status", "git_diff", "code_review",
        "diff_summary", "list_files", "search_text",
        "python_diagnostics", "run_tests",
    },
}


def get_role_tools(role: str) -> set[str]:
    """Return the tool whitelist for a sub-agent role."""
    return _SUBAGENT_TOOLSETS.get(role, set())


async def dispatch_subagent(
    role: str,
    task: str,
    *,
    workspace: Workspace,
    config: Any,  # ProviderConfig
    policy: PermissionPolicy,
    base_persona: str = "",
    max_turns: int = 20,
) -> dict[str, object]:
    """Dispatch a task to an LLM-driven sub-agent with a restricted tool set.

    The sub-agent gets its own ``HermesAgent`` instance with only the tools
    allowed for its role.  It runs inside the workspace (not a separate
    worktree) for speed.

    Parameters
    ----------
    role:
        One of ``"planner"``, ``"builder"``, ``"reviewer"``.
    task:
        The task description for the sub-agent.
    workspace:
        The workspace to operate in.
    config:
        ProviderConfig for the LLM.
    policy:
        Permission policy (passed through to the sub-agent's tool handler).
    base_persona:
        Optional base persona text (prepended to role-specific prompt).
    max_turns:
        Maximum tool-call turns before forcing a response.

    Returns
    -------
    Structured result with ``output``, ``tool_calls_made``, ``turns``.
    """
    # Import here to avoid circular import at module level
    from hermes_lite.agent import HermesAgent  # noqa: F811
    from hermes_lite.tools.coding import register_coding_tools
    from hermes_lite.tools.registry import ToolRegistry

    allowed = get_role_tools(role)
    if not allowed:
        return {"ok": False, "error": f"unknown_role: {role}"}

    role_personas = {
        "planner": (
            "You are a planning specialist. Inspect the repository structure, "
            "identify relevant files, and produce a clear, step-by-step "
            "implementation plan. Do NOT write any code — only read and plan.\n\n"
            "Output format: numbered list of steps, each with file paths and "
            "a brief description of what to change."
        ),
        "builder": (
            "You are a code implementation specialist. Follow the plan and "
            "implement the changes described. Write real, compilable code. "
            "Run tests after making changes to verify correctness.\n\n"
            "Be precise — make minimal edits to achieve the goal."
        ),
        "reviewer": (
            "You are a code review specialist. Review the diff, run tests, "
            "and produce a structured review with findings categorized by "
            "severity (high/medium/low) and category (security/correctness/style/tests)."
        ),
    }

    persona = role_personas.get(role, f"You are a {role} specialist.")
    if base_persona:
        persona = base_persona + "\n\n" + persona

    # Build a restricted tool registry
    full_registry = ToolRegistry()
    register_coding_tools(full_registry, workspace, policy)

    restricted = ToolRegistry()
    for tool_info in full_registry.list_tools():
        name = tool_info["name"]
        if name in allowed:
            handler = full_registry._tools[name]["handler"]
            schema = full_registry._tools[name]["schema"]
            restricted.register(
                name=name,
                schema=schema,
                handler=handler,
                toolset="coding",
                parallel_safe=tool_info.get("parallel_safe", False),
            )

    # Create sub-agent with restricted tools
    sub_agent = HermesAgent(
        config=config,
        persona=persona,
        tool_registry=restricted,
        defer_model_check=True,
    )

    try:
        output, _messages = await sub_agent.run(task, max_turns=max_turns)
        return {
            "ok": True,
            "role": role,
            "output": output,
            "turns_taken": _count_tool_calls(_messages),
            "message_count": len(_messages),
        }
    except Exception as exc:
        return {
            "ok": False,
            "role": role,
            "error": "subagent_failed",
            "detail": str(exc),
        }


def _count_tool_calls(messages: list) -> int:
    """Count tool call parts in a message list."""
    count = 0
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if part.__class__.__name__ == "ToolCallPart":
                count += 1
    return count


def security_audit(workspace_root: str) -> dict[str, Any]:
    """Run security audit on project dependencies using pip-audit or npm audit."""
    import json as _json
    import subprocess as _subprocess
    from pathlib import Path as _Path

    root = _Path(workspace_root)
    results: list[dict[str, Any]] = []

    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        try:
            proc = _subprocess.run(
                ["pip-audit", "-r", str(root), "--format", "json"],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode == 0:
                results.append({"ecosystem": "python", "ok": True, "vulnerabilities": 0})
            else:
                data = _json.loads(proc.stdout) if proc.stdout.strip() else {}
                vulns = len(data.get("dependencies", [])) if isinstance(data, dict) else 0
                results.append({"ecosystem": "python", "ok": False, "vulnerabilities": vulns, "detail": proc.stdout[:2000]})
        except (FileNotFoundError, _subprocess.TimeoutExpired):
            results.append({"ecosystem": "python", "ok": True, "available": False, "hint": "pip-audit not installed"})

    if (root / "package.json").exists():
        try:
            proc = _subprocess.run(
                ["npm", "audit", "--json"], capture_output=True, text=True, timeout=60, cwd=str(root),
            )
            data = _json.loads(proc.stdout) if proc.stdout.strip() else {}
            vulns = data.get("metadata", {}).get("vulnerabilities", {}).get("total", 0)
            results.append({"ecosystem": "node", "ok": vulns == 0, "vulnerabilities": vulns})
        except (FileNotFoundError, _subprocess.TimeoutExpired, _json.JSONDecodeError):
            results.append({"ecosystem": "node", "ok": True, "available": False})

    return {"ok": True, "audited": bool(results), "total_vulnerabilities": sum(r.get("vulnerabilities", 0) for r in results), "results": results}

