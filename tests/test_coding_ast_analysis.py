"""Tests for M13: AST-based code analysis — extract_symbols, call_graph, references."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# extract_symbols
# ---------------------------------------------------------------------------

def test_extract_symbols_functions_and_classes(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import extract_symbols
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "app.py").write_text(
        "import os\n\ndef hello(name: str) -> str:\n    return f'hi {name}'\n\n"
        "class Thing:\n    def method(self, x: int) -> bool:\n        return x > 0\n"
    )
    result = extract_symbols(ws, "app.py")
    assert result["ok"] is True
    assert result["language"] == "python"
    assert result["symbol_count"] >= 2

    names = {s["name"] for s in result["symbols"]}
    assert "hello" in names
    assert "Thing" in names

    # Check function args and return type
    func = next(s for s in result["symbols"] if s["name"] == "hello")
    assert func["kind"] == "function"
    assert func["return_type"] == "str"
    assert len(func["args"]) == 1
    assert func["args"][0]["name"] == "name"
    assert func["args"][0].get("type") == "str"

    # Check class with methods
    cls = next(s for s in result["symbols"] if s["name"] == "Thing")
    assert cls["kind"] == "class"
    assert len(cls["methods"]) == 1
    assert cls["methods"][0]["name"] == "method"
    assert cls["methods"][0]["args"][0]["name"] == "self"

    # Check imports
    import_names = [i["name"] for i in result["imports"]]
    assert "os" in import_names


def test_extract_symbols_decorators(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import extract_symbols
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "deco.py").write_text(
        "@staticmethod\ndef myfunc():\n    pass\n\n"
        "@dataclass\nclass User:\n    name: str\n"
    )
    result = extract_symbols(ws, "deco.py")
    assert result["ok"] is True

    func = next(s for s in result["symbols"] if s["name"] == "myfunc")
    assert "staticmethod" in func["decorators"]

    cls = next(s for s in result["symbols"] if s["name"] == "User")
    assert "dataclass" in cls["decorators"]


def test_extract_symbols_class_inheritance(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import extract_symbols
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "base.py").write_text(
        "from abc import ABC\nclass Base(ABC):\n    pass\n"
    )
    result = extract_symbols(ws, "base.py")
    assert result["ok"] is True
    cls = result["symbols"][0]
    assert "ABC" in cls["bases"]


def test_extract_symbols_syntax_error(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import extract_symbols
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "broken.py").write_text("def broken(:\n")
    result = extract_symbols(ws, "broken.py")
    assert result["ok"] is False
    assert result["error"] == "parse_failed"


def test_extract_symbols_async_functions(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import extract_symbols
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "async_app.py").write_text(
        "import asyncio\n\nasync def fetch(url: str) -> dict:\n    return {}\n"
    )
    result = extract_symbols(ws, "async_app.py")
    assert result["ok"] is True
    func = next(s for s in result["symbols"] if s["name"] == "fetch")
    assert func["kind"] == "async_function"


def test_extract_symbols_raw_path(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import extract_symbols

    (tmp_path / "raw.py").write_text("x = 1\ndef f(): pass\n")
    result = extract_symbols(str(tmp_path), "raw.py")
    assert result["ok"] is True
    assert result["symbol_count"] == 1


def test_extract_symbols_assignments(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import extract_symbols
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "config.py").write_text("DEBUG = True\nVERSION = '1.0'\n")
    result = extract_symbols(ws, "config.py")
    assert result["ok"] is True
    names = {a["name"] for a in result["assignments"]}
    assert "DEBUG" in names
    assert "VERSION" in names


# ---------------------------------------------------------------------------
# build_call_graph
# ---------------------------------------------------------------------------

def test_call_graph_cross_file_resolution(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import build_call_graph
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "lib.py").write_text("def helper():\n    return 42\n")
    (tmp_path / "main.py").write_text("from lib import helper\n\ndef app():\n    return helper()\n")

    cg = build_call_graph(ws)
    assert cg["ok"] is True
    assert cg["node_count"] == 2

    edges = cg["edges"]
    resolved = [e for e in edges if e["resolved"]]
    assert len(resolved) >= 1
    assert any(e["callee_name"] == "helper" and e["resolved"] for e in resolved)


def test_call_graph_method_calls(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import build_call_graph
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "svc.py").write_text(
        "class Service:\n"
        "    def run(self):\n        self._init()\n"
        "    def _init(self):\n        pass\n"
    )
    cg = build_call_graph(ws)
    assert cg["ok"] is True
    edges = cg["edges"]
    resolved = [e for e in edges if e["resolved"]]
    assert any(e["callee_name"] == "_init" and e["resolved"] for e in resolved)


def test_call_graph_no_files(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import build_call_graph
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    cg = build_call_graph(ws)
    assert cg["ok"] is True
    assert cg["node_count"] == 0
    assert cg["edge_count"] == 0


# ---------------------------------------------------------------------------
# find_references
# ---------------------------------------------------------------------------

def test_find_references_basic(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import find_references
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "auth.py").write_text(
        "def authenticate(user, token):\n    return verify_jwt(token)\n\n"
        "def verify_jwt(token):\n    return True\n\n"
        "def login():\n    return authenticate('admin', 'xyz')\n"
    )

    fr = find_references(ws, "authenticate")
    assert fr["ok"] is True
    assert len(fr["definitions"]) >= 1
    assert len(fr["text_references"]) >= 2  # def + call


def test_find_references_not_found(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import find_references
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "app.py").write_text("x = 1\n")

    fr = find_references(ws, "nonexistent")
    assert fr["ok"] is True
    assert len(fr["definitions"]) == 0


def test_find_references_has_callers(tmp_path) -> None:
    from hermes_lite.coding.ast_analysis import find_references
    from hermes_lite.coding.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "lib.py").write_text(
        "def helper():\n    return 42\n\n"
        "def caller1():\n    return helper()\n\n"
        "def caller2():\n    return helper()\n"
    )

    fr = find_references(ws, "helper")
    assert fr["ok"] is True
    callers = fr["call_graph"]["callers"]
    assert len(callers) >= 2
