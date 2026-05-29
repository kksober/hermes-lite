"""Patch helpers for exact text edits."""

from __future__ import annotations

from hermes_lite.coding.workspace import Workspace


def apply_text_patch(
    workspace: Workspace,
    path: str,
    old_text: str,
    new_text: str,
    *,
    replace_all: bool = False,
) -> dict[str, object]:
    """Apply an exact text replacement inside a workspace file."""
    if old_text == "":
        return {"ok": False, "error": "empty_old_text", "path": path}

    read_result = workspace.read_text(path)
    if not read_result["ok"]:
        return read_result

    content = str(read_result["content"])
    occurrences = content.count(old_text)
    if occurrences == 0:
        return {
            "ok": False,
            "error": "patch_mismatch",
            "path": path,
            "relative_path": read_result.get("relative_path", path),
            "message": "old_text was not found in the target file.",
        }

    max_replacements = occurrences if replace_all else 1
    updated = content.replace(old_text, new_text, max_replacements)
    write_result = workspace.write_text(path, updated)
    if not write_result["ok"]:
        return write_result
    return {
        "ok": True,
        "path": write_result["path"],
        "relative_path": write_result["relative_path"],
        "replacements": max_replacements,
        "bytes": write_result["bytes"],
    }
