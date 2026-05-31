"""Lightweight diagnostics and symbol extraction backends."""

from __future__ import annotations

import ast
from pathlib import Path

from hermes_lite.coding.context import list_files
from hermes_lite.coding.workspace import Workspace


def diagnose_python(workspace: Workspace, path: str = ".") -> dict[str, object]:
    """Return Python syntax diagnostics for a file or directory."""
    targets = _python_targets(workspace, path)
    diagnostics: list[dict[str, object]] = []
    for target in targets:
        read_result = workspace.read_text(target)
        if not read_result["ok"]:
            diagnostics.append({
                "path": target,
                "line": 0,
                "column": 0,
                "severity": "error",
                "message": str(read_result.get("error", "read_failed")),
            })
            continue
        try:
            ast.parse(str(read_result["content"]), filename=target)
        except SyntaxError as exc:
            diagnostics.append({
                "path": target,
                "line": exc.lineno or 0,
                "column": exc.offset or 0,
                "severity": "error",
                "message": exc.msg,
            })
    return {"ok": len(diagnostics) == 0, "diagnostics": diagnostics}


def extract_python_symbols(workspace: Workspace, path: str) -> dict[str, object]:
    """Extract classes, functions, methods, and imports from a Python file.

    Delegates to ``ast_analysis.extract_symbols`` for deep extraction,
    returning a superset of the original flat symbol list.
    """
    from hermes_lite.coding.ast_analysis import extract_symbols as _extract

    result = _extract(workspace, path)
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error", "unknown"),
            "diagnostics": [result.get("message", "")],
            "symbols": [],
        }

    # Build the flat symbol list for backward compatibility
    symbols: list[dict[str, object]] = []
    for sym in result.get("symbols", []):
        symbols.append({
            "name": sym["name"],
            "kind": sym.get("kind", "function"),
            "line": sym.get("lineno", 0),
        })
        for m in sym.get("methods", []):
            symbols.append({
                "name": f"{sym['name']}.{m['name']}",
                "kind": "method",
                "line": m.get("lineno", 0),
            })

    symbols.sort(key=lambda item: (int(item.get("line", 0)), str(item.get("name", ""))))
    return {
        "ok": True,
        "path": path,
        "symbols": symbols,
        "imports": result.get("imports", []),
        "assignments": result.get("assignments", []),
    }


def _python_targets(workspace: Workspace, path: str) -> list[str]:
    check = workspace.resolve(path, operation="read")
    if not check.ok:
        return [path]
    if check.path.is_file():
        return [check.relative_path] if check.relative_path.endswith(".py") else []
    return [
        rel for rel in list_files(workspace, pattern=f"{check.relative_path}/**/*.py" if check.relative_path != "." else "**/*.py", limit=2000)["files"]
        if Path(rel).suffix == ".py"
    ]
