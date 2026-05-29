"""Project context discovery helpers."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from hermes_lite.coding.workspace import Workspace

EXTENSION_LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".md": "Markdown",
    ".json": "JSON",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".css": "CSS",
    ".html": "HTML",
}


def list_files(
    workspace: Workspace,
    pattern: str = "**/*",
    limit: int = 200,
) -> dict[str, object]:
    """List non-protected files in the workspace."""
    files: list[str] = []
    for path in sorted(workspace.root.glob(pattern)):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace.root).as_posix()
        protected, _reason = workspace.is_protected_path(relative, operation="read")
        if protected:
            continue
        files.append(relative)
        if len(files) >= limit:
            break
    return {"ok": True, "files": files, "count": len(files), "truncated": len(files) >= limit}


def search_text(
    workspace: Workspace,
    query: str,
    path: str = ".",
    limit: int = 100,
    max_file_bytes: int = 1_000_000,
) -> dict[str, object]:
    """Search text files for a literal query."""
    check = workspace.resolve(path, operation="read")
    if not check.ok:
        return check.to_dict()
    if not query:
        return {"ok": False, "error": "empty_query", "matches": []}

    candidates = [check.path] if check.path.is_file() else sorted(check.path.rglob("*"))
    matches: list[dict[str, object]] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(workspace.root).as_posix()
        protected, _reason = workspace.is_protected_path(relative, operation="read")
        if protected:
            continue
        try:
            if candidate.stat().st_size > max_file_bytes:
                continue
            raw = candidate.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                matches.append({"path": relative, "line_number": line_number, "line": line})
                if len(matches) >= limit:
                    return {"ok": True, "query": query, "matches": matches, "truncated": True}
    return {"ok": True, "query": query, "matches": matches, "truncated": False}


def build_project_map(workspace: Workspace, limit: int = 2000) -> dict[str, object]:
    """Build a compact map of repository files and languages."""
    listed = list_files(workspace, limit=limit)
    files = list(listed["files"])
    language_counts: Counter[str] = Counter()
    top_level: set[str] = set()
    test_dirs: set[str] = set()
    important_files: list[str] = []

    for rel in files:
        path = Path(rel)
        if path.parts:
            top_level.add(path.parts[0])
        if any(part in {"test", "tests", "spec", "specs"} for part in path.parts):
            test_dirs.add(path.parts[0])
        language = EXTENSION_LANGUAGES.get(path.suffix.lower())
        if language:
            language_counts[language] += 1
        if path.name in {"README.md", "pyproject.toml", "package.json", "Cargo.toml", "go.mod"}:
            important_files.append(rel)

    return {
        "ok": True,
        "root": str(workspace.root),
        "file_count": len(files),
        "languages": dict(language_counts),
        "top_level": sorted(top_level),
        "test_dirs": sorted(test_dirs),
        "important_files": sorted(important_files),
        "truncated": bool(listed["truncated"]),
    }


def rank_files(workspace: Workspace, query: str, limit: int = 20) -> dict[str, object]:
    """Rank files by simple query relevance."""
    query_lower = query.lower()
    files = list_files(workspace, limit=2000)["files"]
    ranked: list[dict[str, object]] = []
    for rel in files:
        path = Path(rel)
        score = 0
        lower = rel.lower()
        if query_lower and query_lower in path.name.lower():
            score += 100
        if query_lower and query_lower in lower:
            score += 50
        if path.suffix in {".py", ".ts", ".tsx", ".js", ".jsx"}:
            score += 5
        if score > 0:
            ranked.append({"path": rel, "score": score})
    ranked.sort(key=lambda item: (-int(item["score"]), str(item["path"])))
    return {"ok": True, "query": query, "files": ranked[:limit]}
