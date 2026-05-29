"""LSP (Language Server Protocol) client over stdio.

Supports pyright, pylsp, and tsserver.  Gracefully degrades when no LSP
server is installed — every public function returns structured metadata
including an ``available`` flag.

Clean-room implementation: JSON-RPC 2.0, no OpenCode code referenced.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# LSP servers we can discover
# ---------------------------------------------------------------------------

LSP_SERVER_CANDIDATES: list[dict[str, Any]] = [
    {
        "name": "pyright",
        "languages": ["python"],
        "commands": [
            ["pyright-langserver", "--stdio"],
            ["pyright", "--stdio"],
            ["npx", "pyright", "--stdio"],
        ],
    },
    {
        "name": "pylsp",
        "languages": ["python"],
        "commands": [
            ["pylsp"],
        ],
    },
    {
        "name": "tsserver",
        "languages": ["typescript", "javascript", "tsx", "jsx"],
        "commands": [
            ["typescript-language-server", "--stdio"],
            ["npx", "typescript-language-server", "--stdio"],
        ],
    },
]


def _find_executable(candidates: list[list[str]]) -> str | None:
    """Return the first candidate whose initial command is on PATH."""
    for cmd in candidates:
        if shutil.which(cmd[0]):
            return cmd[0]
    return None


@dataclass
class LspAvailable:
    name: str
    languages: list[str]
    executable: str


def discover_lsp_servers() -> list[LspAvailable]:
    """Return LSP servers that are installed and usable."""
    result: list[LspAvailable] = []
    for candidate in LSP_SERVER_CANDIDATES:
        exe = _find_executable(candidate["commands"])
        if exe:
            result.append(LspAvailable(
                name=candidate["name"],
                languages=candidate["languages"],
                executable=exe,
            ))
    return result


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 helpers
# ---------------------------------------------------------------------------


def _build_request(method: str, params: Any = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex[:8],
        "method": method,
        "params": params or {},
    }


def _build_notification(method: str, params: Any = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
    }


# ---------------------------------------------------------------------------
# LspClient
# ---------------------------------------------------------------------------


@dataclass
class LspClient:
    """A single LSP server connection.

    Usage::

        client = LspClient.start(root_uri, "pyright")
        try:
            diags = client.diagnostics(file_uri)
        finally:
            client.shutdown()
    """

    process: subprocess.Popen[bytes]
    name: str
    root_uri: str
    languages: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _initialized: bool = False
    _server_capabilities: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def start(
        cls,
        root_uri: str,
        server_name: str,
        *,
        timeout: float = 10.0,
    ) -> LspClient | None:
        """Start an LSP server and perform the initialize handshake."""
        candidates = [c for c in LSP_SERVER_CANDIDATES if c["name"] == server_name]
        if not candidates:
            return None
        exe = _find_executable(candidates[0]["commands"])
        if not exe:
            return None

        cmd = [exe]
        for opt in candidates[0]["commands"]:
            if opt[0] == exe:
                cmd = opt
                break

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            return None

        client = cls(
            process=proc,
            name=server_name,
            root_uri=root_uri,
            languages=candidates[0]["languages"],
        )

        init_params = {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "capabilities": {
                "textDocument": {
                    "diagnostic": {"dynamicRegistration": True},
                    "definition": {"dynamicRegistration": True},
                    "references": {"dynamicRegistration": True},
                    "documentSymbol": {"dynamicRegistration": True},
                    "hover": {"dynamicRegistration": True},
                },
            },
        }
        resp = client._send_request("initialize", init_params, timeout=timeout)
        if resp is None:
            client._kill()
            return None

        client._server_capabilities = resp.get("capabilities", {})
        client._initialized = True
        client._send_notification("initialized", {})
        return client

    # -- public tool-facing methods ------------------------------------------

    def diagnostics(self, file_uri: str, *, timeout: float = 10.0) -> dict[str, object]:
        """Get diagnostics for a file.  Returns immediately (pull model)."""
        if not self._initialized:
            return {"ok": False, "error": "not_initialized", "available": True, "server": self.name}

        self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": file_uri,
                "languageId": self._language_id(file_uri),
                "version": 1,
                "text": self._read_file(file_uri),
            },
        })

        # Request diagnostics
        result = self._send_request("textDocument/diagnostic", {
            "textDocument": {"uri": file_uri},
        }, timeout=timeout)

        self._send_notification("textDocument/didClose", {
            "textDocument": {"uri": file_uri},
        })

        if result is None:
            return {"ok": True, "available": True, "server": self.name, "diagnostics": [], "message": "No diagnostics returned."}

        items = result.get("items", [])
        diags = []
        for item in items:
            rng = item.get("range", {})
            start = rng.get("start", {})
            diags.append({
                "line": start.get("line", 0) + 1,
                "column": start.get("character", 0) + 1,
                "severity": _severity_name(item.get("severity", 2)),
                "message": item.get("message", ""),
                "code": item.get("code", ""),
            })
        return {"ok": True, "available": True, "server": self.name, "diagnostics": diags, "count": len(diags)}

    def definition(
        self, file_uri: str, line: int, column: int, *, timeout: float = 10.0,
    ) -> dict[str, object]:
        """Get the definition location of a symbol."""
        if not self._initialized:
            return {"ok": False, "error": "not_initialized"}

        self._ensure_open(file_uri)
        result = self._send_request("textDocument/definition", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line - 1, "character": max(column - 1, 0)},
        }, timeout=timeout)

        return self._format_locations(result)

    def references(
        self, file_uri: str, line: int, column: int, *, timeout: float = 10.0,
    ) -> dict[str, object]:
        """Find references of a symbol."""
        if not self._initialized:
            return {"ok": False, "error": "not_initialized"}

        self._ensure_open(file_uri)
        result = self._send_request("textDocument/references", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line - 1, "character": max(column - 1, 0)},
            "context": {"includeDeclaration": False},
        }, timeout=timeout)

        return self._format_locations(result)

    def symbols(self, file_uri: str, *, timeout: float = 10.0) -> dict[str, object]:
        """Get document symbols (outline)."""
        if not self._initialized:
            return {"ok": False, "error": "not_initialized"}

        self._ensure_open(file_uri)
        result = self._send_request("textDocument/documentSymbol", {
            "textDocument": {"uri": file_uri},
        }, timeout=timeout)

        if result is None:
            return {"ok": True, "available": True, "server": self.name, "symbols": []}
        if isinstance(result, list):
            syms = result
        elif isinstance(result, dict):
            syms = result.get("symbols", result.get("result", []))
        else:
            syms = []

        formatted = []
        for s in syms:
            if isinstance(s, dict):
                rng = s.get("range", {}).get("start", s.get("location", {}).get("range", {}).get("start", {}))
                formatted.append({
                    "name": s.get("name", ""),
                    "kind": _symbol_kind(s.get("kind", 0)),
                    "line": rng.get("line", 0) + 1,
                    "column": rng.get("character", 0) + 1,
                })
        return {"ok": True, "available": True, "server": self.name, "symbols": formatted, "count": len(formatted)}

    def hover(
        self, file_uri: str, line: int, column: int, *, timeout: float = 10.0,
    ) -> dict[str, object]:
        """Get hover information for a symbol."""
        if not self._initialized:
            return {"ok": False, "error": "not_initialized"}

        self._ensure_open(file_uri)
        result = self._send_request("textDocument/hover", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line - 1, "character": max(column - 1, 0)},
        }, timeout=timeout)

        if result is None:
            return {"ok": True, "available": True, "server": self.name, "contents": None}
        contents = result.get("contents", {})
        if isinstance(contents, dict):
            text = contents.get("value", str(contents))
        elif isinstance(contents, list):
            text = " ".join(
                c.get("value", str(c)) if isinstance(c, dict) else str(c)
                for c in contents
            )
        else:
            text = str(contents)
        return {"ok": True, "available": True, "server": self.name, "hover": text}

    def shutdown(self) -> None:
        """Send shutdown + exit and wait for server termination."""
        if not self._initialized:
            self._kill()
            return
        try:
            self._send_request("shutdown", timeout=3)
            self._send_notification("exit")
        except Exception:
            pass
        try:
            self.process.wait(timeout=3)
        except Exception:
            self._kill()

    # -- internal ------------------------------------------------------------

    def _kill(self) -> None:
        try:
            self.process.kill()
            self.process.wait(timeout=2)
        except Exception:
            pass

    def _send_request(self, method: str, params: Any = None, *, timeout: float = 10.0) -> Any:
        req = _build_request(method, params)
        return self._rpc(req, timeout=timeout)

    def _send_notification(self, method: str, params: Any = None) -> None:
        notif = _build_notification(method, params)
        self._write(notif)

    def _rpc(self, message: dict[str, Any], *, timeout: float = 10.0) -> Any:
        with self._lock:
            self._write(message)
            return self._read_response(message["id"], timeout=timeout)

    def _write(self, message: dict[str, Any]) -> None:
        body = json.dumps(message, ensure_ascii=False)
        header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
        try:
            self.process.stdin.write((header + body).encode("utf-8"))  # type: ignore[union-attr]
            self.process.stdin.flush()  # type: ignore[union-attr]
        except Exception:
            pass

    def _read_response(self, request_id: str, timeout: float) -> Any:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            try:
                header = b""
                while not header.endswith(b"\r\n\r\n"):
                    ch = self.process.stdout.read(1)  # type: ignore[union-attr]
                    if not ch:
                        return None
                    header += ch
                content_length = 0
                for line in header.decode("utf-8").splitlines():
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":", 1)[1].strip())
                if content_length <= 0:
                    return None
                body = self.process.stdout.read(content_length)  # type: ignore[union-attr]
                msg = json.loads(body)
                if msg.get("id") == request_id:
                    if "error" in msg:
                        return None
                    return msg.get("result")
            except Exception:
                return None
        return None

    def _ensure_open(self, file_uri: str) -> None:
        self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": file_uri,
                "languageId": self._language_id(file_uri),
                "version": 1,
                "text": self._read_file(file_uri),
            },
        })

    def _language_id(self, file_uri: str) -> str:
        ext = Path(file_uri).suffix.lower()
        mapping = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescriptreact",
            ".js": "javascript",
            ".jsx": "javascriptreact",
            ".json": "json",
            ".md": "markdown",
            ".css": "css",
            ".html": "html",
        }
        return mapping.get(ext, "plaintext")

    def _read_file(self, file_uri: str) -> str:
        path = file_uri.replace("file://", "")
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def _format_locations(self, result: Any) -> dict[str, object]:
        if result is None:
            return {"ok": True, "locations": [], "count": 0}
        locs = result if isinstance(result, list) else [result] if isinstance(result, dict) else []
        items = []
        for loc in locs:
            if not isinstance(loc, dict):
                continue
            uri = loc.get("uri", "")
            rng = loc.get("range", {})
            start = rng.get("start", {})
            items.append({
                "uri": uri,
                "path": uri.replace("file://", ""),
                "line": start.get("line", 0) + 1,
                "column": start.get("character", 0) + 1,
            })
        return {"ok": True, "locations": items, "count": len(items)}


# ---------------------------------------------------------------------------
# public tool-facing API (stateless, with graceful fallback)
# ---------------------------------------------------------------------------


_lsp_pool: dict[str, LspClient] = {}


def _get_client(root_path: str, language: str) -> LspClient | None:
    root_uri = f"file://{Path(root_path).resolve()}"
    key = f"{root_uri}:{language}"
    if key in _lsp_pool:
        client = _lsp_pool[key]
        if client._initialized:
            return client
        else:
            del _lsp_pool[key]

    wanted = "pyright" if language == "python" else "tsserver"
    # Also try pylsp for python
    available = discover_lsp_servers()
    names = {s.name for s in available}
    for candidate_name in [wanted, "pylsp" if language == "python" else wanted]:
        if candidate_name in names:
            client = LspClient.start(root_uri, candidate_name)
            if client:
                _lsp_pool[key] = client
                return client
    return None


def _unavailable(operation: str) -> dict[str, object]:
    return {
        "ok": True,
        "available": False,
        "operation": operation,
        "message": "No LSP server found. Install pyright, pylsp, or typescript-language-server.",
    }


def lsp_diagnostics(workspace_root: str, path: str, language: str = "python") -> dict[str, object]:
    """Get LSP diagnostics for a file, with fallback."""
    client = _get_client(workspace_root, language)
    if client is None:
        return _unavailable("diagnostics")
    file_uri = f"file://{(Path(workspace_root) / path).resolve()}"
    return client.diagnostics(file_uri)


def lsp_definition(workspace_root: str, path: str, line: int, column: int, language: str = "python") -> dict[str, object]:
    """Go to definition."""
    client = _get_client(workspace_root, language)
    if client is None:
        return _unavailable("definition")
    file_uri = f"file://{(Path(workspace_root) / path).resolve()}"
    return client.definition(file_uri, line, column)


def lsp_references(workspace_root: str, path: str, line: int, column: int, language: str = "python") -> dict[str, object]:
    """Find references."""
    client = _get_client(workspace_root, language)
    if client is None:
        return _unavailable("references")
    file_uri = f"file://{(Path(workspace_root) / path).resolve()}"
    return client.references(file_uri, line, column)


def lsp_symbols(workspace_root: str, path: str, language: str = "python") -> dict[str, object]:
    """Get document symbols via LSP."""
    client = _get_client(workspace_root, language)
    if client is None:
        return _unavailable("symbols")
    file_uri = f"file://{(Path(workspace_root) / path).resolve()}"
    return client.symbols(file_uri)


def lsp_hover(workspace_root: str, path: str, line: int, column: int, language: str = "python") -> dict[str, object]:
    """Get hover info via LSP."""
    client = _get_client(workspace_root, language)
    if client is None:
        return _unavailable("hover")
    file_uri = f"file://{(Path(workspace_root) / path).resolve()}"
    return client.hover(file_uri, line, column)


def lsp_status() -> dict[str, object]:
    """Return which LSP servers are available."""
    available = discover_lsp_servers()
    return {
        "ok": True,
        "available_servers": [
            {"name": s.name, "languages": s.languages, "executable": s.executable}
            for s in available
        ],
        "active_sessions": len(_lsp_pool),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _severity_name(severity: int) -> str:
    return {1: "error", 2: "warning", 3: "information", 4: "hint"}.get(severity, "warning")


def _symbol_kind(kind: int) -> str:
    return {
        1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class",
        6: "method", 7: "property", 8: "field", 9: "constructor", 10: "enum",
        11: "interface", 12: "function", 13: "variable", 14: "constant",
        15: "string", 16: "number", 17: "boolean", 18: "array",
    }.get(kind, "unknown")
