"""Minimal ANSI escape-code helpers for terminal formatting.

No external dependencies — works on any ANSI-compatible terminal.
Automatically disables color when stdout is not a TTY.
"""

from __future__ import annotations

import os
import sys

# -- detect TTY -----------------------------------------------------------


def _stdout_is_tty() -> bool:
    try:
        return os.isatty(sys.stdout.fileno())
    except Exception:
        return False


_TTY = _stdout_is_tty()

# -- ANSI codes ------------------------------------------------------------


def reset() -> str:
    return "\033[0m" if _TTY else ""


def bold() -> str:
    return "\033[1m" if _TTY else ""


def dim() -> str:
    return "\033[2m" if _TTY else ""


def red(text: str) -> str:
    if not _TTY:
        return text
    return f"\033[31m{text}\033[0m"


def green(text: str) -> str:
    if not _TTY:
        return text
    return f"\033[32m{text}\033[0m"


def yellow(text: str) -> str:
    if not _TTY:
        return text
    return f"\033[33m{text}\033[0m"


def blue(text: str) -> str:
    if not _TTY:
        return text
    return f"\033[34m{text}\033[0m"


def cyan(text: str) -> str:
    if not _TTY:
        return text
    return f"\033[36m{text}\033[0m"


def gray(text: str) -> str:
    if not _TTY:
        return text
    return f"\033[90m{text}\033[0m"


# -- diff display -----------------------------------------------------------


def color_diff(diff_text: str) -> str:
    """Colorise unified diff lines: + green, - red, @ cyan."""
    if not _TTY:
        return diff_text
    lines = []
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(f"\033[32m{line}\033[0m")
        elif line.startswith("-") and not line.startswith("---"):
            lines.append(f"\033[31m{line}\033[0m")
        elif line.startswith("@@"):
            lines.append(f"\033[36m{line}\033[0m")
        else:
            lines.append(line)
    return "\n".join(lines)


# -- formatted output helpers -----------------------------------------------


def error_box(message: str) -> str:
    if not _TTY:
        return f"ERROR: {message}"
    return f"\033[1;31m ERROR \033[0m {message}"


def success_box(message: str) -> str:
    if not _TTY:
        return f"OK: {message}"
    return f"\033[1;32m  OK   \033[0m {message}"


def spinner_chars() -> list[str]:
    return ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
