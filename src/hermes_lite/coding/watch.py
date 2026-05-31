"""File watch mode — monitor files and run actions on changes.

Read-only analysis: detects changes and reports them.  Does NOT auto-edit.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


def watch_files(
    workspace_root: str,
    globs: list[str],
    *,
    poll_interval: float = 1.0,
    max_cycles: int = 0,
    on_change_command: str = "",
) -> dict[str, Any]:
    """Poll *globs* for changes and optionally run *on_change_command*.

    Parameters
    ----------
    workspace_root:
        Root directory to watch.
    globs:
        List of glob patterns, e.g. ``["**/*.py", "**/*.ts"]``.
    poll_interval:
        Seconds between checks.
    max_cycles:
        Max polling cycles (0 = unlimited).  Because this is a blocking
        call, the agent should use it with care.
    on_change_command:
        Shell command to run when a change is detected (optional).

    Returns
    -------
    ``{ok, watched_files, changes_detected, cycles_completed, output}``
    """
    root = Path(workspace_root)
    if not root.is_dir():
        return {"ok": False, "error": "invalid_workspace"}

    # Build initial snapshot
    snapshot: dict[str, float] = {}
    for pattern in globs:
        for fpath in root.glob(pattern):
            try:
                snapshot[str(fpath)] = fpath.stat().st_mtime
            except OSError:
                continue

    cycles = 0
    changes: list[dict[str, Any]] = []
    output_lines: list[str] = []

    try:
        while True:
            cycles += 1
            time.sleep(poll_interval)
            current_snapshot: dict[str, float] = {}
            for pattern in globs:
                for fpath in root.glob(pattern):
                    try:
                        current_snapshot[str(fpath)] = fpath.stat().st_mtime
                    except OSError:
                        continue

            # Detect changes
            for path, mtime in current_snapshot.items():
                if path not in snapshot:
                    changes.append({"path": path, "change": "created", "at": mtime})
                elif mtime != snapshot[path]:
                    changes.append({"path": path, "change": "modified", "at": mtime})

            for path in snapshot:
                if path not in current_snapshot:
                    changes.append({"path": path, "change": "deleted", "at": time.time()})

            if changes:
                output_lines.append(f"[watch] {len(changes)} file(s) changed in cycle {cycles}")
                for c in changes:
                    output_lines.append(f"  {c['change']}: {c['path']}")
                if on_change_command:
                    import subprocess
                    try:
                        proc = subprocess.run(
                            on_change_command, shell=True, cwd=str(root),
                            capture_output=True, text=True, timeout=30,
                        )
                        output_lines.append(f"[cmd] {on_change_command}")
                        output_lines.append(proc.stdout[:1000])
                    except Exception as exc:
                        output_lines.append(f"[cmd error] {exc}")

            snapshot = current_snapshot

            if max_cycles > 0 and cycles >= max_cycles:
                break
            if cycles > 600:  # safety cap: 10 min at 1s polling
                break

    except KeyboardInterrupt:
        output_lines.append("[watch] interrupted by user")

    return {
        "ok": True,
        "watched_files": len(snapshot),
        "changes_detected": len(changes),
        "cycles_completed": cycles,
        "changes": changes[:100],
        "output": "\n".join(output_lines),
    }


def watch_status(workspace_root: str, globs: list[str]) -> dict[str, Any]:
    """Return a one-shot snapshot of watched files with no polling loop.

    Useful as a quick check: "what files match these globs right now."
    """
    root = Path(workspace_root)
    if not root.is_dir():
        return {"ok": False, "error": "invalid_workspace"}

    files: list[str] = []
    for pattern in globs:
        for fpath in root.glob(pattern):
            files.append(str(fpath.relative_to(root)))

    return {
        "ok": True,
        "globs": globs,
        "file_count": len(files),
        "files": sorted(files)[:200],
    }
