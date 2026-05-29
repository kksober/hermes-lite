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
from hermes_lite.coding.extensibility import hook_status, load_external_tools, load_mcp_servers
from hermes_lite.coding.git import GitClient
from hermes_lite.coding.patches import (
    apply_text_patch,
    apply_unified_diff,
    diff_summary,
    patch_dry_run,
)
from hermes_lite.coding.permissions import PermissionPolicy
from hermes_lite.coding.sessions import SessionManager
from hermes_lite.coding.shell import CommandRunner
from hermes_lite.coding.subagents import create_subagent_plan
from hermes_lite.coding.workspace import Workspace
from hermes_lite.tools.registry import ToolRegistry


def register_coding_tools(
    registry: ToolRegistry,
    workspace: Workspace,
    permission_policy: PermissionPolicy | None = None,
    *,
    session_manager: SessionManager | None = None,
) -> None:
    """Register workspace-aware coding tools."""
    policy = permission_policy or PermissionPolicy()
    runner = CommandRunner(workspace, policy)
    git = GitClient(workspace)
    sessions = session_manager or SessionManager(workspace, policy)

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
    )
    registry.register(
        name="external_tools",
        schema={"description": "List configured external tools.", "properties": {}, "required": []},
        handler=as_json(lambda: load_external_tools(workspace)),
        toolset="coding",
    )
    registry.register(
        name="mcp_servers",
        schema={"description": "List configured MCP servers.", "properties": {}, "required": []},
        handler=as_json(lambda: load_mcp_servers(workspace)),
        toolset="coding",
    )
    registry.register(
        name="hook_status",
        schema={"description": "List configured hooks without running them.", "properties": {}, "required": []},
        handler=as_json(lambda: hook_status(workspace)),
        toolset="coding",
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
    )
    registry.register(
        name="worktree_status",
        schema={"description": "Inspect git worktree status.", "properties": {}, "required": []},
        handler=as_json(lambda: git.worktree_status()),
        toolset="coding",
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
    )
