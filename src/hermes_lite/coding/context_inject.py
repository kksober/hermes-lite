"""Auto-context injection for coding agent conversations.

Discovers project rules (``.hermes/rules.md``) and builds a lightweight
workspace snapshot (git branch, recent activity) for injection into the
system prompt at conversation start.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# rules.md discovery
# ---------------------------------------------------------------------------

_RULES_CANDIDATES = [
    ".hermes/rules.md",
    "CLAUDE.md",
    "AGENTS.md",
    ".cursorrules",
]

_DEFAULT_MAX_RULES_CHARS = 3000


def discover_rules(workspace_root: Path, max_chars: int = _DEFAULT_MAX_RULES_CHARS) -> dict[str, Any]:
    """Find and read project rules from the workspace.

    Checks ``.hermes/rules.md`` first, then falls back to ``CLAUDE.md``
    and ``AGENTS.md`` for compatibility with other tools.

    Returns:
        ``{found: bool, source: str, content: str}``
    """
    for candidate in _RULES_CANDIDATES:
        path = workspace_root / candidate
        if path.exists() and path.is_file():
            try:
                raw = path.read_text(encoding="utf-8")
                return {
                    "found": True,
                    "source": candidate,
                    "content": raw[:max_chars],
                }
            except (OSError, UnicodeDecodeError):
                continue
    return {"found": False, "source": "", "content": ""}


# ---------------------------------------------------------------------------
# workspace snapshot
# ---------------------------------------------------------------------------

def workspace_snapshot(workspace_root: Path) -> dict[str, Any]:
    """Return a lightweight snapshot of workspace state.

    Includes: branch name, recent commit, modified/staged file counts.
    Falls back gracefully for non-git directories.
    """
    try:
        branch = _git_branch(workspace_root)
    except Exception:
        branch = "unknown"

    try:
        last_commit = _git_last_commit(workspace_root)
    except Exception:
        last_commit = ""

    modified = 0
    staged = 0
    try:
        status = subprocess.run(
            ["git", "-C", str(workspace_root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        for line in status.stdout.splitlines():
            if line.strip():
                idx = line[:2].strip()
                if idx in ("M", "A", "D", "R", "C"):
                    staged += 1
                elif idx in ("??",):
                    continue
                else:
                    modified += 1
    except Exception:
        pass

    return {
        "ok": True,
        "branch": branch,
        "last_commit": last_commit[:120],
        "modified_files": modified,
        "staged_files": staged,
    }


def _git_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or "HEAD"
    except Exception:
        return "unknown"


def _git_last_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--oneline", "--no-decorate"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# context preamble builder
# ---------------------------------------------------------------------------

def build_context_preamble(
    workspace_root: Path,
    max_tokens: int = 500,
) -> str:
    """Build a compact context preamble for injection into the system prompt.

    Includes rules.md content and a workspace snapshot, trimmed to fit
    within *max_tokens* (rough estimate: 4 chars ≈ 1 token).

    Parameters
    ----------
    workspace_root:
        The workspace root directory.
    max_tokens:
        Rough token budget for the preamble.

    Returns
    -------
    A string suitable for prepending to the system prompt.
    """
    max_chars = max_tokens * 4
    parts: list[str] = []

    # 1. Rules
    rules = discover_rules(workspace_root)
    if rules["found"]:
        parts.append(
            f"<project_rules source=\"{rules['source']}\">\n"
            f"{rules['content']}\n"
            f"</project_rules>"
        )

    # 2. Workspace snapshot
    snap = workspace_snapshot(workspace_root)
    if snap.get("branch"):
        lines = [
            f"<workspace_context>",
            f"  branch: {snap['branch']}",
        ]
        if snap.get("last_commit"):
            lines.append(f"  last_commit: {snap['last_commit']}")
        if snap.get("modified_files") or snap.get("staged_files"):
            lines.append(
                f"  changes: {snap.get('staged_files', 0)} staged, "
                f"{snap.get('modified_files', 0)} modified"
            )
        lines.append("</workspace_context>")
        parts.append("\n".join(lines))

    preamble = "\n\n".join(parts)

    # Trim to budget
    if len(preamble) > max_chars:
        preamble = preamble[:max_chars] + "\n..."
    return preamble
