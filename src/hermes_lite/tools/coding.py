"""Coding-agent tool registrations."""

from __future__ import annotations

import json
from typing import Any, Callable

from hermes_lite.coding.context import (
    build_project_map,
    find_test_files,
    list_files,
    rank_files,
    recent_changes,
    repo_map_summary,
    search_text,
)
from hermes_lite.coding.diagnostics import diagnose_python, extract_python_symbols
from hermes_lite.coding.ast_analysis import build_call_graph, extract_symbols, find_references
from hermes_lite.coding.extensibility import hook_status, load_external_tools, load_mcp_servers, run_hooks
from hermes_lite.coding.multimodal import read_image, read_image_supported
from hermes_lite.coding.notebook import (
    notebook_delete_cell,
    notebook_edit_cell,
    notebook_insert_cell,
    notebook_read_all_cells,
    notebook_read_cell,
)
import asyncio

from hermes_lite.coding.notify import notify as _notify_send
from hermes_lite.coding.git import GitClient
from hermes_lite.coding.lsp import (
    discover_lsp_servers,
    lsp_definition,
    lsp_diagnostics,
    lsp_hover,
    lsp_references,
    lsp_status,
    lsp_symbols,
)
from hermes_lite.coding.mcp_client import McpClientManager
from hermes_lite.coding.patches import (
    _fuzzy_find,
    apply_text_patch,
    apply_unified_diff,
    diff_summary,
    edit_batch,
    patch_dry_run,
)
from hermes_lite.coding.permissions import PermissionDecision, PermissionPolicy
from hermes_lite.coding.sessions import SessionManager
from hermes_lite.coding.shell import CommandRunner
from hermes_lite.coding.subagents import (
    approve_plan,
    create_subagent_plan,
    dispatch_subagent,
    execute_subagent_plan,
    list_plans,
    run_code_review,
    save_plan,
    subagent_execute_with_commands,
)
from hermes_lite.coding.context_inject import discover_rules, workspace_snapshot
from hermes_lite.coding.testing import discover_tests, extract_failure_locations, run_tests, debug_error
from hermes_lite.coding.todo import todo_create, todo_list as _todo_list, todo_update
from hermes_lite.coding.embeddings import semantic_search, build_semantic_index
from hermes_lite.coding.scaffold import scaffold_project, scaffold_list_templates
from hermes_lite.coding.subagents import security_audit
from hermes_lite.coding.watch import watch_status
from hermes_lite.coding.web import web_fetch, web_search
from hermes_lite.coding.worktree_exec import WorktreeExecutor
from hermes_lite.coding.workspace import Workspace
from hermes_lite.tools.registry import ToolRegistry


def _render_diagram(mermaid_source: str, *, output_path: str = "") -> dict[str, object]:
    """Store mermaid diagram source for rendering.

    When *output_path* is non-empty, writes the mermaid source to that file.
    Otherwise returns a structured representation for the agent.
    """
    if output_path:
        from pathlib import Path
        p = Path(output_path)
        p.write_text(mermaid_source, encoding="utf-8")
        return {"ok": True, "saved": True, "path": output_path, "bytes": len(mermaid_source)}
    lines = mermaid_source.strip().splitlines()
    return {
        "ok": True,
        "saved": False,
        "format": "mermaid",
        "lines": len(lines),
        "source_preview": mermaid_source[:2000],
    }


def _render_edit_preview(
    path: str, old_text: str, new_text: str, dry: dict[str, object],
) -> str:
    """Render a human-readable diff preview from edit parameters."""
    lines: list[str] = []
    lines.append(f"File: {path}")
    matches = dry.get("matches", 0)
    lines.append(f"Matches: {matches}")
    if old_text:
        lines.append(f"\n- {old_text.strip()}")
    if new_text:
        lines.append(f"+ {new_text.strip()}")
    return "\n".join(lines)


def _apply_patch_with_confirm(
    workspace: Workspace, policy: PermissionPolicy,
    path: str, old_text: str, new_text: str, *, replace_all: bool = False,
    fuzzy: bool = False,
) -> dict[str, object]:
    """Apply a text patch with edit confirmation when interactive."""
    check = workspace.resolve(path, operation="write")
    decision = policy.decide_write(check)
    if decision.denied:
        result: dict[str, object] = decision.to_dict()
        result.update({"ok": False, "error": "permission_denied", "reason": decision.reason})
        return result
    if decision.requires_approval:
        current = workspace.read_text(path)
        old_content = current.get("content", "") if current.get("ok") else ""
        # Run a dry preview — note: apply_text_patch doesn't have a real dry_run
        # so we use a heuristic: try to find the match and render the preview
        read_r = workspace.read_text(path)
        if read_r.get("ok"):
            match_key = old_text
            file_content = str(read_r["content"])
            if old_text not in file_content and fuzzy:
                match_key = _fuzzy_find(file_content, old_text) or old_text
            diff_text = _render_edit_preview(path, match_key, new_text, {"matches": 1 if match_key else 0, "content": file_content})
        else:
            diff_text = f"- {old_text}\n+ {new_text}"
        decision.edit_preview = f"Edit preview for {path}:\n{diff_text}"
        if not policy.confirm(decision):
            return {"ok": False, "error": "edit_rejected",
                    "message": f"Edit to {path} was not confirmed."}
    return apply_text_patch(workspace, path, old_text, new_text, replace_all=replace_all, fuzzy=fuzzy)


def _apply_unified_diff_with_confirm(
    workspace: Workspace, policy: PermissionPolicy,
    path: str, diff_text: str, *, dry_run: bool = False, fuzzy: int = 0,
) -> dict[str, object]:
    """Apply a unified diff with edit confirmation when interactive."""
    check = workspace.resolve(path, operation="write")
    decision = policy.decide_write(check)
    if decision.denied:
        result: dict[str, object] = decision.to_dict()
        result.update({"ok": False, "error": "permission_denied", "reason": decision.reason})
        return result
    if decision.requires_approval and not dry_run:
        decision.edit_preview = f"Unified diff for {path}:\n{diff_text[:2000]}"
        if not policy.confirm(decision):
            return {"ok": False, "error": "edit_rejected",
                    "message": f"Unified diff to {path} was not confirmed."}
    return apply_unified_diff(workspace, path, diff_text, dry_run=dry_run, fuzzy=fuzzy)


def register_coding_tools(
    registry: ToolRegistry,
    workspace: Workspace,
    permission_policy: PermissionPolicy | None = None,
    *,
    session_manager: SessionManager | None = None,
    mcp_manager: McpClientManager | None = None,
    worktree_executor: WorktreeExecutor | None = None,
    skill_manager: Any | None = None,
) -> None:
    """Register workspace-aware coding tools."""
    policy = permission_policy or PermissionPolicy()
    runner = CommandRunner(workspace, policy)
    git = GitClient(workspace)
    sessions = session_manager or SessionManager(workspace, policy)
    mcp = mcp_manager or McpClientManager(workspace)
    wt_exec = worktree_executor or WorktreeExecutor(workspace, policy)

    def _edit_file(
        path: str, old_text: str, new_text: str,
        *, replace_all: bool = False, preview_only: bool = False,
    ) -> dict[str, object]:
        """Unified edit entry point: dry_run first, then apply or preview."""
        check = workspace.resolve(path, operation="write")
        decision = policy.decide_write(check)
        if decision.denied:
            result = decision.to_dict()
            result.update({"ok": False, "error": "permission_denied", "reason": decision.reason})
            return result

        current = workspace.read_text(path)
        old_content = current.get("content", "") if current.get("ok") else ""

        dry = apply_text_patch(workspace, path, old_text, new_text, replace_all=replace_all, dry_run=True)
        if not dry.get("ok"):
            return dry

        if preview_only:
            preview = diff_summary(workspace, path, old_content)
            return {
                "ok": True,
                "applied": False,
                "preview_only": True,
                "matches_found": dry.get("matches", 0),
                "diff_preview": preview.get("diff_preview", ""),
                "added_lines": preview.get("added_lines", 0),
                "removed_lines": preview.get("removed_lines", 0),
            }

        # Show diff preview and ask for confirmation when in interactive mode
        if decision.requires_approval:
            preview = diff_summary(workspace, path, old_content)
            diff_text = preview.get("diff_preview", "") or _render_edit_preview(
                path, old_text, new_text, dry,
            )
            decision.edit_preview = f"Edit preview for {path}:\n{diff_text}"
            if not policy.confirm(decision):
                return {"ok": False, "error": "edit_rejected",
                        "message": f"Edit to {path} was not confirmed."}

        result = apply_text_patch(workspace, path, old_text, new_text, replace_all=replace_all)
        preview = diff_summary(workspace, path, old_content) if old_content else {"diff_preview": ""}
        result["diff_preview"] = preview.get("diff_preview", "")
        result["preview_only"] = False
        # Run post-edit hooks (lint, format, etc.)
        if result.get("ok"):
            try:
                from hermes_lite.coding.extensibility import run_post_edit_hooks
                hooks_result = run_post_edit_hooks(workspace, path)
                if hooks_result.get("ran", 0) > 0:
                    result["post_edit_hooks"] = hooks_result
            except Exception:
                pass
        return result

    def _dispatch_sync(
        role: str, task: str, ws: Workspace, pol: PermissionPolicy,
        executor: WorktreeExecutor,
    ) -> dict[str, object]:
        """Sync sub-agent dispatch: creates worktree, runs role commands, returns result."""
        from hermes_lite.coding.subagents import create_subagent_plan, _SUBAGENT_TOOLSETS

        if role not in ("planner", "builder", "reviewer"):
            return {"ok": False, "error": f"unknown_role: {role}"}

        plan = create_subagent_plan(task)
        create_result = executor.create_run(task, roles=[role])
        if not create_result.get("ok"):
            return create_result

        raw_run = create_result["run"]
        run = _reconstruct_run_for_dispatch(raw_run, executor)

        # Role-specific discovery commands
        role_commands: dict[str, list[str]] = {
            "planner": [
                "find . -type f -name '*.py' | head -30",
                "cat pyproject.toml 2>/dev/null || cat setup.py 2>/dev/null || echo 'no project config'",
                "ls -la tests/ 2>/dev/null || ls -la test/ 2>/dev/null || echo 'no tests dir'",
            ],
            "builder": [
                f"echo 'Task: {task}'",
                "find . -type f -name '*.py' | head -20",
            ],
            "reviewer": [
                "git diff --stat 2>/dev/null || echo 'no git diff'",
                "git diff 2>/dev/null | head -100 || echo 'no changes'",
            ],
        }

        cmds = role_commands.get(role, ["echo 'no commands defined'"])
        step = executor.execute_step(run, 0, commands=cmds)

        return {
            "ok": step.get("ok", False),
            "role": role,
            "task": task,
            "plan_id": plan.plan_id,
            "branch": str(raw_run.get("branch_name", "")),
            "output": step.get("output", ""),
            "toolset": sorted(_SUBAGENT_TOOLSETS.get(role, set())),
        }

    def _reconstruct_run_for_dispatch(raw_run: dict[str, object], executor: WorktreeExecutor) -> Any:
        from hermes_lite.coding.worktree_exec import WorktreeRun, WorktreeTask
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

    def as_json(func: Callable[..., dict[str, object]]) -> Callable[..., str]:
        def wrapper(**kwargs: Any) -> str:
            return json.dumps(func(**kwargs))

        return wrapper

    def workspace_status() -> dict[str, object]:
        return {
            "ok": True,
            "workspace": workspace.summary(),
            "permissions": policy.summary(),
            "git": git.worktree_status(),
        }

    def read_file(path: str, offset: int = 1, limit: int = 500, max_bytes: int = 1_000_000) -> dict[str, object]:
        check = workspace.resolve(path, operation="read")
        decision = policy.decide_read(check)
        if not decision.allowed:
            result = decision.to_dict()
            result.update({"ok": False, "error": "permission_denied", "reason": decision.reason})
            return result
        try:
            size = check.path.stat().st_size
        except OSError:
            size = 0
        if size > max_bytes:
            return {
                "ok": False,
                "error": "file_too_large",
                "path": str(check.relative_path),
                "size": size,
                "max_bytes": max_bytes,
                "message": f"File is {size} bytes, exceeds max {max_bytes}. Use a smaller max_bytes or read with offset/limit.",
            }
        result = workspace.read_text(path)
        if not result["ok"]:
            return result
        lines = str(result["content"]).splitlines()
        start = max(offset, 1) - 1
        selected = lines[start : start + max(limit, 1)]
        result.update({
            "offset": start + 1,
            "limit": limit,
            "total_lines": len(lines),
            "numbered_content": "\n".join(
                f"{start + index + 1:>6}|{line}" for index, line in enumerate(selected)
            ),
        })
        return result

    def write_file(path: str, content: str) -> dict[str, object]:
        check = workspace.resolve(path, operation="write")
        decision = policy.decide_write(check)
        if decision.denied:
            result = decision.to_dict()
            result.update({"ok": False, "error": "permission_denied", "reason": decision.reason})
            return result
        if decision.requires_approval:
            current = workspace.read_text(path)
            old_content = current.get("content", "") if current.get("ok") else ""
            preview = ""
            if old_content:
                preview = f"--- a/{path}\n+++ b/{path}\n@@ -1,{len(old_content.splitlines())} +1,{len(content.splitlines())} @@\n"
                for line in old_content.splitlines():
                    preview += f"-{line}\n"
                for line in content.splitlines():
                    preview += f"+{line}\n"
            else:
                preview = f"New file: {path}\n+{content[:500]}"
            decision.edit_preview = f"Write preview for {path}:\n{preview}"
            if not policy.confirm(decision):
                return {"ok": False, "error": "edit_rejected",
                        "message": f"Write to {path} was not confirmed."}
        result = workspace.write_text(path, content)
        if result.get("ok"):
            try:
                from hermes_lite.coding.extensibility import run_post_edit_hooks
                hooks_result = run_post_edit_hooks(workspace, path)
                if hooks_result.get("ran", 0) > 0:
                    result["post_edit_hooks"] = hooks_result
            except Exception:
                pass
        return result

    registry.register(
        name="workspace_status",
        schema={"description": "Return workspace, permissions, and git status.", "properties": {}, "required": []},
        handler=as_json(lambda: workspace_status()),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="list_files",
        schema={
            "description": "List non-protected workspace files.",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern, default **/*."},
                "limit": {"type": "integer", "description": "Maximum files to return."},
            },
            "required": [],
        },
        handler=as_json(lambda pattern="**/*", limit=200: list_files(workspace, pattern=pattern, limit=limit)),
        toolset="coding",
    )
    registry.register(
        name="search_text",
        schema={
            "description": "Search workspace text files for a literal query.",
            "properties": {
                "query": {"type": "string", "description": "Literal search query."},
                "path": {"type": "string", "description": "File or directory to search."},
                "limit": {"type": "integer", "description": "Maximum matches."},
            },
            "required": ["query"],
        },
        handler=as_json(lambda query, path=".", limit=100: search_text(workspace, query, path=path, limit=limit)),
        toolset="coding",
    )
    registry.register(
        name="read_file",
        schema={
            "description": "Read a workspace file with line-number metadata. Refuses files over max_bytes (default 1MB).",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
                "max_bytes": {"type": "integer", "description": "Maximum file size in bytes to read (default 1,000,000)."},
            },
            "required": ["path"],
        },
        handler=as_json(read_file),
        toolset="coding",
    )
    registry.register(
        name="write_file",
        schema={
            "description": "Write a workspace file after permission checks.",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        handler=as_json(write_file),
        toolset="coding",
    )
    registry.register(
        name="apply_patch",
        schema={
            "description": "Apply an exact text replacement to a workspace file.",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_text", "new_text"],
        },
        handler=as_json(
            lambda path, old_text, new_text, replace_all=False: _apply_patch_with_confirm(
                workspace, policy, path, old_text, new_text, replace_all=replace_all,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="apply_unified_diff",
        schema={
            "description": "Apply a unified diff patch to a workspace file (multi-hunk).",
            "properties": {
                "path": {"type": "string"},
                "diff_text": {"type": "string"},
                "dry_run": {"type": "boolean"},
                "fuzzy": {"type": "integer"},
            },
            "required": ["path", "diff_text"],
        },
        handler=as_json(
            lambda path, diff_text, dry_run=False, fuzzy=0: _apply_unified_diff_with_confirm(
                workspace, policy, path, diff_text, dry_run=dry_run, fuzzy=fuzzy,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="patch_dry_run",
        schema={
            "description": "Validate a unified diff applies cleanly without writing.",
            "properties": {
                "path": {"type": "string"},
                "diff_text": {"type": "string"},
                "fuzzy": {"type": "integer"},
            },
            "required": ["path", "diff_text"],
        },
        handler=as_json(
            lambda path, diff_text, fuzzy=0: patch_dry_run(
                workspace, path, diff_text, fuzzy=fuzzy,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="diff_summary",
        schema={
            "description": "Show added/removed line counts and diff preview for a file.",
            "properties": {
                "path": {"type": "string"},
                "old_content": {"type": "string"},
            },
            "required": ["path"],
        },
        handler=as_json(
            lambda path, old_content=None: diff_summary(workspace, path, old_content)
        ),
        toolset="coding",
    )
    registry.register(
        name="run_command",
        schema={
            "description": "Run a non-destructive command inside the workspace.",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "number"},
            },
            "required": ["command"],
        },
        handler=as_json(lambda command, cwd=".", timeout_seconds=None: runner.run(command, cwd=cwd, timeout_seconds=timeout_seconds)),
        toolset="coding",
    )
    registry.register(
        name="git_status",
        schema={"description": "Return git short status.", "properties": {}, "required": []},
        handler=as_json(lambda: git.status()),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="git_diff",
        schema={
            "description": "Return git diff output.",
            "properties": {"path": {"type": "string"}, "stat": {"type": "boolean"}},
            "required": [],
        },
        handler=as_json(lambda path="", stat=False: git.diff(path=path, stat=stat)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="project_map",
        schema={
            "description": "Return project language and structure summary.",
            "properties": {"limit": {"type": "integer"}},
            "required": [],
        },
        handler=as_json(lambda limit=2000: build_project_map(workspace, limit=limit)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="rank_files",
        schema={
            "description": "Rank workspace files for a query.",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
        handler=as_json(lambda query, limit=20: rank_files(workspace, query, limit=limit)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="recent_changes",
        schema={
            "description": "List recently modified files (git log or filesystem mtime).",
            "properties": {"count": {"type": "integer"}},
            "required": [],
        },
        handler=as_json(lambda count=20: recent_changes(workspace, count=count)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="find_test_files",
        schema={
            "description": "Find test files likely associated with a source file.",
            "properties": {"source_path": {"type": "string"}},
            "required": ["source_path"],
        },
        handler=as_json(lambda source_path: find_test_files(workspace, source_path)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="repo_map",
        schema={
            "description": "Token-aware compact repository overview for LLM context.",
            "properties": {
                "token_budget": {"type": "integer"},
                "include_recent": {"type": "boolean"},
            },
            "required": [],
        },
        handler=as_json(
            lambda token_budget=2000, include_recent=True: repo_map_summary(
                workspace, token_budget=token_budget, include_recent=include_recent,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="python_diagnostics",
        schema={
            "description": "Run Python syntax diagnostics.",
            "properties": {"path": {"type": "string"}},
            "required": [],
        },
        handler=as_json(lambda path=".": diagnose_python(workspace, path)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="python_symbols",
        schema={
            "description": "Extract Python classes and functions.",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=as_json(lambda path: extract_python_symbols(workspace, path)),
        toolset="coding",
        parallel_safe=True,
    )

    # -- code_structure (deep AST analysis) --------------------------------

    # Note: extract_symbols and extract_python_symbols are both available.
    # extract_symbols returns richer output (methods, imports, annotations).

    registry.register(
        name="code_structure",
        schema={
            "description": "Extract structured symbols from a Python file: classes with methods, functions with args/return types, imports, assignments.",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace."},
            },
            "required": ["path"],
        },
        handler=as_json(lambda path: extract_symbols(workspace, path)),
        toolset="coding",
        parallel_safe=True,
    )

    # -- call_graph -------------------------------------------------------

    registry.register(
        name="call_graph",
        schema={
            "description": "Build a cross-file call graph for Python code showing which functions call which.",
            "properties": {
                "file_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Glob patterns for files to include (default: ['**/*.py']).",
                },
            },
            "required": [],
        },
        handler=as_json(lambda file_patterns=None: build_call_graph(
            workspace, file_patterns=file_patterns,
        )),
        toolset="coding",
        parallel_safe=True,
    )

    # -- find_symbol ------------------------------------------------------

    registry.register(
        name="find_symbol",
        schema={
            "description": "Find where a symbol is defined, referenced textually, and how it's called.",
            "properties": {
                "name": {"type": "string", "description": "Unqualified symbol name (e.g. 'authenticate')."},
            },
            "required": ["name"],
        },
        handler=as_json(lambda name: find_references(workspace, name)),
        toolset="coding",
        parallel_safe=True,
    )

    registry.register(
        name="external_tools",
        schema={"description": "List configured external tools.", "properties": {}, "required": []},
        handler=as_json(lambda: load_external_tools(workspace)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="mcp_servers",
        schema={"description": "List configured MCP servers.", "properties": {}, "required": []},
        handler=as_json(lambda: load_mcp_servers(workspace)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="hook_status",
        schema={"description": "List configured hooks without running them.", "properties": {}, "required": []},
        handler=as_json(lambda: hook_status(workspace)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="subagent_plan",
        schema={
            "description": "Create a clean-room planner/builder/reviewer subagent plan.",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
        },
        handler=as_json(lambda task: create_subagent_plan(task).to_dict()),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="worktree_status",
        schema={"description": "Inspect git worktree status.", "properties": {}, "required": []},
        handler=as_json(lambda: git.worktree_status()),
        toolset="coding",
        parallel_safe=True,
    )

    # -- long-running command sessions ----------------------------------

    registry.register(
        name="start_command",
        schema={
            "description": "Start a long-running command in the background.",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run."},
                "cwd": {"type": "string", "description": "Working directory."},
                "pty": {"type": "boolean", "description": "Use PTY for interactive commands."},
                "timeout_seconds": {"type": "number", "description": "Auto-stop after N seconds."},
            },
            "required": ["command"],
        },
        handler=as_json(
            lambda command, cwd=".", pty=False, timeout_seconds=None: sessions.start(
                command, cwd=cwd, pty=pty, timeout_seconds=timeout_seconds
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="read_command",
        schema={
            "description": "Read buffered output from a running command session.",
            "properties": {
                "session_id": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["session_id"],
        },
        handler=as_json(
            lambda session_id, offset=0, limit=100: sessions.read(
                session_id, offset=offset, limit=limit
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="write_stdin",
        schema={
            "description": "Send input to a running command session.",
            "properties": {
                "session_id": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["session_id", "text"],
        },
        handler=as_json(
            lambda session_id, text: sessions.write_stdin(session_id, text)
        ),
        toolset="coding",
    )
    registry.register(
        name="stop_command",
        schema={
            "description": "Stop a running command session.",
            "properties": {
                "session_id": {"type": "string"},
                "force": {"type": "boolean"},
            },
            "required": ["session_id"],
        },
        handler=as_json(
            lambda session_id, force=False: sessions.stop(session_id, force=force)
        ),
        toolset="coding",
    )
    registry.register(
        name="list_sessions",
        schema={
            "description": "List all command sessions (running and finished).",
            "properties": {},
            "required": [],
        },
        handler=as_json(lambda: sessions.list_sessions()),
        toolset="coding",
        parallel_safe=True,
    )

    # -- LSP tools --------------------------------------------------------

    registry.register(
        name="lsp_status",
        schema={"description": "Check which LSP servers are available.", "properties": {}, "required": []},
        handler=as_json(lambda: lsp_status()),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="lsp_diagnostics",
        schema={
            "description": "Get LSP diagnostics for a file (falls back if no LSP).",
            "properties": {
                "path": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["path"],
        },
        handler=as_json(
            lambda path, language="python": lsp_diagnostics(
                str(workspace.root), path, language=language,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="lsp_symbols",
        schema={
            "description": "Get document symbols via LSP.",
            "properties": {
                "path": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["path"],
        },
        handler=as_json(
            lambda path, language="python": lsp_symbols(
                str(workspace.root), path, language=language,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="lsp_definition",
        schema={
            "description": "Go to definition via LSP.",
            "properties": {
                "path": {"type": "string"},
                "line": {"type": "integer"},
                "column": {"type": "integer"},
                "language": {"type": "string"},
            },
            "required": ["path", "line", "column"],
        },
        handler=as_json(
            lambda path, line, column, language="python": lsp_definition(
                str(workspace.root), path, line, column, language=language,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="lsp_references",
        schema={
            "description": "Find references via LSP.",
            "properties": {
                "path": {"type": "string"},
                "line": {"type": "integer"},
                "column": {"type": "integer"},
                "language": {"type": "string"},
            },
            "required": ["path", "line", "column"],
        },
        handler=as_json(
            lambda path, line, column, language="python": lsp_references(
                str(workspace.root), path, line, column, language=language,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="lsp_hover",
        schema={
            "description": "Get hover info via LSP.",
            "properties": {
                "path": {"type": "string"},
                "line": {"type": "integer"},
                "column": {"type": "integer"},
                "language": {"type": "string"},
            },
            "required": ["path", "line", "column"],
        },
        handler=as_json(
            lambda path, line, column, language="python": lsp_hover(
                str(workspace.root), path, line, column, language=language,
            )
        ),
        toolset="coding",
    )

    # -- MCP tools --------------------------------------------------------

    registry.register(
        name="mcp_status",
        schema={"description": "Show MCP server connection status.", "properties": {}, "required": []},
        handler=as_json(lambda: mcp.status()),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="mcp_connect",
        schema={
            "description": "Start all declared MCP servers from .hermes/mcp.json.",
            "properties": {},
            "required": [],
        },
        handler=as_json(lambda: mcp.connect_all()),
        toolset="coding",
    )
    registry.register(
        name="mcp_list_tools",
        schema={
            "description": "List tools from all connected MCP servers.",
            "properties": {},
            "required": [],
        },
        handler=as_json(lambda: mcp.list_all_tools()),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="mcp_call_tool",
        schema={
            "description": "Call a tool on a connected MCP server.",
            "properties": {
                "server": {"type": "string"},
                "tool": {"type": "string"},
                "arguments": {"type": "object"},
            },
            "required": ["server", "tool"],
        },
        handler=as_json(
            lambda server, tool, arguments=None: mcp.call_tool(
                server, tool, arguments or {},
            )
        ),
        toolset="coding",
    )

    # -- worktree / subagent tools ----------------------------------------

    registry.register(
        name="subagent_execute",
        schema={
            "description": "Execute a subagent plan with explicit commands in an isolated worktree.",
            "properties": {
                "task": {"type": "string"},
                "planner_commands": {"type": "array", "items": {"type": "string"}},
                "builder_commands": {"type": "array", "items": {"type": "string"}},
                "reviewer_commands": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task"],
        },
        handler=as_json(
            lambda task, planner_commands=None, builder_commands=None, reviewer_commands=None: (
                subagent_execute_with_commands(
                    task, workspace, policy,
                    planner_commands=planner_commands,
                    builder_commands=builder_commands,
                    reviewer_commands=reviewer_commands,
                )
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="worktree_status_tool",
        schema={
            "description": "Inspect git worktree status (alias).",
            "properties": {},
            "required": [],
        },
        handler=as_json(lambda: git.worktree_status()),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="subagent_dispatch",
        schema={
            "description": "Dispatch a task to a sub-agent in an isolated worktree. Role: planner (inspect + plan), builder (implement), or reviewer (review diff).",
            "properties": {
                "role": {"type": "string", "description": "Sub-agent role: planner, builder, or reviewer."},
                "task": {"type": "string", "description": "Task description for the sub-agent."},
            },
            "required": ["role", "task"],
        },
        handler=as_json(
            lambda role, task: _dispatch_sync(role, task, workspace, policy, wt_exec)
        ),
        toolset="coding",
    )

    # -- test runner tools ------------------------------------------------

    registry.register(
        name="discover_tests",
        schema={
            "description": "Find test files in the workspace (tests/ or test/ directories).",
            "properties": {},
            "required": [],
        },
        handler=as_json(lambda: {"ok": True, "test_files": discover_tests(workspace)}),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="run_tests",
        schema={
            "description": "Run tests using .venv python if available. Returns structured pass/fail/error details with file:line locations for failures.",
            "properties": {
                "path": {"type": "string", "description": "Optional sub-path or test file to restrict execution."},
                "extra_args": {"type": "array", "items": {"type": "string"}, "description": "Extra pytest arguments, e.g. ['-x', '--tb=long']."},
            },
            "required": [],
        },
        handler=as_json(
            lambda path="", extra_args=None: run_tests(
                workspace, path=path, extra_args=extra_args,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="debug_error",
        schema={
            "description": "Parse a traceback and return source context around each error frame.",
            "properties": {
                "traceback_text": {"type": "string", "description": "Raw traceback string."},
                "context_lines": {"type": "integer", "description": "Lines of context around each frame (default 5)."},
            },
            "required": ["traceback_text"],
        },
        handler=as_json(lambda traceback_text, context_lines=5: debug_error(
            workspace, traceback_text, context_lines=context_lines,
        )),
        toolset="coding",
    )

    # -- context injection tools -------------------------------------------

    registry.register(
        name="read_rules",
        schema={
            "description": "Read project rules from .hermes/rules.md (or CLAUDE.md/AGENTS.md as fallback).",
            "properties": {},
            "required": [],
        },
        handler=as_json(lambda: discover_rules(workspace.root)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="workspace_context",
        schema={
            "description": "Get current workspace context: git branch, last commit, modified/staged file counts.",
            "properties": {},
            "required": [],
        },
        handler=as_json(lambda: workspace_snapshot(workspace.root)),
        toolset="coding",
        parallel_safe=True,
    )

    # -- web tools ---------------------------------------------------------

    registry.register(
        name="web_search",
        schema={
            "description": "Search the web via DuckDuckGo. No API key required.",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "limit": {"type": "integer", "description": "Maximum results (default 10)."},
            },
            "required": ["query"],
        },
        handler=as_json(lambda query, limit=10: web_search(query, limit=limit)),
        toolset="coding",
    )
    registry.register(
        name="web_fetch",
        schema={
            "description": "Fetch a URL and return its text content (HTML tags stripped).",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch."},
                "max_chars": {"type": "integer", "description": "Truncate output (default 8000)."},
            },
            "required": ["url"],
        },
        handler=as_json(lambda url, max_chars=8000: web_fetch(url, max_chars=max_chars)),
        toolset="coding",
    )
    registry.register(
        name="semantic_search",
        schema={
            "description": "Semantically search workspace code files for a natural-language query.",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query."},
                "top_k": {"type": "integer", "description": "Maximum results (default 10)."},
            },
            "required": ["query"],
        },
        handler=as_json(lambda query, top_k=10: semantic_search(
            str(workspace.root), query, top_k=top_k,
        )),
        toolset="coding",
    )

    # -- code review tools --------------------------------------------------

    registry.register(
        name="code_review",
        schema={
            "description": "Run automated code review on a diff — checks security, correctness, and style.",
            "properties": {
                "diff_text": {"type": "string", "description": "Unified diff text (git diff output)."},
            },
            "required": ["diff_text"],
        },
        handler=as_json(lambda diff_text: run_code_review(diff_text, workspace)),
        toolset="coding",
        parallel_safe=True,
    )

    # -- todo tracking tools ------------------------------------------------

    registry.register(
        name="todo_create",
        schema={
            "description": "Create a new todo item in the workspace.",
            "properties": {
                "subject": {"type": "string", "description": "Short task title."},
                "description": {"type": "string", "description": "Optional details."},
                "priority": {"type": "string", "description": "low/medium/high (default medium)."},
            },
            "required": ["subject"],
        },
        handler=as_json(
            lambda subject, description="", priority="medium": todo_create(
                str(workspace.root), subject, description, priority=priority,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="todo_update",
        schema={
            "description": "Update or resolve a todo item by ID.",
            "properties": {
                "todo_id": {"type": "string", "description": "Todo item ID."},
                "status": {"type": "string", "description": "New status: pending/in_progress/completed/blocked."},
                "subject": {"type": "string", "description": "Updated subject."},
                "description": {"type": "string", "description": "Updated description."},
                "priority": {"type": "string", "description": "Updated priority."},
            },
            "required": ["todo_id"],
        },
        handler=as_json(
            lambda todo_id, status="", subject="", description="", priority="": todo_update(
                str(workspace.root), todo_id, status=status, subject=subject,
                description=description, priority=priority,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="todo_list",
        schema={
            "description": "List workspace todo items, optionally filtered.",
            "properties": {
                "status": {"type": "string", "description": "Filter by status."},
                "priority": {"type": "string", "description": "Filter by priority."},
            },
            "required": [],
        },
        handler=as_json(
            lambda status="", priority="": _todo_list(
                str(workspace.root), status=status, priority=priority,
            )
        ),
        toolset="coding",
        parallel_safe=True,
    )

    # -- edit preview tool -------------------------------------------------

    registry.register(
        name="edit_file",
        schema={
            "description": "Validate a text patch (dry_run) and apply it when safe. Returns diff preview.",
            "properties": {
                "path": {"type": "string", "description": "File to edit."},
                "old_text": {"type": "string", "description": "Exact text to replace."},
                "new_text": {"type": "string", "description": "Replacement text."},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)."},
                "preview_only": {"type": "boolean", "description": "Only show preview without applying (default false)."},
            },
            "required": ["path", "old_text", "new_text"],
        },
        handler=as_json(
            lambda path, old_text, new_text, replace_all=False, preview_only=False: _edit_file(
                workspace, path, old_text, new_text, replace_all=replace_all, preview_only=preview_only,
            )
        ),
        toolset="coding",
    )

    # -- plan management tools ---------------------------------------------

    registry.register(
        name="plan_create",
        schema={
            "description": "Create a coding plan (persisted to .hermes/plans/).",
            "properties": {
                "task": {"type": "string", "description": "Task description."},
            },
            "required": ["task"],
        },
        handler=as_json(
            lambda task: save_plan(
                create_subagent_plan(task), str(workspace.root),
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="plan_approve",
        schema={
            "description": "Approve and execute a persisted plan in an isolated worktree.",
            "properties": {
                "plan_id": {"type": "string", "description": "Plan ID to approve and execute."},
            },
            "required": ["plan_id"],
        },
        handler=as_json(
            lambda plan_id: approve_plan(plan_id, workspace, policy)
        ),
        toolset="coding",
    )
    registry.register(
        name="plan_list",
        schema={
            "description": "List all persisted plans.",
            "properties": {},
            "required": [],
        },
        handler=as_json(lambda: list_plans(str(workspace.root))),
        toolset="coding",
        parallel_safe=True,
    )

    # -- scaffold tools -----------------------------------------------------

    registry.register(
        name="scaffold_project",
        schema={
            "description": "Generate a standard project structure from a built-in template.",
            "properties": {
                "template": {
                    "type": "string",
                    "description": "Template name: python-app, python-lib, or node-app.",
                },
                "project_name": {"type": "string", "description": "Optional custom project name."},
            },
            "required": ["template"],
        },
        handler=as_json(lambda template, project_name="": scaffold_project(
            str(workspace.root), template, project_name=project_name,
        )),
        toolset="coding",
    )
    registry.register(
        name="scaffold_list_templates",
        schema={
            "description": "List available scaffold templates.",
            "properties": {},
            "required": [],
        },
        handler=as_json(scaffold_list_templates),
        toolset="coding",
        parallel_safe=True,
    )

    # -- notebook tools ----------------------------------------------------

    registry.register(
        name="notebook_read_cell",
        schema={
            "description": "Read a single cell from a .ipynb notebook by index (0-based).",
            "properties": {
                "path": {"type": "string", "description": "Notebook file path."},
                "cell_index": {"type": "integer", "description": "Cell index."},
            },
            "required": ["path", "cell_index"],
        },
        handler=as_json(lambda path, cell_index: notebook_read_cell(path, cell_index)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="notebook_read_all_cells",
        schema={
            "description": "Read all cells from a .ipynb notebook.",
            "properties": {
                "path": {"type": "string", "description": "Notebook file path."},
            },
            "required": ["path"],
        },
        handler=as_json(lambda path: notebook_read_all_cells(path)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="notebook_edit_cell",
        schema={
            "description": "Replace the source of a notebook cell.",
            "properties": {
                "path": {"type": "string"},
                "cell_index": {"type": "integer"},
                "source": {"type": "string"},
                "cell_type": {"type": "string", "description": "code or markdown."},
            },
            "required": ["path", "cell_index", "source"],
        },
        handler=as_json(
            lambda path, cell_index, source, cell_type="code": notebook_edit_cell(
                path, cell_index, source, cell_type=cell_type,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="notebook_insert_cell",
        schema={
            "description": "Insert a new cell into a notebook at the given index.",
            "properties": {
                "path": {"type": "string"},
                "cell_index": {"type": "integer"},
                "source": {"type": "string"},
                "cell_type": {"type": "string"},
            },
            "required": ["path", "cell_index", "source"],
        },
        handler=as_json(
            lambda path, cell_index, source, cell_type="code": notebook_insert_cell(
                path, cell_index, source, cell_type=cell_type,
            )
        ),
        toolset="coding",
    )
    registry.register(
        name="notebook_delete_cell",
        schema={
            "description": "Delete a cell from a notebook by index.",
            "properties": {
                "path": {"type": "string"},
                "cell_index": {"type": "integer"},
            },
            "required": ["path", "cell_index"],
        },
        handler=as_json(lambda path, cell_index: notebook_delete_cell(path, cell_index)),
        toolset="coding",
    )

    # -- multimodal tools --------------------------------------------------

    registry.register(
        name="read_image",
        schema={
            "description": "Read an image/PDF file and return a base64 data-URI for vision models.",
            "properties": {
                "path": {"type": "string", "description": "Image or PDF file path."},
            },
            "required": ["path"],
        },
        handler=as_json(lambda path: read_image(path)),
        toolset="coding",
        parallel_safe=True,
    )

    # -- hook execution tools ----------------------------------------------

    registry.register(
        name="run_hooks",
        schema={
            "description": "Execute enabled hooks for an event (pre_tool, post_tool, pre_command, post_edit).",
            "properties": {
                "event": {"type": "string", "description": "Hook event name."},
            },
            "required": ["event"],
        },
        handler=as_json(lambda event: run_hooks(workspace, event)),
        toolset="coding",
    )
    registry.register(
        name="watch_status",
        schema={
            "description": "Check which files match watch globs (one-shot, no polling).",
            "properties": {
                "globs": {"type": "array", "items": {"type": "string"}, "description": "Glob patterns to watch."},
            },
            "required": ["globs"],
        },
        handler=as_json(lambda globs: watch_status(str(workspace.root), globs)),
        toolset="coding",
        parallel_safe=True,
    )
    registry.register(
        name="security_audit",
        schema={
            "description": "Run dependency security audit (pip-audit / npm audit).",
            "properties": {},
            "required": [],
        },
        handler=as_json(lambda: security_audit(str(workspace.root))),
        toolset="coding",
    )
    registry.register(
        name="render_diagram",
        schema={
            "description": "Render a Mermaid.js diagram and save to file (or return as ASCII).",
            "properties": {
                "mermaid_source": {"type": "string", "description": "Mermaid diagram source."},
                "output_path": {"type": "string", "description": "Optional output file path (.svg or .png)."},
            },
            "required": ["mermaid_source"],
        },
        handler=as_json(lambda mermaid_source, output_path="": _render_diagram(
            mermaid_source, output_path=output_path,
        )),
        toolset="coding",
    )

    # -- find_files (glob-based file search) -------------------------------

    registry.register(
        name="find_files",
        schema={
            "description": "Find workspace files matching a glob pattern (e.g. '*.py', 'src/**/*.ts').",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match file paths."},
                "limit": {"type": "integer", "description": "Maximum files to return (default 100)."},
            },
            "required": ["pattern"],
        },
        handler=as_json(lambda pattern, limit=100: list_files(workspace, pattern=pattern, limit=limit)),
        toolset="coding",
        parallel_safe=True,
    )

    # -- apply_edit (fuzzy search-and-replace) ----------------------------

    registry.register(
        name="apply_edit",
        schema={
            "description": "Replace text in a file with fuzzy matching (trailing-ws and indent tolerant).",
            "properties": {
                "path": {"type": "string", "description": "Target file path."},
                "old_text": {"type": "string", "description": "Text to find and replace."},
                "new_text": {"type": "string", "description": "Replacement text."},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)."},
                "fuzzy": {"type": "boolean", "description": "Use fuzzy matching (default true)."},
            },
            "required": ["path", "old_text", "new_text"],
        },
        handler=as_json(
            lambda path, old_text, new_text, replace_all=False, fuzzy=True: _apply_patch_with_confirm(
                workspace, policy, path, old_text, new_text, replace_all=replace_all, fuzzy=fuzzy,
            )
        ),
        toolset="coding",
    )

    # -- edit_batch (multi-file atomic) -----------------------------------

    def _edit_batch_with_confirm(ops: list[dict[str, Any]]) -> dict[str, object]:
        """Atomic batch edit with permission check and confirmation."""
        # Check permissions for all files
        for op in ops:
            path = str(op.get("path", ""))
            if not path:
                continue
            check = workspace.resolve(path, operation="write")
            decision = policy.decide_write(check)
            if decision.denied:
                return {"ok": False, "error": "permission_denied", "path": path, "reason": decision.reason}
        # For interactive mode, show preview
        if policy.interactive and policy.confirm is not None:
            preview_lines = [f"Batch edit — {len(ops)} file(s):"]
            for op in ops:
                preview_lines.append(f"  {op.get('path', '?')}: -{str(op.get('old_text', ''))[:80]}  +{str(op.get('new_text', ''))[:80]}")
            decision = PermissionDecision(
                action="ask", path="<batch>", operation="write",
                reason="batch_edit_confirm", edit_preview="\n".join(preview_lines),
            )
            if not policy.confirm(decision):
                return {"ok": False, "error": "edit_rejected", "message": "Batch edit was not confirmed."}
        return edit_batch(workspace, ops)

    registry.register(
        name="edit_batch",
        schema={
            "description": "Atomically edit multiple files. All edits are validated before any file is written.",
            "properties": {
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path."},
                            "old_text": {"type": "string", "description": "Text to find."},
                            "new_text": {"type": "string", "description": "Replacement text."},
                            "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)."},
                            "fuzzy": {"type": "boolean", "description": "Use fuzzy matching (default true)."},
                        },
                        "required": ["path", "old_text", "new_text"],
                    },
                    "description": "List of edit operations.",
                },
            },
            "required": ["edits"],
        },
        handler=as_json(lambda edits: _edit_batch_with_confirm(edits)),
        toolset="coding",
    )

    # -- skill_view -------------------------------------------------------

    if skill_manager is not None:
        def _skill_view(name: str) -> dict[str, object]:
            content = skill_manager.load(name)
            if content is None:
                return {"ok": False, "error": "skill_not_found", "name": name}
            return {"ok": True, "name": name, "content": content}

        def _skill_manage(action: str, name: str, *, content: str = "",
                          old_string: str = "", new_string: str = "") -> dict[str, object]:
            if action == "create":
                try:
                    result = skill_manager.create(name, content)
                    return {"ok": True, "action": "create", "name": result}
                except ValueError as exc:
                    return {"ok": False, "error": "invalid_frontmatter", "message": str(exc)}
            elif action == "patch":
                ok = skill_manager.patch(name, old_string, new_string)
                return {"ok": ok, "action": "patch", "name": name}
            elif action == "delete":
                ok = skill_manager.delete(name)
                return {"ok": ok, "action": "delete", "name": name}
            else:
                return {"ok": False, "error": "invalid_action",
                        "message": f"Unknown action '{action}'. Use create, patch, or delete."}

        registry.register(
            name="skill_view",
            schema={
                "description": "Load and read the full content of a skill by name.",
                "properties": {
                    "name": {"type": "string", "description": "Skill directory name."},
                },
                "required": ["name"],
            },
            handler=as_json(_skill_view),
            toolset="coding",
            parallel_safe=True,
        )
        registry.register(
            name="skill_manage",
            schema={
                "description": "Create, patch, or delete a skill. Action 'create' requires 'content' (full SKILL.md with YAML frontmatter). Action 'patch' requires 'old_string' and 'new_string'. Action 'delete' just needs 'name'.",
                "properties": {
                    "action": {"type": "string", "description": "One of: create, patch, delete."},
                    "name": {"type": "string", "description": "Skill directory name."},
                    "content": {"type": "string", "description": "Full SKILL.md text with YAML frontmatter (required for create)."},
                    "old_string": {"type": "string", "description": "Exact text to find and replace (required for patch)."},
                    "new_string": {"type": "string", "description": "Replacement text (required for patch)."},
                },
                "required": ["action", "name"],
            },
            handler=as_json(_skill_manage),
            toolset="coding",
        )
