"""Built-in tools for Hermes Lite.

Provides real, usable tool functions for terminal, file, and web operations.
Each tool has a proper pydantic-ai compatible schema and is grouped into a
logical toolset (``terminal``, ``file``, ``web``).

Usage::

    from hermes_lite.tools.builtin import register_builtin_tools
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_builtin_tools(registry)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hermes_lite.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def run_shell(command: str) -> str:
    """Execute a shell command and return stdout.

    Args:
        command: The shell command to execute.

    Returns:
        Combined stdout and stderr output, or an error message.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds."
    except Exception as exc:
        return f"Error executing command: {exc}"


def read_file(path: str) -> str:
    """Read a file and return its content with line numbers (first 500 lines).

    Args:
        path: Path to the file to read.

    Returns:
        File content with 6-digit line numbers, or an error message.
    """
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Error: File not found: {path}"
        if p.is_dir():
            return f"Error: Path is a directory: {path}"
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        truncated = len(lines) > 500
        if truncated:
            lines = lines[:500]
        numbered = [f"{i + 1:>6}|{line}" for i, line in enumerate(lines)]
        if truncated:
            numbered.append("... (truncated — showing first 500 lines)")
        return "\n".join(numbered)
    except Exception as exc:
        return f"Error reading file: {exc}"


def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed.

    Args:
        path: Path to the file to write.
        content: Text content to write.

    Returns:
        Confirmation message or error.
    """
    try:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as exc:
        return f"Error writing file: {exc}"


def web_fetch(url: str) -> str:
    """Fetch the text content of a web page via HTTP GET.

    Args:
        url: The URL to fetch.

    Returns:
        First 5000 characters of the response text, or an error message.
    """
    try:
        import requests  # lazy import — only needed when this tool is used

        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Hermes-Lite/1.0"},
        )
        response.raise_for_status()
        text = response.text[:5000]
        if len(response.text) > 5000:
            text += "\n... (truncated to first 5000 characters)"
        return text
    except Exception as exc:
        return f"Error fetching URL: {exc}"


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def register_builtin_tools(registry: ToolRegistry) -> None:
    """Register all built-in tools on the given ``ToolRegistry``.

    Tools are grouped into toolsets:

    * ``terminal`` — ``run_shell``
    * ``file``      — ``read_file``, ``write_file``
    * ``web``       — ``web_fetch``

    Args:
        registry: The tool registry to populate.
    """
    registry.register(
        name="run_shell",
        schema={
            "description": (
                "Execute a shell command and return stdout/stderr. "
                "Timeout: 30 seconds. Use for running tests, listing "
                "directories, searching files, etc."
            ),
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
            },
            "required": ["command"],
        },
        handler=run_shell,
        toolset="terminal",
    )

    registry.register(
        name="read_file",
        schema={
            "description": (
                "Read a file and return its content with line numbers. "
                "Shows the first 500 lines."
            ),
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read.",
                },
            },
            "required": ["path"],
        },
        handler=read_file,
        toolset="file",
    )

    registry.register(
        name="write_file",
        schema={
            "description": (
                "Write text content to a file. Creates parent directories "
                "if they do not exist. Overwrites existing files."
            ),
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write.",
                },
            },
            "required": ["path", "content"],
        },
        handler=write_file,
        toolset="file",
    )

    registry.register(
        name="web_fetch",
        schema={
            "description": (
                "Fetch the text content of a web page via HTTP GET. "
                "Returns the first 5000 characters."
            ),
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                },
            },
            "required": ["url"],
        },
        handler=web_fetch,
        toolset="web",
    )
