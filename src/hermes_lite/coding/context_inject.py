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

_CONVENTIONS_PATH = ".hermes/conventions.md"

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


def discover_conventions(workspace_root: Path, max_chars: int = 2000) -> dict[str, Any]:
    """Find and read coding conventions from ``.hermes/conventions.md``.

    Returns:
        ``{found: bool, content: str}``
    """
    path = workspace_root / _CONVENTIONS_PATH
    if path.exists() and path.is_file():
        try:
            raw = path.read_text(encoding="utf-8")
            return {"found": True, "content": raw[:max_chars]}
        except (OSError, UnicodeDecodeError):
            pass
    return {"found": False, "content": ""}


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

    # 2. Coding conventions
    conventions = discover_conventions(workspace_root)
    if conventions["found"]:
        parts.append(
            f"<coding_conventions>\n"
            f"{conventions['content']}\n"
            f"</coding_conventions>"
        )

    # 3. Workspace snapshot
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


# ---------------------------------------------------------------------------
# per-turn context (lightweight, inject every turn)
# ---------------------------------------------------------------------------

_FRAMEWORK_INDICATORS: dict[str, tuple[str, str]] = {
    "pyproject.toml": ("Python", "uv/poetry/setuptools"),
    "package.json": ("Node.js / TypeScript", "npm/yarn/pnpm"),
    "go.mod": ("Go", "mod"),
    "Cargo.toml": ("Rust", "cargo"),
    "Gemfile": ("Ruby", "bundler"),
    "build.gradle": ("Java / Kotlin (Gradle)", "gradle"),
    "pom.xml": ("Java (Maven)", "maven"),
    "Makefile": ("C/C++", "make"),
    "CMakeLists.txt": ("C/C++", "cmake"),
    "Dockerfile": ("Docker", "docker"),
}


def detect_frameworks(workspace_root: Path) -> dict[str, Any]:
    """Detect project language/framework from config files.

    Returns a dict with ``language``, ``build_system``, and ``files`` keys.
    """
    detected: list[dict[str, str]] = []
    for filename, (lang, build) in _FRAMEWORK_INDICATORS.items():
        if (workspace_root / filename).exists():
            detected.append({"file": filename, "language": lang, "build_system": build})

    language = detected[0]["language"] if detected else "unknown"
    build_system = detected[0]["build_system"] if detected else "unknown"
    return {
        "language": language,
        "build_system": build_system,
        "files": [d["file"] for d in detected],
    }


def per_turn_context(workspace_root: Path) -> str:
    """Build a sub-200-token context snippet for per-turn injection.

    Returns an empty string when git is unavailable.
    """
    snap = workspace_snapshot(workspace_root)
    if not snap.get("branch") or snap["branch"] == "unknown":
        return ""

    lines = ["<workspace_state>"]
    lines.append(f"branch: {snap['branch']}")
    if snap.get("last_commit"):
        lines.append(f"HEAD: {snap['last_commit']}")
    changes = ""
    if snap.get("staged_files") or snap.get("modified_files"):
        changes = f"{snap.get('staged_files', 0)} staged, {snap.get('modified_files', 0)} modified"
        lines.append(f"changes: {changes}")
    lines.append("</workspace_state>")

    # Framework hint (~1 line)
    fw = detect_frameworks(workspace_root)
    if fw["language"] != "unknown":
        lines.append(f"<project>{fw['language']} ({', '.join(fw['files'])})</project>")

    snippet = "\n".join(lines)
    # Hard cap at 200 tokens (~800 chars)
    if len(snippet) > 800:
        snippet = snippet[:797] + "..."
    return snippet
