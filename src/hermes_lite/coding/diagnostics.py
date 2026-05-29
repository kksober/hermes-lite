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
    """Extract classes and functions from a Python file."""
    read_result = workspace.read_text(path)
    if not read_result["ok"]:
        return read_result
    try:
        tree = ast.parse(str(read_result["content"]), filename=path)
    except SyntaxError as exc:
        return {
            "ok": False,
            "error": "syntax_error",
            "diagnostics": [{
                "path": path,
                "line": exc.lineno or 0,
                "column": exc.offset or 0,
                "severity": "error",
                "message": exc.msg,
            }],
            "symbols": [],
        }

    symbols: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            symbols.append({"name": node.name, "kind": "class", "line": node.lineno})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append({"name": node.name, "kind": "function", "line": node.lineno})
    symbols.sort(key=lambda item: (int(item["line"]), str(item["name"])))
    return {"ok": True, "path": path, "symbols": symbols}


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
