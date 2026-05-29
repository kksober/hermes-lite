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
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from hermes_lite.agent import HermesAgent
from hermes_lite.coding.context import build_project_map
from hermes_lite.coding.git import GitClient
from hermes_lite.coding.permissions import PermissionPolicy
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
) -> WorkspaceRuntime | None:
    """Create workspace runtime and register coding tools when configured."""
    if not workspace_path:
        return None
    workspace = Workspace(workspace_path)
    policy = permission_policy or PermissionPolicy()
    register_coding_tools(tools, workspace, policy)
    return WorkspaceRuntime(workspace=workspace, permission_policy=policy)


def build_persona(
    base_persona: str = DEFAULT_PERSONA,
    *,
    workspace: Workspace | None = None,
    permission_policy: PermissionPolicy | None = None,
) -> str:
    """Compose the base persona with coding-agent instructions when needed."""
    if workspace is None:
        return base_persona
    policy = permission_policy or PermissionPolicy()
    return base_persona + "\n\n" + build_coding_prompt(workspace, policy)


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
                print("  /projectmap      Show project structure summary")
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
    workspace_runtime = create_workspace_runtime(args.workspace, tools)

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
        sys.exit(0)


if __name__ == "__main__":
    main()
