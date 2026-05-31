"""Patch helpers for exact text edits, unified diff application, and diff summaries.

Clean-room implementation — no OpenCode code or structure referenced.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

from hermes_lite.coding.workspace import Workspace


# ---------------------------------------------------------------------------
# exact text replacement (legacy, kept for backward compat)
# ---------------------------------------------------------------------------


def apply_text_patch(
    workspace: Workspace,
    path: str,
    old_text: str,
    new_text: str,
    *,
    replace_all: bool = False,
    fuzzy: bool = False,
) -> dict[str, object]:
    """Apply an exact text replacement inside a workspace file.

    When *fuzzy* is True and an exact match fails, retries with
    trailing-whitespace and indent-tolerant matching strategies.
    """
    if old_text == "":
        return {"ok": False, "error": "empty_old_text", "path": path}

    read_result = workspace.read_text(path)
    if not read_result["ok"]:
        return read_result

    content = str(read_result["content"])

    def _do_replace(match_key: str) -> dict[str, object]:
        occ = content.count(match_key)
        mr = occ if replace_all else 1
        updated = content.replace(match_key, new_text, mr)
        wr = workspace.write_text(path, updated)
        if not wr["ok"]:
            return wr
        return {
            "ok": True,
            "path": wr["path"],
            "relative_path": wr["relative_path"],
            "replacements": mr,
            "bytes": wr["bytes"],
        }

    occurrences = content.count(old_text)
    if occurrences > 0:
        result = _do_replace(old_text)
        result["match_strategy"] = "exact"
        return result

    if not fuzzy:
        return {
            "ok": False,
            "error": "patch_mismatch",
            "path": path,
            "relative_path": read_result.get("relative_path", path),
            "message": "old_text was not found in the target file.",
        }

    match_key = _fuzzy_find(content, old_text)
    if match_key is not None:
        result = _do_replace(match_key)
        result["match_strategy"] = "fuzzy"
        return result

    return {
        "ok": False,
        "error": "patch_mismatch",
        "path": path,
        "relative_path": read_result.get("relative_path", path),
        "message": "old_text was not found in the target file (fuzzy matching also failed).",
    }


# ---------------------------------------------------------------------------
# fuzzy matching helpers
# ---------------------------------------------------------------------------


def _fuzzy_find(content: str, old_text: str) -> str | None:
    """Locate *old_text* in *content* with fuzzy line-by-line matching.

    Tries two strategies in order:
    1. Trailing-whitespace tolerance (compare lines with rstrip)
    2. Indent tolerance (compare lines with lstrip, trust the file's indentation)

    Returns the actual matching text from *content* so it can be used as an
    exact replacement key, or ``None`` if no match found.
    """
    old_lines = old_text.splitlines()
    content_lines = content.splitlines()
    n = len(old_lines)
    if n == 0 or n > len(content_lines):
        return None

    # Strategy 1: trailing whitespace tolerance
    old_stripped = [l.rstrip() for l in old_lines]
    content_stripped = [l.rstrip() for l in content_lines]
    for i in range(len(content_stripped) - n + 1):
        if all(content_stripped[i + j] == old_stripped[j] for j in range(n)):
            return "\n".join(content_lines[i : i + n])

    # Strategy 2: indent tolerance
    old_noindent = [l.lstrip() for l in old_lines]
    content_noindent = [l.lstrip() for l in content_lines]
    for i in range(len(content_noindent) - n + 1):
        if all(content_noindent[i + j] == old_noindent[j] for j in range(n)):
            return "\n".join(content_lines[i : i + n])

    return None


# ---------------------------------------------------------------------------
# unified diff parsing and application
# ---------------------------------------------------------------------------


@dataclass
class Hunk:
    """A single hunk within a unified diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: list[tuple[str, str]]  # (kind, text) — kind in {context, remove, add}


@dataclass
class ParsedDiff:
    """A parsed unified diff for a single file."""

    old_path: str
    new_path: str
    hunks: list[Hunk]


def parse_unified_diff(diff_text: str) -> ParsedDiff | None:
    """Parse a single-file unified diff into structured form.

    Returns ``None`` if the diff cannot be parsed.
    """
    lines = diff_text.splitlines()
    if len(lines) < 3:
        return None

    old_path = ""
    new_path = ""
    hunks: list[Hunk] = []
    current_hunk_lines: list[tuple[str, str]] = []
    current_header = ""
    old_start = old_count = new_start = new_count = 0

    i = 0
    # Parse file headers
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            old_path = _strip_git_prefix(line[4:].strip())
        elif line.startswith("+++ "):
            new_path = _strip_git_prefix(line[4:].strip())
        elif line.startswith("@@"):
            break
        i += 1

    if not old_path and not new_path:
        return None

    # Parse hunks
    while i < len(lines):
        line = lines[i]
        if line.startswith("@@"):
            # flush previous hunk
            if current_header:
                hunks.append(Hunk(
                    old_start=old_start, old_count=old_count,
                    new_start=new_start, new_count=new_count,
                    header=current_header,
                    lines=current_hunk_lines,
                ))
            current_header = line
            current_hunk_lines = []
            nums = _parse_hunk_header(line)
            if nums is None:
                return None
            old_start, old_count, new_start, new_count = nums
        elif line.startswith(" "):
            current_hunk_lines.append(("context", line[1:]))
        elif line.startswith("-"):
            current_hunk_lines.append(("remove", line[1:]))
        elif line.startswith("+"):
            current_hunk_lines.append(("add", line[1:]))
        elif line == r"\ No newline at end of file":
            pass  # marker line, skip
        i += 1

    # flush last hunk
    if current_header:
        hunks.append(Hunk(
            old_start=old_start, old_count=old_count,
            new_start=new_start, new_count=new_count,
            header=current_header,
            lines=current_hunk_lines,
        ))

    return ParsedDiff(old_path=old_path, new_path=new_path, hunks=hunks)


def apply_unified_diff(
    workspace: Workspace,
    path: str,
    diff_text: str,
    *,
    dry_run: bool = False,
    fuzzy: int = 0,
) -> dict[str, object]:
    """Apply a unified diff to a workspace file.

    Parameters
    ----------
    workspace:
        Workspace boundary.
    path:
        Target file path (workspace-relative).
    diff_text:
        Unified diff text.
    dry_run:
        If ``True``, validate the patch applies cleanly without writing.
    fuzzy:
        Number of context lines that may differ and still allow the hunk to
        match.  Default 0 (strict match).

    Returns
    -------
    A dict with ``ok``, and on success ``hunks_applied``, ``path``.
    On failure, ``error`` with ``conflicts`` detail.
    """
    parsed = parse_unified_diff(diff_text)
    if parsed is None:
        return {"ok": False, "error": "parse_failed", "message": "Could not parse unified diff."}

    read_result = workspace.read_text(path)
    if not read_result["ok"]:
        return read_result

    content = str(read_result["content"])
    original_lines = content.splitlines(keepends=True)

    # Normalize: always have trailing newline for diff matching
    if content and not content.endswith("\n"):
        trailing_newline = False
        work_lines = original_lines[:]
    else:
        trailing_newline = True
        work_lines = original_lines[:]

    conflicts: list[dict[str, Any]] = []
    offset = 0
    applied = 0

    for hunk in parsed.hunks:
        result = _apply_hunk(work_lines, hunk, offset, fuzzy=fuzzy)
        if result is None:
            conflicts.append({
                "hunk_header": hunk.header,
                "old_start": hunk.old_start,
                "old_count": hunk.old_count,
                "message": "Hunk could not be applied at the expected position.",
            })
            continue
        work_lines, delta, _warnings = result
        offset += delta
        applied += 1

    if conflicts:
        return {
            "ok": False,
            "error": "patch_conflict",
            "path": path,
            "hunks_total": len(parsed.hunks),
            "hunks_applied": applied,
            "conflicts": conflicts,
        }

    new_content = "".join(work_lines)

    if dry_run:
        return {
            "ok": True,
            "path": path,
            "dry_run": True,
            "hunks_applied": applied,
            "hunks_total": len(parsed.hunks),
            "patch_preview": _patch_preview(content, new_content),
        }

    write_result = workspace.write_text(path, new_content)
    if not write_result["ok"]:
        return write_result

    return {
        "ok": True,
        "path": write_result["path"],
        "relative_path": write_result["relative_path"],
        "hunks_applied": applied,
        "hunks_total": len(parsed.hunks),
        "bytes": write_result["bytes"],
        "patch_summary": _patch_preview(content, new_content),
    }


def patch_dry_run(
    workspace: Workspace, path: str, diff_text: str, *, fuzzy: int = 0
) -> dict[str, object]:
    """Check whether a unified diff would apply cleanly, without writing."""
    return apply_unified_diff(workspace, path, diff_text, dry_run=True, fuzzy=fuzzy)


# ---------------------------------------------------------------------------
# diff summary
# ---------------------------------------------------------------------------


def diff_summary(
    workspace: Workspace,
    path: str,
    old_content: str | None = None,
) -> dict[str, object]:
    """Generate a summary of changes made to a file.

    If *old_content* is provided, diff against it; otherwise reads the file.
    Returns added/removed line counts and a unified diff preview.
    """
    read_result = workspace.read_text(path)
    if not read_result["ok"]:
        return read_result

    new_content = str(read_result["content"])

    if old_content is None:
        # We only have current content; can't diff without old
        return {
            "ok": True,
            "path": path,
            "current_lines": len(new_content.splitlines()),
            "message": "No old content provided; cannot compute diff.",
        }

    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=path, tofile=path,
        lineterm="",
    ))

    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

    return {
        "ok": True,
        "path": path,
        "lines_added": added,
        "lines_removed": removed,
        "diff_preview": "\n".join(diff[:80]),  # first 80 lines of diff
        "diff_truncated": len(diff) > 80,
    }


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _strip_git_prefix(path: str) -> str:
    """Strip the ``a/`` or ``b/`` git prefix from a diff path."""
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _parse_hunk_header(header: str) -> tuple[int, int, int, int] | None:
    """Parse ``@@ -old_start,old_count +new_start,new_count @@``."""
    import re
    m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
    if not m:
        return None
    old_start = int(m.group(1))
    old_count = int(m.group(2)) if m.group(2) is not None else 1
    new_start = int(m.group(3))
    new_count = int(m.group(4)) if m.group(4) is not None else 1
    return old_start, old_count, new_start, new_count


def _apply_hunk(
    lines: list[str],
    hunk: Hunk,
    offset: int,
    fuzzy: int = 0,
) -> tuple[list[str], int, list[str]] | None:
    """Attempt to apply a single hunk to *lines*.

    Returns ``(new_lines, delta, warnings)`` on success, ``None`` if the
    hunk does not match.
    """
    search_start = max(0, hunk.old_start - 1 + offset - fuzzy)
    search_end = min(len(lines), hunk.old_start - 1 + offset + fuzzy + hunk.old_count)

    context_lines = [t for kind, t in hunk.lines if kind in ("context", "remove")]

    best_match = None
    for candidate in range(search_start, search_end):
        if candidate + len(context_lines) > len(lines):
            break
        mismatch = 0
        ctx_idx = 0
        for ki, (kind, text) in enumerate(hunk.lines):
            if kind == "add":
                continue
            if candidate + ctx_idx >= len(lines):
                mismatch += 1
                break
            if lines[candidate + ctx_idx].rstrip("\n") != text:
                mismatch += 1
            ctx_idx += 1
        if mismatch <= fuzzy:
            best_match = candidate
            break

    if best_match is None:
        return None

    result: list[str] = []
    warnings: list[str] = []
    # Copy lines before the hunk
    result.extend(lines[:best_match])

    # Apply the hunk
    ctx_idx = 0
    for kind, text in hunk.lines:
        if kind == "context":
            if best_match + ctx_idx < len(lines):
                result.append(lines[best_match + ctx_idx])
            else:
                result.append(text + "\n")
            ctx_idx += 1
        elif kind == "remove":
            ctx_idx += 1
        elif kind == "add":
            result.append(text + "\n")

    # Copy lines after the hunk
    result.extend(lines[best_match + ctx_idx:])

    new_count = sum(1 for kind, _ in hunk.lines if kind != "remove")
    delta = new_count - hunk.old_count + (best_match - (hunk.old_start - 1 + offset))

    return result, delta, warnings


def _patch_preview(old: str, new: str) -> dict[str, object]:
    """Return a compact preview of what a patch changes."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        old_lines, new_lines, fromfile="a", tofile="b", lineterm="",
    ))
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    return {
        "lines_added": added,
        "lines_removed": removed,
        "hunks": sum(1 for line in diff if line.startswith("@@")),
        "diff_preview": "\n".join(diff[:40]),
    }
