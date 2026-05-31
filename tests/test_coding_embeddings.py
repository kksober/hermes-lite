"""Tests for semantic code search."""
from __future__ import annotations


def test_tokenize_strips_stopwords_and_punctuation() -> None:
    from hermes_lite.coding.embeddings import _tokenize

    tokens = _tokenize("def test_user_authentication(self, request): pass")
    assert "test_user_authentication" in tokens
    assert "request" in tokens
    assert "def" not in tokens
    assert "self" not in tokens
    assert "pass" not in tokens


def test_tokenize_splits_camelcase() -> None:
    from hermes_lite.coding.embeddings import _tokenize

    tokens = _tokenize("UserAuthenticationHandler")
    assert "userauthenticationhandler" in tokens


def test_semantic_index_build_and_search() -> None:
    from hermes_lite.coding.embeddings import SemanticIndex

    idx = SemanticIndex(backend="text")
    idx.index_files({
        "auth.py": "def login(user, password):\n    return check_credentials(user, password)",
        "db.py": "class Database:\n    def connect(self):\n        return Connection()",
        "test_auth.py": "def test_login():\n    assert login('admin', 'secret')",
    })

    results = idx.search("authentication user login")
    assert len(results) > 0
    assert results[0]["path"] == "auth.py"
    assert results[0]["score"] > 0


def test_semantic_index_ranks_db_above_auth_for_db_query() -> None:
    from hermes_lite.coding.embeddings import SemanticIndex

    idx = SemanticIndex(backend="text")
    idx.index_files({
        "auth.py": "def login(user, password): pass",
        "db.py": "class Database:\n    def connect(self, host, port):\n        return db_connection(host, port)",
    })

    results = idx.search("database connection")
    assert len(results) > 0
    assert results[0]["path"] == "db.py"


def test_semantic_index_empty_returns_empty() -> None:
    from hermes_lite.coding.embeddings import SemanticIndex

    idx = SemanticIndex(backend="text")
    idx.index_files({})
    results = idx.search("anything")
    assert results == []


def test_semantic_index_clear_resets() -> None:
    from hermes_lite.coding.embeddings import SemanticIndex

    idx = SemanticIndex(backend="text")
    idx.index_files({"a.py": "print('hello')"})
    assert len(idx._docs) == 1
    idx.clear()
    assert len(idx._docs) == 0


def test_semantic_search_tool(tmp_path) -> None:
    from hermes_lite.coding.embeddings import semantic_search

    (tmp_path / "auth.py").write_text("def authenticate(user, token):\n    return verify_jwt(token)")
    (tmp_path / "models.py").write_text("class User:\n    name: str\n    email: str")

    result = semantic_search(str(tmp_path), "user authentication jwt")
    assert result["ok"] is True
    assert result["total_files"] > 0
    assert len(result["results"]) > 0
    result_paths = {r["path"] for r in result["results"]}
    assert "auth.py" in result_paths
    assert "models.py" in result_paths


def test_semantic_search_invalid_root() -> None:
    from hermes_lite.coding.embeddings import semantic_search

    result = semantic_search("/nonexistent/path", "query")
    assert result["ok"] is False
    assert result["error"] == "invalid_workspace"


def test_build_semantic_index(tmp_path) -> None:
    from hermes_lite.coding.embeddings import build_semantic_index

    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "b.py").write_text("y = 2")

    result = build_semantic_index(str(tmp_path))
    assert result["ok"] is True
    assert result["indexed_files"] == 2
    assert result["backend"] == "text"


def test_semantic_index_extract_snippet() -> None:
    from hermes_lite.coding.embeddings import SemanticIndex

    idx = SemanticIndex(backend="text")
    content = "line1\nline2\ndef login():\n    pass\nline5\n"
    snippet = idx._extract_snippet(content, "login")
    assert "def login" in snippet
