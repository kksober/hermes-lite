"""Project context discovery with ripgrep acceleration and smart indexing.

Falls back gracefully to pure-Python search when ``rg`` is not installed.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

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
    ".sql": "SQL",
    ".sh": "Shell",
    ".Dockerfile": "Dockerfile",
}

TEST_FILE_PATTERNS = [
    "test_{name}",
    "{name}_test",
    "test{name}",
    "{name}Test",
    "test_{name}.py",
    "test_{name}.ts",
]


def _has_rg() -> bool:
    """Check whether ripgrep is available on ``$PATH``."""
    try:
        subprocess.run(
            ["rg", "--version"],
            capture_output=True,
            timeout=2,
        )
        return True
    except Exception:
        return False


def _rg_files(workspace: Workspace, pattern: str = "", limit: int = 2000) -> list[str]:
    """Use ``rg --files`` for fast file enumeration."""
    args = ["rg", "--files", "--hidden"]
    if pattern:
        args.extend(["--glob", pattern])
    try:
        proc = subprocess.run(
            args,
            cwd=workspace.root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return []

    files: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        protected, _ = workspace.is_protected_path(line, operation="read")
        if protected:
            continue
        files.append(line)
        if len(files) >= limit:
            break
    return files


def _rg_search(
    workspace: Workspace,
    query: str,
    *,
    path: str = ".",
    limit: int = 100,
    case_sensitive: bool = True,
    file_pattern: str = "",
) -> list[dict[str, Any]]:
    """Use ``rg --json`` for structured search results."""
    args = [
        "rg", "--json", "--no-heading",
        "--line-number", "--color", "never",
    ]
    if not case_sensitive:
        args.append("--ignore-case")
    if file_pattern:
        args.extend(["--glob", file_pattern])
    args.append(query)

    search_dir = workspace.root / path if path != "." else workspace.root
    if search_dir.is_file():
        args.append(str(search_dir))
    else:
        args.append(str(search_dir))

    matches: list[dict[str, Any]] = []
    try:
        proc = subprocess.run(
            args,
            cwd=workspace.root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return matches

    for line in proc.stdout.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "match":
            continue
        data = entry.get("data", {})
        file_path = data.get("path", {}).get("text", "")
        relative = _relative_path(workspace, file_path)
        if not relative:
            continue
        protected, _ = workspace.is_protected_path(relative, operation="read")
        if protected:
            continue
        line_number = data.get("line_number", 0)
        line_text = data.get("lines", {}).get("text", "").rstrip("\n")
        matches.append({
            "path": relative,
            "line_number": line_number,
            "line": line_text,
        })
        if len(matches) >= limit:
            break
    return matches


def _relative_path(workspace: Workspace, abs_path: str) -> str | None:
    """Convert an absolute path to workspace-relative, or None if outside."""
    if not abs_path:
        return None
    try:
        return str(Path(abs_path).relative_to(workspace.root))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def list_files(
    workspace: Workspace,
    pattern: str = "**/*",
    limit: int = 200,
) -> dict[str, object]:
    """List non-protected files in the workspace.

    Uses ``rg --files`` when available (much faster for large repos).
    """
    use_rg = _has_rg()

    if use_rg and pattern in ("**/*", "*"):
        rg_files = _rg_files(workspace, pattern="", limit=limit)
        if rg_files:
            return {
                "ok": True,
                "files": rg_files,
                "count": len(rg_files),
                "truncated": len(rg_files) >= limit,
                "method": "ripgrep",
            }

    # Pure-Python fallback
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
    return {
        "ok": True,
        "files": files,
        "count": len(files),
        "truncated": len(files) >= limit,
        "method": "glob",
    }


def search_text(
    workspace: Workspace,
    query: str,
    path: str = ".",
    limit: int = 100,
    max_file_bytes: int = 1_000_000,
) -> dict[str, object]:
    """Search workspace text files for a literal query.

    Uses ``rg --json`` when available; falls back to Python string scan.
    """
    if not query:
        return {"ok": False, "error": "empty_query", "matches": []}

    if _has_rg():
        rg_matches = _rg_search(workspace, query, path=path, limit=limit)
        if rg_matches or True:  # rg is authoritative even for zero results
            return {
                "ok": True,
                "query": query,
                "matches": rg_matches,
                "truncated": len(rg_matches) >= limit,
                "method": "ripgrep",
            }

    # Pure-Python fallback
    check = workspace.resolve(path, operation="read")
    if not check.ok:
        return check.to_dict()

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
                    return {
                        "ok": True, "query": query, "matches": matches,
                        "truncated": True, "method": "python",
                    }
    return {
        "ok": True, "query": query, "matches": matches,
        "truncated": False, "method": "python",
    }


def build_project_map(
    workspace: Workspace,
    limit: int = 2000,
    *,
    token_budget: int | None = None,
) -> dict[str, object]:
    """Build a compact map of repository structure, languages, and key files.

    If *token_budget* is set, the output is trimmed to fit within roughly
    that number of tokens (1 token ≈ 4 chars for English text).
    """
    listed = list_files(workspace, limit=limit)
    files = list(listed["files"])
    language_counts: Counter[str] = Counter()
    top_level: set[str] = set()
    test_dirs: set[str] = set()
    important_files: list[str] = []

    file_list: list[dict[str, object]] = []

    for rel in files:
        p = Path(rel)
        if p.parts:
            top_level.add(p.parts[0])
        if any(part in {"test", "tests", "spec", "specs"} for part in p.parts):
            test_dirs.add(p.parts[0])
        language = EXTENSION_LANGUAGES.get(p.suffix.lower())
        if language:
            language_counts[language] += 1
        if p.name in {
            "README.md", "pyproject.toml", "package.json",
            "Cargo.toml", "go.mod", "Makefile", "Dockerfile",
        }:
            important_files.append(rel)
        file_list.append({"path": rel, "language": language, "suffix": p.suffix})

    result: dict[str, object] = {
        "ok": True,
        "root": str(workspace.root),
        "file_count": len(files),
        "languages": dict(language_counts),
        "top_level": sorted(top_level),
        "test_dirs": sorted(test_dirs),
        "important_files": sorted(important_files),
        "truncated": bool(listed["truncated"]),
        "method": listed.get("method", "glob"),
    }

    if token_budget is not None:
        result = _trim_to_token_budget(result, token_budget)

    return result


def rank_files(
    workspace: Workspace,
    query: str,
    limit: int = 20,
) -> dict[str, object]:
    """Rank workspace files by query relevance using multi-factor scoring."""
    query_lower = query.lower()
    query_parts = query_lower.replace("_", " ").replace("-", " ").split()
    files = list_files(workspace, limit=5000)["files"]

    ranked: list[dict[str, object]] = []
    for rel in files:
        p = Path(rel)
        score = 0

        # Name match bonuses
        name_lower = p.name.lower()
        if query_lower == name_lower:
            score += 200
        elif query_lower in name_lower:
            score += 100
        elif any(part in name_lower for part in query_parts if len(part) >= 3):
            score += 50

        # Path match bonuses
        path_lower = rel.lower()
        if query_lower in path_lower:
            score += 30
        if any(part in path_lower for part in query_parts if len(part) >= 3):
            score += 15

        # Stem matching (e.g., "agent" matches "agents.py")
        stem = p.stem.lower().rstrip("s")
        if query_lower in stem or stem in query_lower:
            score += 25

        # Source code bonus
        if p.suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}:
            score += 5

        # Test file bonus (rank test files near their source counterparts)
        if "test" in name_lower or "spec" in name_lower:
            score += 3

        if score > 0:
            ranked.append({"path": rel, "score": score})

    ranked.sort(key=lambda item: (-int(item["score"]), str(item["path"])))
    return {"ok": True, "query": query, "files": ranked[:limit], "method": "multi_factor"}


def recent_changes(workspace: Workspace, count: int = 20) -> dict[str, object]:
    """List recently modified files via git log, or filesystem mtime fallback."""
    try:
        proc = subprocess.run(
            [
                "git", "log", "--pretty=format:", "--name-only",
                "--diff-filter=AM", f"-n{count}",
            ],
            cwd=workspace.root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            seen: set[str] = set()
            recent: list[dict[str, object]] = []
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line or line in seen:
                    continue
                seen.add(line)
                p = (workspace.root / line) if line else None
                mtime = p.stat().st_mtime if p and p.exists() else 0.0
                recent.append({"path": line, "mtime": mtime})
                if len(recent) >= count:
                    break
            return {"ok": True, "files": recent, "source": "git"}
    except Exception:
        pass

    # filesystem fallback: most recently modified files
    listing = list_files(workspace, limit=500)
    paths = [(f, (workspace.root / f).stat().st_mtime) for f in listing["files"]]
    paths.sort(key=lambda x: -x[1])
    recent = [{"path": p, "mtime": mtime} for p, mtime in paths[:count]]
    return {"ok": True, "files": recent, "source": "filesystem"}


def find_test_files(
    workspace: Workspace,
    source_path: str,
) -> dict[str, object]:
    """Find test files likely associated with a source file.

    Heuristics:
    - Look in test/ and tests/ directories
    - Match by stem name (foo.py → test_foo.py, foo_test.py)
    - Match by directory mirroring (src/foo/bar.py → tests/foo/test_bar.py)
    """
    source = Path(source_path)
    stem = source.stem
    candidates: list[dict[str, object]] = []
    scored: list[tuple[int, str]] = []

    test_dir_names = {"test", "tests", "spec", "specs", "__tests__", "e2e", "integration"}

    for f in list_files(workspace, limit=5000)["files"]:
        fp = Path(f)
        # Only consider test paths
        if not any(td in fp.parts for td in test_dir_names):
            continue

        score = 0
        f_stem = fp.stem

        # Exact stem match with test prefix/suffix
        if f_stem == f"test_{stem}" or f_stem == f"{stem}_test" or f_stem == f"test{stem}":
            score += 100
        elif stem in f_stem or f_stem in stem:
            score += 40

        # Directory mirroring
        if source.parent.name in f:
            score += 20

        if score > 0:
            scored.append((score, f))

    scored.sort(key=lambda x: -x[0])
    for s, path in scored[:20]:
        fp = Path(path)
        candidates.append({
            "path": path,
            "score": s,
            "language": EXTENSION_LANGUAGES.get(fp.suffix.lower()),
        })

    return {
        "ok": True,
        "source": str(source_path),
        "test_files": candidates,
        "count": len(candidates),
    }


def repo_map_summary(
    workspace: Workspace,
    *,
    token_budget: int = 2000,
    include_recent: bool = True,
) -> dict[str, object]:
    """Token-aware compact repository overview for LLM context windows."""
    pm = build_project_map(workspace, token_budget=token_budget // 2)
    result: dict[str, object] = {
        "ok": True,
        "root": pm["root"],
        "file_count": pm["file_count"],
        "languages": pm["languages"],
        "top_level_dirs": pm["top_level"],
        "important_files": pm.get("important_files", []),
        "test_dirs": pm.get("test_dirs", []),
    }

    if include_recent:
        rc = recent_changes(workspace, count=10)
        result["recent_changes"] = rc["files"][:10]
        result["recent_source"] = rc["source"]

    return result


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _trim_to_token_budget(result: dict[str, object], budget: int) -> dict[str, object]:
    """Truncate string fields to stay within an approximate token budget."""
    result = dict(result)
    current_chars = len(str(result))
    chars_per_token = 4
    budget_chars = budget * chars_per_token

    if current_chars <= budget_chars:
        return result

    # Remove detailed file lists first
    for key in list(result.keys()):
        if key in ("files", "important_files"):
            if isinstance(result[key], list):
                result[key] = result[key][:50]  # type: ignore[index]
        if isinstance(result[key], list) and len(str(result[key])) > budget_chars // 3:
            result[key] = result[key][:10]  # type: ignore[index]

    return result
