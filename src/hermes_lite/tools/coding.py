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
from hermes_lite.coding.extensibility import hook_status, load_external_tools, load_mcp_servers, run_hooks
from hermes_lite.coding.multimodal import read_image, read_image_supported
from hermes_lite.coding.notebook import (
    notebook_delete_cell,
    notebook_edit_cell,
    notebook_insert_cell,
    notebook_read_all_cells,
    notebook_read_cell,
)
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
    apply_text_patch,
    apply_unified_diff,
    diff_summary,
    patch_dry_run,
)
from hermes_lite.coding.permissions import PermissionPolicy
from hermes_lite.coding.sessions import SessionManager
from hermes_lite.coding.shell import CommandRunner
from hermes_lite.coding.subagents import (
    approve_plan,
    create_subagent_plan,
    execute_subagent_plan,
    list_plans,
    run_code_review,
    save_plan,
    subagent_execute_with_commands,
)
from hermes_lite.coding.context_inject import discover_rules, workspace_snapshot
from hermes_lite.coding.testing import discover_tests, extract_failure_locations, run_tests
from hermes_lite.coding.todo import todo_create, todo_list as _todo_list, todo_update
from hermes_lite.coding.web import web_fetch, web_search
from hermes_lite.coding.worktree_exec import WorktreeExecutor
from hermes_lite.coding.workspace import Workspace
from hermes_lite.tools.registry import ToolRegistry


def register_coding_tools(
    registry: ToolRegistry,
    workspace: Workspace,
    permission_policy: PermissionPolicy | None = None,
    *,
    session_manager: SessionManager | None = None,
    mcp_manager: McpClientManager | None = None,
    worktree_executor: WorktreeExecutor | None = None,
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
        # Validate path
        check = workspace.resolve(path, operation="write")
        decision = policy.decide_write(check)
        if not decision.allowed:
            result = decision.to_dict()
            result.update({"ok": False, "error": "permission_denied", "reason": decision.reason})
            return result

        # Read current content for diff preview
        current = workspace.read_text(path)
        old_content = current.get("content", "") if current.get("ok") else ""

        # Dry run to validate
        dry = apply_text_patch(workspace, path, old_text, new_text, replace_all=replace_all, dry_run=True)
        if not dry.get("ok"):
            return dry

        if preview_only:
            # Generate preview diff
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

        # Apply the change
        result = apply_text_patch(workspace, path, old_text, new_text, replace_all=replace_all)
        # Get diff for the applied change
        new_content = workspace.read_text(path).get("content", "")
        preview = diff_summary(workspace, path, old_content) if old_content else {"diff_preview": ""}
        result["diff_preview"] = preview.get("diff_preview", "")
        result["preview_only"] = False
        return result

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

    def read_file(path: str, offset: int = 1, limit: int = 500) -> dict[str, object]:
        check = workspace.resolve(path, operation="read")
        decision = policy.decide_read(check)
        if not decision.allowed:
            result = decision.to_dict()
            result.update({"ok": False, "error": "permission_denied", "reason": decision.reason})
            return result
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
        if not decision.allowed:
            result = decision.to_dict()
            result.update({"ok": False, "error": "permission_denied", "reason": decision.reason})
            return result
        return workspace.write_text(path, content)

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
            "description": "Read a workspace file with line-number metadata.",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
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
            lambda path, old_text, new_text, replace_all=False: apply_text_patch(
                workspace,
                path,
                old_text,
                new_text,
                replace_all=replace_all,
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
            lambda path, diff_text, dry_run=False, fuzzy=0: apply_unified_diff(
                workspace, path, diff_text, dry_run=dry_run, fuzzy=fuzzy,
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
