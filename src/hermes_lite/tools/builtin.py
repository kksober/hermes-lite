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

import ipaddress
import shlex
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from hermes_lite.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# WARNING: run_shell executes arbitrary commands.  We use ``shell=False``
# with ``shlex.split`` to avoid shell injection.  Complex shell features
# (pipes, redirects, &&/|| chaining) are deliberately NOT supported —
# use a script file and call ``/bin/sh script.sh`` if you need them.
# ---------------------------------------------------------------------------

def run_shell(command: str) -> str:
    """Execute a shell command and return stdout.

    Commands are tokenised with shlex.split and executed with shell=False
    to prevent command-injection attacks.  Pipe/redirect syntax is NOT
    supported — write a temporary script for complex pipelines.

    Args:
        command: The shell command to execute.

    Returns:
        Combined stdout and stderr output, or an error message.
    """
    try:
        # Security: never use shell=True to avoid injection attacks.
        # shlex.split handles quoting correctly without invoking a shell.
        args = shlex.split(command)
        result = subprocess.run(
            args,
            shell=False,
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


def read_file(path: str, offset: int = 1, limit: int = 500) -> str:
    """Read a text file and return paginated content with line numbers.

    Args:
        path: Path to the file to read.
        offset: Starting line number (1-indexed, default: 1).
        limit: Maximum number of lines to return (default: 500).

    Returns:
        JSON string with keys: content, total_lines, offset, limit.
    """
    import json

    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return json.dumps({
                "error": f"File not found: {path}",
                "content": "",
                "total_lines": 0,
                "offset": offset,
                "limit": limit,
            })
        if p.is_dir():
            return json.dumps({
                "error": f"Path is a directory: {path}",
                "content": "",
                "total_lines": 0,
                "offset": offset,
                "limit": limit,
            })
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        total_lines = len(lines)

        # Clamp offset to valid range
        start = max(1, min(offset, total_lines)) - 1  # 0-indexed
        end = min(start + limit, total_lines)
        page_lines = lines[start:end]

        numbered = [f"{start + i + 1:>6}|{line}" for i, line in enumerate(page_lines)]
        result = {
            "content": "\n".join(numbered),
            "total_lines": total_lines,
            "offset": start + 1,
            "limit": limit,
        }
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({
            "error": f"Error reading file: {exc}",
            "content": "",
            "total_lines": 0,
            "offset": offset,
            "limit": limit,
        })


# ---------------------------------------------------------------------------
# SECURITY: write_file restricts all writes to a workspace directory.
# Hidden files (.env, .git, etc.) are rejected to prevent sensitive-file
# tampering even within the workspace.
# ---------------------------------------------------------------------------

def write_file(path: str, content: str, workspace_dir: str = ".") -> str:
    """Write content to a file, creating parent directories as needed.

    **Security constraints:**
    * Writes are restricted to subdirectories of ``workspace_dir``.
      Absolute paths outside the workspace are rejected.
    * Hidden files (names starting with ``.``) are rejected to protect
      sensitive files like ``.env``, ``.git``, etc.
    * Symlinks that escape the workspace are rejected.

    Args:
        path: Path to the file to write (relative to workspace_dir).
        content: Text content to write.
        workspace_dir: Root directory for file writes (default ".").

    Returns:
        Confirmation message or error.
    """
    try:
        workspace = Path(workspace_dir).expanduser().resolve()
        p = Path(path)

        # Reject absolute paths outside workspace
        if p.is_absolute():
            resolved = p.expanduser().resolve()
            # Allow absolute paths only if they are inside workspace
            try:
                resolved.relative_to(workspace)
            except ValueError:
                return (
                    f"Error: Absolute path '{path}' is outside the workspace "
                    f"directory '{workspace}'. Use a relative path within the "
                    f"workspace instead."
                )
        else:
            resolved = (workspace / p).resolve()

        # Ensure resolved path is within workspace (catches '../' escape attempts)
        try:
            resolved.relative_to(workspace)
        except ValueError:
            return (
                f"Error: Path '{path}' resolves outside the workspace "
                f"directory '{workspace}'."
            )

        # Reject hidden files
        if resolved.name.startswith("."):
            return (
                f"Error: Writing to hidden files ('{resolved.name}') is "
                f"not allowed for security reasons."
            )

        # Reject symlinks that point outside workspace
        if resolved.is_symlink():
            real_path = resolved.resolve()
            try:
                real_path.relative_to(workspace)
            except ValueError:
                return (
                    f"Error: Symlink '{path}' targets a path outside the "
                    f"workspace."
                )

        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as exc:
        return f"Error writing file: {exc}"


# ---------------------------------------------------------------------------
# SSRF PROTECTION: web_fetch validates URLs before fetching.
# * Only http/https schemes are allowed (no file://, ftp://, gopher://, etc.)
# * Private/reserved IP addresses are rejected (RFC 1918, loopback, link-local).
# * Uses httpx with a timeout to prevent hanging on slow servers.
# ---------------------------------------------------------------------------

_PRIVATE_NETWORKS = [
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("169.254.0.0/16"),
]


def _is_private_ip(host: str) -> bool:
    """Check whether a hostname resolves to a private/reserved IP address."""
    import socket

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # Hostname — resolve and check all addresses
        try:
            addrs = socket.getaddrinfo(host, None, socket.AF_INET)
        except socket.gaierror:
            return True  # block unresolvable hosts
        for info in addrs:
            ip = ipaddress.IPv4Address(info[4][0])
            for net in _PRIVATE_NETWORKS:
                if ip in net:
                    return True
        return False

    for net in _PRIVATE_NETWORKS:
        if addr in net:
            return True
    return False


def web_fetch(url: str) -> str:
    """Fetch the text content of a web page via HTTP GET.

    **Security:** Only http/https schemes are allowed.  Private/reserved
    IP addresses (RFC 1918, loopback, link-local) are rejected to prevent
    Server-Side Request Forgery (SSRF) attacks.

    Args:
        url: The URL to fetch.

    Returns:
        First 5000 characters of the response text, or an error message.
    """
    import httpx  # lazy import — only needed when this tool is used

    try:
        parsed = urlparse(url)

        # Reject non-http/https schemes (prevents file://, ftp://, gopher://, etc.)
        if parsed.scheme not in ("http", "https"):
            return (
                f"Error: URL scheme '{parsed.scheme}' is not allowed. "
                "Only http:// and https:// URLs are supported."
            )

        # Reject URLs with no hostname
        if not parsed.hostname:
            return "Error: URL has no valid hostname."

        # SSRF check: reject private/reserved IPs
        if _is_private_ip(parsed.hostname):
            return (
                f"Error: URL resolves to a private/reserved IP address. "
                "Fetching internal/private addresses is not allowed."
            )

        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            response = client.get(
                url,
                headers={"User-Agent": "Hermes-Lite/1.0"},
                follow_redirects=True,
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
                "Read a text file and return paginated content with line numbers. "
                "Returns a JSON object with content, total_lines, offset, and limit."
            ),
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read.",
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting line number (1-indexed, default: 1).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum lines to return (default: 500, max: 2000).",
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
