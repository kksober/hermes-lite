"""Python AST-based code analysis: symbol extraction, call graph, references.

Clean-room implementation using only Python's stdlib ``ast`` module.
Zero additional dependencies.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

from hermes_lite.coding.workspace import Workspace


# ---------------------------------------------------------------------------
# Python source parsing
# ---------------------------------------------------------------------------

def _parse_python(source: str, filepath: str = "<string>") -> ast.Module | None:
    """Parse Python source into an AST, returning None on syntax error."""
    try:
        return ast.parse(source, filename=filepath)
    except SyntaxError:
        return None


# ---------------------------------------------------------------------------
# symbol extraction
# ---------------------------------------------------------------------------

def _get_type_annotation(node: ast.expr | None) -> str | None:
    """Convert a type annotation AST node to its string representation."""
    if node is None:
        return None
    return ast.unparse(node)


def _extract_function_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    """Extract detailed function/method information from a FunctionDef node."""
    info: dict[str, Any] = {
        "name": node.name,
        "kind": "function",
        "lineno": node.lineno,
        "args": [],
        "decorators": [],
    }
    if node.returns:
        info["return_type"] = _get_type_annotation(node.returns)
    if isinstance(node, ast.AsyncFunctionDef):
        info["kind"] = "async_function"
    # Extract arguments with type annotations
    for arg in node.args.args:
        arg_info: dict[str, Any] = {"name": arg.arg}
        if arg.annotation:
            arg_info["type"] = _get_type_annotation(arg.annotation)
        info["args"].append(arg_info)
    # Decorators
    for dec in node.decorator_list:
        info["decorators"].append(ast.unparse(dec))
    # Docstring
    doc = ast.get_docstring(node)
    if doc:
        info["docstring"] = doc[:200]
    return info


def extract_symbols(workspace_or_root: Workspace | Path | str, path: str = "") -> dict[str, Any]:
    """Extract structured symbols from a Python source file.

    Returns classes, functions, imports, and module-level assignments with
    line numbers, type annotations, arguments, decorators, and inheritance.

    Parameters
    ----------
    workspace_or_root:
        A ``Workspace`` instance or a root path.  When a Workspace is used
        the *path* parameter is resolved against it.  Otherwise *path* is
        treated as a full path.
    path:
        Relative path inside the workspace, or ignored if a raw root is
        given and empty.

    Returns
    -------
    ``{ok, symbols, imports, assignments, language}``  or
    ``{ok: False, error: ...}`` on failure.
    """
    from hermes_lite.coding.workspace import Workspace as WS

    if isinstance(workspace_or_root, WS):
        read_result = workspace_or_root.read_text(path)
        if not read_result.get("ok"):
            return {"ok": False, "error": "read_failed", "message": read_result.get("error", "unknown")}
        source = str(read_result["content"])
        filepath = str(path)
    else:
        root = Path(workspace_or_root)
        full = root / path if path else root
        try:
            source = full.read_text(encoding="utf-8")
            filepath = str(full)
        except (OSError, UnicodeDecodeError) as exc:
            return {"ok": False, "error": "read_failed", "message": str(exc)}

    tree = _parse_python(source, filepath)
    if tree is None:
        return {"ok": False, "error": "parse_failed", "message": "Syntax error in Python source."}

    symbols: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []

    for node in ast.iter_child_nodes(tree):
        # --- classes -------------------------------------------------------
        if isinstance(node, ast.ClassDef):
            cls_info: dict[str, Any] = {
                "name": node.name,
                "kind": "class",
                "lineno": node.lineno,
                "bases": [ast.unparse(b) for b in node.bases],
                "decorators": [ast.unparse(d) for d in node.decorator_list],
                "methods": [],
            }
            doc = ast.get_docstring(node)
            if doc:
                cls_info["docstring"] = doc[:200]
            # Walk class body for methods
            for body_node in node.body:
                if isinstance(body_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    cls_info["methods"].append(_extract_function_info(body_node))
            symbols.append(cls_info)

        # --- functions -----------------------------------------------------
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(_extract_function_info(node))

        # --- imports -------------------------------------------------------
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "name": alias.name,
                    "alias": alias.asname,
                    "lineno": node.lineno,
                })
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.append({
                    "module": node.module or "",
                    "name": alias.name,
                    "alias": alias.asname,
                    "lineno": node.lineno,
                })

        # --- module-level assignments --------------------------------------
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.append({
                        "name": target.id,
                        "lineno": node.lineno,
                    })

    return {
        "ok": True,
        "language": "python",
        "file": filepath,
        "symbols": symbols,
        "imports": imports,
        "assignments": assignments,
        "symbol_count": len(symbols),
    }


# ---------------------------------------------------------------------------
# call graph
# ---------------------------------------------------------------------------

def _collect_calls(node: ast.AST) -> list[dict[str, Any]]:
    """Walk an AST node and collect all function/method calls within it."""
    calls: list[dict[str, Any]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        call_info: dict[str, Any] = {"lineno": child.lineno}
        if isinstance(child.func, ast.Name):
            call_info["name"] = child.func.id
            call_info["kind"] = "direct"
        elif isinstance(child.func, ast.Attribute):
            call_info["name"] = child.func.attr
            if isinstance(child.func.value, ast.Name):
                call_info["object"] = child.func.value.id
            call_info["kind"] = "method"
        else:
            call_info["name"] = "<complex>"
            call_info["kind"] = "complex"
        calls.append(call_info)
    return calls


def build_call_graph(
    workspace: Workspace,
    file_patterns: list[str] | None = None,
) -> dict[str, Any]:
    """Build a cross-file call graph for Python source files in a workspace.

    Scans Python files, extracts function/class definitions (nodes) and call
    relationships (edges).  Resolves cross-file calls by matching call names
    against symbols defined in imported modules.

    Parameters
    ----------
    workspace:
        The workspace to scan.
    file_patterns:
        Optional glob patterns to restrict scanning (default ``["**/*.py"]``).

    Returns
    -------
    ``{ok, nodes, edges, file_count}`` with:
    - ``nodes``:  ``{qualified_name: {file, kind, lineno}}``
    - ``edges``:  ``[{caller, callee, file, lineno}]``
    """
    from hermes_lite.coding.context import list_files

    patterns = file_patterns or ["**/*.py"]
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    # Map simple names → their qualified names for cross-file resolution
    name_index: dict[str, list[str]] = {}

    for pattern in patterns:
        result = list_files(workspace, pattern=pattern, limit=500)
        if not result.get("ok"):
            continue
        for fpath in result.get("files", []):
            r = extract_symbols(workspace, fpath)
            if not r.get("ok"):
                continue
            # Register definitions
            for sym in r.get("symbols", []):
                qname = f"{fpath}::{sym['name']}"
                nodes[qname] = {
                    "file": fpath,
                    "kind": sym.get("kind", "unknown"),
                    "lineno": sym.get("lineno", 0),
                }
                name_index.setdefault(sym["name"], []).append(qname)
                # Also register class methods
                for m in sym.get("methods", []):
                    m_qname = f"{fpath}::{sym['name']}.{m['name']}"
                    nodes[m_qname] = {
                        "file": fpath,
                        "kind": "method",
                        "lineno": m.get("lineno", 0),
                    }
                    name_index.setdefault(m["name"], []).append(m_qname)

    # Collect call edges
    for pattern in patterns:
        result = list_files(workspace, pattern=pattern, limit=500)
        if not result.get("ok"):
            continue
        for fpath in result.get("files", []):
            r = extract_symbols(workspace, fpath)
            if not r.get("ok"):
                continue
            # For each function/method, collect calls in its body
            # We need the raw AST for this — re-parse
            read_r = workspace.read_text(fpath)
            if not read_r.get("ok"):
                continue
            source = str(read_r.get("content"))
            tree = _parse_python(source, str(fpath))
            if tree is None:
                continue
            # Find all function bodies and collect their calls
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                # Determine caller qualified name
                caller_file = fpath
                caller_name = node.name
                # Check if this function is a method of a class
                for parent in ast.iter_child_nodes(tree):
                    if isinstance(parent, ast.ClassDef) and node in parent.body:
                        caller_name = f"{parent.name}.{node.name}"
                        break
                caller_qname = f"{caller_file}::{caller_name}"
                calls = _collect_calls(node)
                for call in calls:
                    callee_qname = None
                    callee_name = call["name"]
                    if callee_name in name_index:
                        callee_qname = name_index[callee_name][0]
                    edges.append({
                        "caller": caller_qname,
                        "callee": callee_qname or callee_name,
                        "callee_name": callee_name,
                        "resolved": callee_qname is not None,
                        "file": fpath,
                        "lineno": call["lineno"],
                    })

    return {
        "ok": True,
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


# ---------------------------------------------------------------------------
# find references
# ---------------------------------------------------------------------------

def find_references(
    workspace: Workspace,
    symbol_name: str,
) -> dict[str, Any]:
    """Find definitions, textual references, and callers/callees for a symbol.

    Uses call-graph analysis for precise call-relationship data, and
    text search for all textual occurrences.

    Parameters
    ----------
    workspace:
        The workspace to search.
    symbol_name:
        The unqualified symbol name to find (e.g. ``"authenticate"``).

    Returns
    -------
    ``{ok, symbol_name, definitions, text_references, call_graph}``
    """
    from hermes_lite.coding.context import search_text

    cg = build_call_graph(workspace)

    # Find definitions in the call graph nodes
    definitions: list[dict[str, Any]] = []
    for qname, info in cg.get("nodes", {}).items():
        simple = qname.rsplit("::", 1)[-1].split(".", 1)[-1]  # last component
        if info["kind"] in ("class",):
            simple = qname.rsplit("::", 1)[-1]
        if info.get("file", ""):
            pass
        if simple == symbol_name:
            definitions.append({"qualified_name": qname, **info})

    # Also try exact match on the symbol name
    if not definitions:
        for qname, info in cg.get("nodes", {}).items():
            if qname.endswith(f"::{symbol_name}") or qname.endswith(f".{symbol_name}"):
                definitions.append({"qualified_name": qname, **info})

    # Text search for all occurrences
    text_refs = search_text(workspace, symbol_name, limit=50)

    # Call graph: callers and callees
    callers: list[dict[str, Any]] = []
    callees: list[dict[str, Any]] = []
    for edge in cg.get("edges", []):
        if edge.get("callee_name") == symbol_name:
            callers.append(edge)
        # Check if caller matches any definition
        caller_simple = edge.get("caller", "").rsplit("::", 1)[-1]
        if caller_simple == symbol_name or caller_simple.endswith(f".{symbol_name}"):
            callees.append(edge)

    return {
        "ok": True,
        "symbol_name": symbol_name,
        "definitions": definitions,
        "text_references": text_refs.get("matches", [])[:20],
        "call_graph": {
            "callers": callers,
            "callees": callees,
        },
        "total_references": len(text_refs.get("matches", [])),
    }
