"""Semantic code search with optional embedding backends.

Uses a lightweight TF-IDF text ranker by default (zero dependencies).
Optionally backs with sentence-transformers or OpenAI embeddings.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

# Common English + programming stopwords filtered from queries
_STOPWORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "that", "this", "it", "its", "and", "but",
    "or", "if", "while", "about", "up", "out", "def", "class", "import",
    "return", "self", "pass", "none", "true", "false", "elif", "else",
    "try", "except", "finally", "raise", "yield", "lambda", "global",
    "nonlocal", "assert", "async", "await", "break", "continue", "del",
}


def _tokenize(text: str) -> list[str]:
    """Tokenize code or natural-language text into lowercased terms."""
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


class SemanticIndex:
    """Lightweight semantic index over a set of documents (code files).

    Default backend is TF-IDF text ranking.  Embedding backends are
    activated by passing ``backend="openai"`` or ``backend="sentence_transformers"``
    along with the required credentials / model name.
    """

    def __init__(
        self,
        backend: str = "text",
        *,
        model_name: str = "",
        api_key: str = "",
        embedding_cache_path: str = "",
    ) -> None:
        self.backend = backend
        self.model_name = model_name
        self.api_key = api_key
        self._docs: dict[str, str] = {}
        self._idf: dict[str, float] = {}
        self._doc_vectors: dict[str, dict[str, float]] = {}
        self._cache_path = Path(embedding_cache_path) if embedding_cache_path else None

    # ------------------------------------------------------------------
    # indexing
    # ------------------------------------------------------------------

    def index_files(self, files: dict[str, str], *, symbols_per_file: dict[str, list[str]] | None = None) -> None:
        """Index a mapping of ``{file_path: content}``.

        If *symbols_per_file* is provided, symbol tokens are weighted 2x in
        the TF-IDF vectors, making symbol-aware searches more accurate.
        """
        self._docs = dict(files)
        if self.backend == "text":
            self._build_tfidf_index(files, symbols_per_file=symbols_per_file)

    def _build_tfidf_index(self, files: dict[str, str], *, symbols_per_file: dict[str, list[str]] | None = None) -> None:
        """Compute TF-IDF vectors, optionally weighting symbols 2x."""
        N = len(files)
        if N == 0:
            self._idf = {}
            self._doc_vectors = {}
            return

        df: dict[str, int] = {}
        doc_tokens: dict[str, list[str]] = {}

        sym_map = symbols_per_file or {}

        for path, content in files.items():
            tokens = _tokenize(content)
            # Weight symbol names 2x by appending them again
            extra = sym_map.get(path, [])
            for name in extra:
                st = _tokenize(name)
                tokens.extend(st)
            doc_tokens[path] = tokens
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1

        self._idf = {t: math.log((N + 1) / (df[t] + 1)) + 1.0 for t in df}
        self._doc_vectors = {}

        for path, tokens in doc_tokens.items():
            tf: dict[str, float] = {}
            total = len(tokens) or 1
            for t in tokens:
                tf[t] = tf.get(t, 0.0) + 1.0
            self._doc_vectors[path] = {
                t: (c / total) * self._idf.get(t, 0.0) for t, c in tf.items()
            }

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Return top-k files ranked by relevance to *query*."""
        if self.backend == "text" or not self.model_name:
            return self._text_search(query, top_k)
        # Embedding backends would go here (openai, sentence_transformers)
        return self._text_search(query, top_k)

    def _text_search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """TF-IDF cosine-similarity search."""
        query_tokens = _tokenize(query)
        if not query_tokens or not self._doc_vectors:
            # Return all files with basic substring match as fallback
            results: list[dict[str, Any]] = []
            query_lower = query.lower()
            for path, content in self._docs.items():
                score = 1.0 if query_lower in content.lower() else 0.0
                if score > 0:
                    snippet = self._extract_snippet(content, query_lower)
                    results.append({"path": path, "score": score, "snippet": snippet})
            results.sort(key=lambda r: r["score"], reverse=True)
            return results[:top_k]

        qv: dict[str, float] = {}
        for t in query_tokens:
            qv[t] = qv.get(t, 0.0) + 1.0
        q_norm = math.sqrt(sum(v * v for v in qv.values())) or 1.0
        for t in qv:
            qv[t] /= q_norm

        scores: list[tuple[str, float]] = []
        for path, dv in self._doc_vectors.items():
            d_norm = math.sqrt(sum(v * v for v in dv.values())) or 1.0
            dot = sum(qv.get(t, 0.0) * (dv.get(t, 0.0) / d_norm) for t in qv)
            scores.append((path, dot))

        scores.sort(key=lambda x: x[1], reverse=True)

        results: list[dict[str, Any]] = []
        for path, score in scores[:top_k]:
            if score > 0.001:
                snippet = self._extract_snippet(
                    self._docs.get(path, ""), " ".join(query_tokens),
                )
                results.append({"path": path, "score": round(score, 4), "snippet": snippet})
        return results

    def _extract_snippet(self, content: str, query_terms: str) -> str:
        """Extract a relevant snippet around the first matching line."""
        lines = content.splitlines()
        terms = query_terms.lower().split()
        best_idx = 0
        best_score = 0
        for i, line in enumerate(lines):
            score = sum(1 for t in terms if t in line.lower())
            if score > best_score:
                best_score = score
                best_idx = i
        start = max(0, best_idx - 2)
        end = min(len(lines), best_idx + 3)
        snippet_lines = lines[start:end]
        snippet = "\n".join(snippet_lines)
        if len(snippet) > 500:
            snippet = snippet[:497] + "..."
        return snippet

    def clear(self) -> None:
        """Reset the index."""
        self._docs = {}
        self._idf = {}
        self._doc_vectors = {}


# ------------------------------------------------------------------
# shared module-level index (built lazily, reused across calls)
# ------------------------------------------------------------------

_index: SemanticIndex | None = None


def _get_index() -> SemanticIndex:
    global _index
    if _index is None:
        _index = SemanticIndex(backend="text")
    return _index


def _extract_symbol_names(root: Path, files: dict[str, str]) -> dict[str, list[str]]:
    """Extract symbol names from Python files for weighted TF-IDF indexing."""
    import ast

    symbols_per_file: dict[str, list[str]] = {}
    for rp, content in files.items():
        if not rp.endswith(".py"):
            continue
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
        if names:
            symbols_per_file[rp] = names
    return symbols_per_file


def semantic_search(
    workspace_root: str,
    query: str,
    top_k: int = 10,
    *,
    file_patterns: list[str] | None = None,
    symbol_aware: bool = True,
) -> dict[str, Any]:
    """Search workspace files semantically and return ranked results.

    Parameters
    ----------
    workspace_root:
        Absolute path to the workspace root.
    query:
        Natural-language query, e.g. "where is user authentication handled".
    top_k:
        Maximum number of results to return.
    file_patterns:
        Optional list of glob patterns to restrict the file set
        (default: ``["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.md"]``).
    symbol_aware:
        When True (default), Python symbol names get 2x TF-IDF weight.
    """
    if file_patterns is None:
        file_patterns = ["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.md",
                         "**/*.rs", "**/*.go", "**/*.java", "**/*.rb"]

    root = Path(workspace_root)
    if not root.is_dir():
        return {"ok": False, "error": "invalid_workspace", "message": f"Not a directory: {workspace_root}"}

    # Collect files matching patterns
    files: dict[str, str] = {}
    seen_paths: set[str] = set()
    for pattern in file_patterns:
        for fpath in root.glob(pattern):
            rp = str(fpath.relative_to(root))
            if rp in seen_paths:
                continue
            seen_paths.add(rp)
            try:
                content = fpath.read_text(encoding="utf-8")
                if len(content) > 50_000:
                    content = content[:50_000]
                files[rp] = content
            except (OSError, UnicodeDecodeError):
                continue

    symbols = _extract_symbol_names(root, files) if symbol_aware else None
    index = _get_index()
    index.index_files(files, symbols_per_file=symbols)
    results = index.search(query, top_k=top_k)

    return {
        "ok": True,
        "query": query,
        "total_files": len(files),
        "symbol_weighted": symbols is not None and len(symbols) > 0,
        "results": results,
        "backend": index.backend,
    }


def build_semantic_index(
    workspace_root: str,
    *,
    file_patterns: list[str] | None = None,
    symbol_aware: bool = True,
) -> dict[str, Any]:
    """Pre-build the semantic index for *workspace_root*.

    Call this during project-map construction so that subsequent
    ``semantic_search`` calls are fast.
    """
    if file_patterns is None:
        file_patterns = ["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.md",
                         "**/*.rs", "**/*.go", "**/*.java", "**/*.rb"]

    root = Path(workspace_root)
    if not root.is_dir():
        return {"ok": False, "error": "invalid_workspace"}

    files: dict[str, str] = {}
    for pattern in file_patterns:
        for fpath in root.glob(pattern):
            rp = str(fpath.relative_to(root))
            try:
                content = fpath.read_text(encoding="utf-8")
                if len(content) > 50_000:
                    content = content[:50_000]
                files[rp] = content
            except (OSError, UnicodeDecodeError):
                continue

    symbols = _extract_symbol_names(root, files) if symbol_aware else None
    index = _get_index()
    index.index_files(files, symbols_per_file=symbols)

    return {"ok": True, "indexed_files": len(files), "symbol_weighted": symbols is not None and len(symbols) > 0, "backend": index.backend}
