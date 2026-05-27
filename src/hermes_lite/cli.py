"""Interactive REPL for Hermes Lite.

Usage::

    .venv/bin/python -m hermes_lite.cli
    # or via console_scripts entry point:
    hermes-lite
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from hermes_lite.agent import HermesAgent
from hermes_lite.memory.manager import MemoryManager
from hermes_lite.providers.adapters import ProviderConfig
from hermes_lite.skills.manager import SkillManager
from hermes_lite.tools.builtin import register_builtin_tools
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

        case "clear":
            os.system("clear" if os.name != "nt" else "cls")
            return True

        case _:
            print(f"Unknown command: /{cmd}. Type /help for available commands.")
            return True


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def run_repl(agent: HermesAgent, memory: MemoryManager, skills: SkillManager) -> None:
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
            )
            if not should_continue:
                return
            continue

        # Send to agent
        print()  # blank line before response
        try:
            response = await agent.run(user_input)
            print(response)
        except Exception as exc:
            print(f"[ERROR] {exc}")
        print()  # blank line after response


def main() -> None:
    """CLI entry point — sets up the agent and starts the REPL."""
    # 1. Load environment
    _load_env()

    # 2. Check for API key
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("Warning: DEEPSEEK_API_KEY not set in environment or .env file.")
        print("Set it with:  export DEEPSEEK_API_KEY=sk-...")
        sys.exit(1)

    # 3. Create provider config and agent building blocks
    config = ProviderConfig(
        provider="deepseek",
        model="deepseek-chat",
    )

    tools = ToolRegistry()
    register_builtin_tools(tools)

    skills = SkillManager(base_dir="skills/")
    memory = MemoryManager()

    # 4. Create the agent
    agent = HermesAgent(
        config=config,
        persona=(
            "You are Hermes Agent, an intelligent AI assistant created by "
            "Nous Research. You are helpful, knowledgeable, and direct. You "
            "assist users with a wide range of tasks including answering "
            "questions, writing and editing code, analyzing information, "
            "creative work, and executing actions via your tools. You "
            "communicate clearly, admit uncertainty when appropriate, and "
            "prioritize being genuinely useful over being verbose."
        ),
        tool_registry=tools,
        memory_manager=memory,
    )

    # 5. Run the REPL
    try:
        asyncio.run(run_repl(agent, memory, skills))
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
