"""Workspace boundary and path-safety helpers for coding agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Operation = Literal["read", "write", "execute"]


@dataclass(frozen=True)
class PathCheck:
    """Result of resolving a path against a workspace boundary."""

    ok: bool
    path: Path
    relative_path: str
    operation: str
    error: str = ""
    protected: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation."""
        return {
            "ok": self.ok,
            "path": str(self.path),
            "relative_path": self.relative_path,
            "operation": self.operation,
            "error": self.error,
            "protected": self.protected,
            "reason": self.reason,
        }


class Workspace:
    """A repository or project root with central path rules."""

    protected_names = {
        ".git",
        ".venv",
        "node_modules",
        ".pytest_cache",
        "__pycache__",
    }
    secret_names = {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "known_hosts",
    }
    secret_suffixes = (".pem", ".key", ".p12", ".pfx")

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def resolve(self, path: str | Path, operation: Operation = "read") -> PathCheck:
        """Resolve a user path and reject paths outside or protected by the workspace."""
        raw = Path(path).expanduser()
        target = raw.resolve(strict=False) if raw.is_absolute() else (self.root / raw).resolve(strict=False)

        try:
            relative = target.relative_to(self.root)
        except ValueError:
            return PathCheck(
                ok=False,
                path=target,
                relative_path="",
                operation=operation,
                error="outside_workspace",
                reason="Path resolves outside the workspace root.",
            )

        relative_path = relative.as_posix() if relative.as_posix() != "." else "."
        protected, reason = self.is_protected_path(relative_path, operation=operation)
        if protected:
            return PathCheck(
                ok=False,
                path=target,
                relative_path=relative_path,
                operation=operation,
                error="protected_path",
                protected=True,
                reason=reason,
            )

        return PathCheck(
            ok=True,
            path=target,
            relative_path=relative_path,
            operation=operation,
        )

    def is_protected_path(
        self,
        relative_path: str | Path,
        operation: Operation = "write",
    ) -> tuple[bool, str]:
        """Return whether a workspace-relative path is protected."""
        parts = [part for part in str(relative_path).replace("\\", "/").split("/") if part and part != "."]
        if not parts:
            return False, ""

        name = parts[-1]
        if name == ".env" or name.startswith(".env."):
            return True, "secret_file"
        if name in self.secret_names or name.endswith(self.secret_suffixes):
            return True, "secret_file"
        if any(part in self.protected_names for part in parts):
            return True, "protected_directory"
        if operation == "write" and name.startswith(".") and name not in {".hermes"}:
            return True, "hidden_file"
        return False, ""

    def read_text(self, path: str | Path) -> dict[str, object]:
        """Read a text file within the workspace."""
        check = self.resolve(path, operation="read")
        if not check.ok:
            return check.to_dict()
        if not check.path.exists():
            data = check.to_dict()
            data.update({"ok": False, "error": "file_not_found"})
            return data
        if check.path.is_dir():
            data = check.to_dict()
            data.update({"ok": False, "error": "is_directory"})
            return data
        try:
            content = check.path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            data = check.to_dict()
            data.update({"ok": False, "error": "read_failed", "message": str(exc)})
            return data
        return {
            "ok": True,
            "path": str(check.path),
            "relative_path": check.relative_path,
            "content": content,
            "bytes": len(content.encode("utf-8")),
        }

    def write_text(self, path: str | Path, content: str) -> dict[str, object]:
        """Write a text file within the workspace."""
        check = self.resolve(path, operation="write")
        if not check.ok:
            return check.to_dict()
        try:
            check.path.parent.mkdir(parents=True, exist_ok=True)
            check.path.write_text(content, encoding="utf-8")
        except OSError as exc:
            data = check.to_dict()
            data.update({"ok": False, "error": "write_failed", "message": str(exc)})
            return data
        return {
            "ok": True,
            "path": str(check.path),
            "relative_path": check.relative_path,
            "bytes": len(content.encode("utf-8")),
        }

    def list_dir(self, path: str | Path = ".") -> dict[str, object]:
        """List immediate entries inside a directory, excluding protected paths."""
        check = self.resolve(path, operation="read")
        if not check.ok:
            return check.to_dict()
        if not check.path.exists():
            data = check.to_dict()
            data.update({"ok": False, "error": "directory_not_found"})
            return data
        if not check.path.is_dir():
            data = check.to_dict()
            data.update({"ok": False, "error": "not_directory"})
            return data

        entries: list[dict[str, object]] = []
        for child in sorted(check.path.iterdir(), key=lambda item: item.name):
            rel = child.relative_to(self.root).as_posix()
            protected, _reason = self.is_protected_path(rel, operation="read")
            if protected:
                continue
            entries.append({"path": rel, "is_dir": child.is_dir()})
        return {"ok": True, "path": str(check.path), "entries": entries}

    def summary(self) -> dict[str, object]:
        """Return a compact workspace summary."""
        return {
            "ok": True,
            "root": str(self.root),
            "exists": self.root.exists(),
            "is_git_repo": (self.root / ".git").exists(),
            "protected_names": sorted(self.protected_names),
            "secret_suffixes": list(self.secret_suffixes),
        }
