"""Interactive REPL for Hermes Lite.

Usage::

    .venv/bin/python -m hermes_lite.cli
    # or via console_scripts entry point:
    hermes-lite
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from hermes_lite.agent import HermesAgent
from hermes_lite.coding.audit import AuditLogger
from hermes_lite.coding.context import build_project_map
from hermes_lite.coding.git import GitClient
from hermes_lite.coding.mcp_client import McpClientManager
from hermes_lite.coding.permissions import PermissionDecision, PermissionPolicy
from hermes_lite.coding.sessions import SessionManager
from hermes_lite.coding.worktree_exec import WorktreeExecutor
from hermes_lite.coding.workspace import Workspace
from hermes_lite.memory.manager import MemoryManager
from hermes_lite.prompts.coding_agent import build_coding_prompt
from hermes_lite.providers.adapters import ProviderConfig
from hermes_lite.skills.manager import SkillManager
from hermes_lite.tools.builtin import register_builtin_tools
from hermes_lite.tools.coding import register_coding_tools
from hermes_lite.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# prompt_toolkit (optional) — graceful fallback to built-in input()
# ---------------------------------------------------------------------------
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style

    _HAS_PROMPT_TOOLKIT = True
except ImportError:  # pragma: no cover
    _HAS_PROMPT_TOOLKIT = False

# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

BANNER = r"""
  _    _
 | |  | |                      
 | |__| | ___ _ __ _ __ ___  ___     | |   (_) |_ ___
 |  __  |/ _ \ '__| '_ ` _ \/ __|    | |   | | __/ _ \
 | |  | |  __/ |  | | | | | \__ \    | |___| | ||  __/
 |_|  |_|\___|_|  |_| |_| |_|___/    |_____|_|\__\___|

 Type /help for commands, /quit to exit.
"""

DEFAULT_PERSONA = (
    "You are Hermes Agent, an intelligent AI assistant created by "
    "Nous Research. You are helpful, knowledgeable, and direct. You "
    "assist users with a wide range of tasks including answering "
    "questions, writing and editing code, analyzing information, "
    "creative work, and executing actions via your tools. You "
    "communicate clearly, admit uncertainty when appropriate, and "
    "prioritize being genuinely useful over being verbose."
)


@dataclass
class WorkspaceRuntime:
    """Runtime objects for workspace-aware coding mode."""

    workspace: Workspace
    permission_policy: PermissionPolicy
    session_manager: SessionManager
    audit_logger: AuditLogger


def _load_env() -> None:
    """Load .env from project root or current directory."""
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


def _get_prompt_toolkit_style() -> Style:
    """Return a minimal style for prompt_toolkit."""
    return Style.from_dict(
        {
            "prompt": "bold #00aa00",
            "separator": "#888888",
        }
    )


def _get_history_path() -> Path:
    """Path to the REPL history file, XDG-compliant."""
    xdg_state = os.getenv("XDG_STATE_HOME")
    if xdg_state:
        base = Path(xdg_state)
    else:
        base = Path.home() / ".local" / "state"
    return base / "hermes-lite" / "history"


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Hermes Lite — interactive AI assistant REPL",
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("HERMES_PROVIDER", "deepseek"),
        help="LLM provider (default: deepseek, or $HERMES_PROVIDER)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("HERMES_MODEL", "deepseek-chat"),
        help="Model name (default: deepseek-chat, or $HERMES_MODEL)",
    )
    parser.add_argument(
        "--workspace",
        default=os.getenv("HERMES_WORKSPACE", ""),
        help="Enable coding-agent mode for this workspace path.",
    )
    return parser


def create_workspace_runtime(
    workspace_path: str,
    tools: ToolRegistry,
    permission_policy: PermissionPolicy | None = None,
    *,
    confirm: "Callable[[PermissionDecision], bool] | None" = None,
) -> WorkspaceRuntime | None:
    """Create workspace runtime and register coding tools when configured."""
    if not workspace_path:
        return None
    workspace = Workspace(workspace_path)
    audit = AuditLogger()
    policy = permission_policy or PermissionPolicy(interactive=True, confirm=confirm, audit=audit)
    sessions = SessionManager(workspace, policy, audit=audit)
    mcp = McpClientManager(workspace)
    wt_exec = WorktreeExecutor(workspace, policy, audit=audit)
    register_coding_tools(
        tools, workspace, policy,
        session_manager=sessions,
        mcp_manager=mcp,
        worktree_executor=wt_exec,
    )
    return WorkspaceRuntime(
        workspace=workspace,
        permission_policy=policy,
        session_manager=sessions,
        audit_logger=audit,
    )


def build_persona(
    base_persona: str = DEFAULT_PERSONA,
    *,
    workspace: Workspace | None = None,
    permission_policy: PermissionPolicy | None = None,
    inject_context: bool = True,
) -> str:
    """Compose the base persona with coding-agent instructions when needed.

    When *workspace* is set and *inject_context* is ``True``, the function
    prepends project rules (``.hermes/rules.md``) and a workspace snapshot
    before the coding prompt.
    """
    if workspace is None:
        return base_persona
    policy = permission_policy or PermissionPolicy()

    parts = [base_persona]

    if inject_context:
        from hermes_lite.coding.context_inject import build_context_preamble
        preamble = build_context_preamble(workspace.root)
        if preamble:
            parts.append(preamble)

    parts.append(build_coding_prompt(workspace, policy))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def _handle_dot_command(
    cmd: str,
    args: str,
    *,
    agent: HermesAgent,
    memory: MemoryManager,
    skills: SkillManager,
    workspace_runtime: WorkspaceRuntime | None = None,
) -> bool:
    """Handle a slash-command.  Returns ``True`` if the REPL should continue,
    ``False`` if it should exit."""
    match cmd:
        case "quit" | "exit" | "q":
            print("Goodbye!")
            return False

        case "help" | "h" | "?":
            print("Commands:")
            print("  /quit, /exit     Exit the REPL")
            print("  /help            Show this help")
            print("  /memory          Show current memories")
            print("  /skills          List loaded skills")
            print("  /clear           Clear the screen")
            print("  /tools           List registered tools")
            print("  /model           Show current model/provider info")
            if workspace_runtime is not None:
                print("  /status          Show workspace and git status")
                print("  /diff            Show current git diff")
                print("  /permissions     Show active permission policy")
                print("  /approve <rule>  Approve a pending permission category")
                print("  /deny <rule>     Deny a pending permission category")
                print("  /audit           Show audit log summary")
                print("  /sessions        List background command sessions")
                print("  /recent [n]      Show recently changed files")
                print("  /test [path]     Run tests with .venv python, structured results")
                print("  /testfor <path>  Find test files for a source file")
                print("  /repomap         Token-aware repository overview")
                print("  /projectmap      Show project structure summary")
                print("  /lsp             Show LSP server availability")
                print("  /mcp             Show MCP server connection status")
                print("  /worktree        Show git worktree info")
                print("  /plan <task>     Generate a subagent plan")
                print("  /context         Show workspace context (branch, rules, changes)")
                print("  /todo [text]     Add a todo item")
                print("  /run             Resume agent execution stub")
                print("  /resume <id>     Resume a command session")
            print("  Any other text is sent to the agent.")
            return True

        case "memory":
            entries = memory.list_all()
            if not entries:
                print("(no memories stored)")
            else:
                for e in entries:
                    print(f"  [{e.target}] {e.content}")
            return True

        case "skills":
            skill_list = skills.list_all()
            if not skill_list:
                print("(no skills loaded)")
            else:
                for s in skill_list:
                    print(f"  {s['name']} (v{s.get('version', '?')}) — {s.get('description', '')}")
            return True

        case "tools":
            tool_list = agent.tool_registry.list_tools()
            if not tool_list:
                print("(no tools registered)")
            else:
                for t in tool_list:
                    print(f"  {t['name']} [{t['toolset']}]")
            return True

        case "model":
            cfg = agent.config
            print(f"  Provider: {cfg.provider}")
            print(f"  Model:    {cfg.model}")
            print(f"  Base URL: {cfg.base_url or '(default)'}")
            return True

        case "status":
            if workspace_runtime is None:
                print("No workspace configured. Start with --workspace PATH.")
                return True
            git_status = GitClient(workspace_runtime.workspace).status()
            print(f"  Workspace: {workspace_runtime.workspace.root}")
            print(f"  Provider:  {agent.config.provider}")
            print(f"  Model:     {agent.config.model}")
            if git_status.get("ok"):
                print(f"  Git branch: {git_status.get('branch') or '(detached)'}")
                print(f"  Git clean:  {git_status.get('clean')}")
            else:
                print(f"  Git:       {git_status.get('error')}")
            return True

        case "diff":
            if workspace_runtime is None:
                print("No workspace configured. Start with --workspace PATH.")
                return True
            diff = GitClient(workspace_runtime.workspace).diff(stat=False)
            if diff.get("ok"):
                print(diff.get("diff") or "(no diff)")
            else:
                print(f"Unable to read diff: {diff.get('error')}")
            return True

        case "permissions":
            if workspace_runtime is None:
                print("No workspace configured. Start with --workspace PATH.")
                return True
            print(json.dumps(workspace_runtime.permission_policy.summary(), indent=2))
            return True

        case "projectmap":
            if workspace_runtime is None:
                print("No workspace configured. Start with --workspace PATH.")
                return True
            print(json.dumps(build_project_map(workspace_runtime.workspace), indent=2))
            return True

        case "approve":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            category = args.strip()
            valid_categories = {"network", "risky_git", "shell_control", "package_install"}
            if category not in valid_categories:
                print(f"Usage: /approve <category> — one of: {', '.join(sorted(valid_categories))}")
                return True
            workspace_runtime.permission_policy.authorize("category", category, scope="session")
            print(f"Category '{category}' authorized for this session.")
            return True

        case "deny":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            category = args.strip()
            if not category:
                print("Usage: /deny <category>")
                return True
            workspace_runtime.permission_policy.revoke("category", category)
            print(f"Category '{category}' authorization revoked.")
            return True

        case "sessions":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            result = workspace_runtime.session_manager.list_sessions()
            if not result["sessions"]:
                print("(no active sessions)")
            else:
                for s in result["sessions"]:
                    status = "RUNNING" if s["running"] else "STOPPED"
                    print(f"  [{s['session_id']}] {status}  {s['command']}")
            return True

        case "audit":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            summary = workspace_runtime.audit_logger.summary()
            print(f"  Audit entries: {summary['total_entries']}")
            print(f"  Allowed: {summary['allowed']}, Asked: {summary['asked']}, Denied: {summary['denied']}")
            recent = workspace_runtime.audit_logger.recent(5)
            if recent:
                print("  Recent:")
                for e in recent:
                    print(f"    [{e.decision:>5}] {e.operation}: {e.target} ({e.reason})")
            return True

        case "plan":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            task = args.strip()
            if not task:
                print("Usage: /plan <task description>")
                return True
            from hermes_lite.coding.subagents import create_subagent_plan
            plan = create_subagent_plan(task)
            print(json.dumps(plan.to_dict(), indent=2))
            return True

        case "todo":
            print("(todo tracking not yet implemented)")
            return True

        case "run":
            print("(run/resume agent not yet implemented from slash command)")
            return True

        case "resume":
            sid = args.strip()
            if not sid:
                print("Usage: /resume <session-id>")
                return True
            print(f"(resume session {sid} not yet implemented)")
            return True

        case "lsp":
            from hermes_lite.coding.lsp import discover_lsp_servers, lsp_status
            st = lsp_status()
            if st.get("available_servers"):
                for s in st["available_servers"]:
                    print(f"  {s['name']} ({', '.join(s['languages'])}) — {s['executable']}")
            else:
                print("  No LSP servers found. Install pyright/pylsp/typescript-language-server.")
            print(f"  Active sessions: {st['active_sessions']}")
            return True

        case "mcp":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            from hermes_lite.coding.mcp_client import McpClientManager
            mcp_mgr = McpClientManager(workspace_runtime.workspace)
            config = mcp_mgr.connect_all()
            if config.get("details"):
                for d in config["details"]:
                    print(f"  {d['name']}: {d['status']} ({d['command']})")
            else:
                print("  No MCP servers configured in .hermes/mcp.json")
            mcp_mgr.shutdown_all()
            return True

        case "worktree":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            wt = GitClient(workspace_runtime.workspace).worktree_status()
            print(f"  Is git repo: {wt['is_git_repo']}")
            for wt_info in wt.get("worktrees", []):
                print(f"  {wt_info.get('worktree', '?')} [{wt_info.get('branch', '?')}]")
            return True

        case "recent":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            from hermes_lite.coding.context import recent_changes
            count = int(args.strip()) if args.strip() else 10
            result = recent_changes(workspace_runtime.workspace, count=count)
            if result["ok"]:
                for f in result["files"]:
                    print(f"  {f['path']}")
                print(f"  (source: {result['source']})")
            return True

        case "testfor":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            from hermes_lite.coding.context import find_test_files
            path = args.strip()
            if not path:
                print("Usage: /testfor <source-file-path>")
                return True
            result = find_test_files(workspace_runtime.workspace, path)
            if result["ok"]:
                if result["test_files"]:
                    for tf in result["test_files"]:
                        print(f"  [{tf['score']}] {tf['path']} ({tf.get('language', '?')})")
                else:
                    print("  (no test files found)")
            return True

        case "test":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            from hermes_lite.coding.testing import run_tests, discover_tests
            extra = args.strip().split() if args.strip() else []
            path = extra[0] if extra and not extra[0].startswith("-") else ""
            extra_args = extra if not path else extra[1:]

            print(f"Running tests{' in ' + path if path else ''}...")
            result = run_tests(workspace_runtime.workspace, path=path, extra_args=extra_args if extra_args else None)

            if not result.get("ran"):
                print(f"  Error: {result.get('message', 'tests could not be run')}")
                if "python_used" in result:
                    print(f"  Python: {result['python_used']}")
                return True

            print(f"  Runner: {result.get('runner', '?')}")
            print(f"  Python: {result.get('python_used', '?')}")
            print(f"  Passed: {result.get('passed', 0)}  Failed: {result.get('failed', 0)}  Errors: {result.get('errors', 0)}")
            if result.get("skipped"):
                print(f"  Skipped: {result['skipped']}")

            failures = result.get("failures", [])
            if failures:
                print(f"\n  --- {len(failures)} failure(s) ---")
                for f in failures:
                    print(f"  [{f.get('failure_type', '?')}] {f.get('test_name', '?')}")
                    if f.get("file") and f.get("line"):
                        print(f"    {f['file']}:{f['line']}")
                    msg = f.get("message", "")
                    if msg:
                        print(f"    {msg[:200]}")
            elif result.get("ok"):
                print("  All tests passed.")
            return True

        case "context":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            from hermes_lite.coding.context_inject import build_context_preamble
            preamble = build_context_preamble(workspace_runtime.workspace.root)
            print(preamble if preamble else "(no context available)")
            return True

        case "rules":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            from hermes_lite.coding.context_inject import discover_rules
            result = discover_rules(workspace_runtime.workspace.root)
            if result["found"]:
                print(f"Rules from {result['source']}:")
                print(result["content"])
            else:
                print("No .hermes/rules.md (or CLAUDE.md/AGENTS.md) found in workspace.")
                print("Create .hermes/rules.md to provide project-level instructions.")
            return True

        case "repomap":
            if workspace_runtime is None:
                print("No workspace configured.")
                return True
            from hermes_lite.coding.context import repo_map_summary
            result = repo_map_summary(workspace_runtime.workspace)
            print(json.dumps(result, indent=2))
            return True

        case "clear":
            os.system("clear" if os.name != "nt" else "cls")
            return True

        case _:
            print(f"Unknown command: /{cmd}. Type /help for available commands.")
            return True


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def run_repl(
    agent: HermesAgent,
    memory: MemoryManager,
    skills: SkillManager,
    workspace_runtime: WorkspaceRuntime | None = None,
) -> None:
    """Run the interactive REPL loop."""
    print(BANNER)

    # Only use prompt_toolkit if stdin is a real TTY
    if _HAS_PROMPT_TOOLKIT and sys.stdin.isatty():
        history_path = _get_history_path()
        history_path.parent.mkdir(parents=True, exist_ok=True)

        session = PromptSession(
            history=FileHistory(str(history_path)),
            style=_get_prompt_toolkit_style(),
        )

        async def _read_line() -> str:
            try:
                return await session.prompt_async(
                    [("class:prompt", ">> "), ("class:separator", "")],
                )
            except EOFError:
                return "/quit"
            except KeyboardInterrupt:
                print()  # newline after ^C
                return ""

        _readline = _read_line
    else:
        # Pure input() fallback — runs in executor to avoid blocking
        def _input_blocking() -> str:
            try:
                return input(">> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return "/quit"

        async def _read_line() -> str:
            return await asyncio.get_event_loop().run_in_executor(None, _input_blocking)

        _readline = _read_line

    # Main loop
    message_history = None
    while True:
        try:
            user_input = (await _readline()).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return

        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            parts = user_input[1:].split(maxsplit=1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            should_continue = await _handle_dot_command(
                cmd,
                args,
                agent=agent,
                memory=memory,
                skills=skills,
                workspace_runtime=workspace_runtime,
            )
            if not should_continue:
                if workspace_runtime is not None:
                    workspace_runtime.session_manager.cleanup()
                return
            continue

        # Send to agent
        print()  # blank line before response
        try:
            response, message_history = await agent.run(
                user_input, message_history=message_history
            )
            print(response)
        except Exception as exc:
            print(f"[ERROR] {exc}")
        print()  # blank line after response


def main() -> None:
    """CLI entry point — sets up the agent and starts the REPL."""
    # 1. Load environment (must come before arg parse for env var defaults)
    _load_env()

    parser = build_parser()
    args = parser.parse_args()

    # 2. Check for API key
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("Warning: DEEPSEEK_API_KEY not set in environment or .env file.")
        print("Set it with:  export DEEPSEEK_API_KEY=***")
        sys.exit(1)

    # 3. Create provider config and agent building blocks
    config = ProviderConfig(
        provider=args.provider,  # type: ignore[arg-type]
        model=args.model,
    )

    tools = ToolRegistry()
    register_builtin_tools(tools)

    # build confirm callback for interactive permission prompts
    def _confirm_permission(decision: PermissionDecision) -> bool:
        print(f"\n  [PERMISSION] {decision.operation}: {decision.target}")
        print(f"  Reason: {decision.reason}")
        if decision.message:
            print(f"  {decision.message}")
        try:
            answer = input("  Approve? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        return answer in ("y", "yes")

    workspace_runtime = create_workspace_runtime(
        args.workspace, tools, confirm=_confirm_permission
    )

    skills = SkillManager(base_dir="skills/")
    memory = MemoryManager()

    # 4. Create the agent
    agent = HermesAgent(
        config=config,
        persona=build_persona(
            DEFAULT_PERSONA,
            workspace=workspace_runtime.workspace if workspace_runtime else None,
            permission_policy=(
                workspace_runtime.permission_policy if workspace_runtime else None
            ),
        ),
        tool_registry=tools,
        memory_manager=memory,
        skill_manager=skills,
    )

    # 5. Run the REPL
    try:
        asyncio.run(run_repl(agent, memory, skills, workspace_runtime=workspace_runtime))
    except KeyboardInterrupt:
        print("\nGoodbye!")
    finally:
        if workspace_runtime is not None:
            workspace_runtime.session_manager.cleanup()
    sys.exit(0)


if __name__ == "__main__":
    main()
