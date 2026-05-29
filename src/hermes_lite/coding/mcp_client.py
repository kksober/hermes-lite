"""MCP (Model Context Protocol) stdio client.

Launches MCP servers defined in ``.hermes/mcp.json``, performs the
initialize handshake, and exposes ``list_tools`` / ``call_tool``.

Every interaction is bounded by timeout and subject to permission checks
in the tool layer.  Clean-room implementation — no OpenCode code referenced.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from hermes_lite.coding.extensibility import load_mcp_servers
from hermes_lite.coding.workspace import Workspace


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _jsonrpc_request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex[:8],
        "method": method,
        "params": params or {},
    }


# ---------------------------------------------------------------------------
# McpServerConnection
# ---------------------------------------------------------------------------


@dataclass
class McpServerConnection:
    """A single connected MCP server process."""

    name: str
    command: str
    process: subprocess.Popen[bytes]
    server_info: dict[str, Any] = field(default_factory=dict)
    server_capabilities: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    initialized: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def start(
        cls,
        name: str,
        command: str,
        args: list[str],
        *,
        timeout: float = 10.0,
    ) -> McpServerConnection | None:
        """Start an MCP server and complete the initialize handshake."""
        try:
            parsed = shlex.split(command)
        except ValueError:
            return None
        full_cmd = parsed + list(args)

        try:
            proc = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            return None

        conn = cls(name=name, command=" ".join(full_cmd), process=proc)

        init_result = conn._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "hermes-lite", "version": "0.1.0"},
        }, timeout=timeout)

        if init_result is None:
            conn.shutdown()
            return None

        conn.server_info = init_result.get("serverInfo", {})
        conn.server_capabilities = init_result.get("capabilities", {})
        conn.initialized = True

        conn._send_notification("notifications/initialized", {})
        return conn

    def list_tools(self, *, timeout: float = 10.0) -> dict[str, object]:
        """Fetch the tool list from the MCP server."""
        if not self.initialized:
            return {"ok": False, "error": "not_initialized", "server": self.name}

        result = self._rpc("tools/list", {}, timeout=timeout)
        if result is None:
            return {"ok": False, "error": "rpc_failed", "server": self.name}

        tools = result.get("tools", [])
        self.tools = tools
        return {
            "ok": True,
            "server": self.name,
            "tools": [
                {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema", {}),
                }
                for t in tools
            ],
            "count": len(tools),
        }

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, object]:
        """Call a tool on the MCP server."""
        if not self.initialized:
            return {"ok": False, "error": "not_initialized", "server": self.name}

        result = self._rpc("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        }, timeout=timeout)

        if result is None:
            return {"ok": False, "error": "rpc_failed", "server": self.name, "tool": tool_name}

        return {
            "ok": True,
            "server": self.name,
            "tool": tool_name,
            "content": result.get("content", []),
            "isError": result.get("isError", False),
        }

    def shutdown(self) -> None:
        """Terminate the MCP server process."""
        try:
            self.process.stdin.close()  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            self.process.wait(timeout=3)
        except Exception:
            try:
                self.process.kill()
                self.process.wait(timeout=2)
            except Exception:
                pass

    # -- internal ------------------------------------------------------------

    def _rpc(self, method: str, params: dict[str, Any], *, timeout: float = 10.0) -> Any:
        with self._lock:
            req = _jsonrpc_request(method, params)
            self._write(req)
            return self._read_response(req["id"], timeout=timeout)

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        notif = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self._write(notif)

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


# ---------------------------------------------------------------------------
# McpClientManager — manages multiple MCP servers
# ---------------------------------------------------------------------------


@dataclass
class McpClientManager:
    """Manages lifecycle for multiple MCP server connections."""

    workspace: Workspace
    connections: dict[str, McpServerConnection] = field(default_factory=dict)

    def connect_all(self, *, timeout: float = 10.0) -> dict[str, object]:
        """Start all MCP servers declared in ``.hermes/mcp.json``."""
        config = load_mcp_servers(self.workspace)
        servers = config.get("servers", [])
        if not isinstance(servers, list):
            return {"ok": True, "connected": 0, "total": 0, "details": []}

        details = []
        connected = 0
        for server_def in servers:
            name = server_def.get("name", "")
            if not name or not server_def.get("enabled", True):
                continue
            command = server_def.get("command", "")
            args = server_def.get("args", [])
            if not command:
                continue

            conn = McpServerConnection.start(name, command, args, timeout=timeout)
            if conn:
                self.connections[name] = conn
                connected += 1
                details.append({"name": name, "status": "connected", "command": command})
            else:
                details.append({"name": name, "status": "failed", "command": command})

        return {"ok": True, "connected": connected, "total": len(details), "details": details}

    def list_all_tools(self) -> dict[str, object]:
        """List tools from all connected MCP servers."""
        all_tools: list[dict[str, Any]] = []
        for name, conn in self.connections.items():
            result = conn.list_tools()
            if result["ok"]:
                for tool in result.get("tools", []):
                    tool["_server"] = name
                    all_tools.append(tool)
        return {"ok": True, "tools": all_tools, "count": len(all_tools)}

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, object]:
        """Call a tool on a specific MCP server."""
        conn = self.connections.get(server_name)
        if conn is None:
            return {"ok": False, "error": "server_not_found", "server": server_name}
        return conn.call_tool(tool_name, arguments, timeout=timeout)

    def shutdown_all(self) -> None:
        """Shut down all MCP connections."""
        for conn in list(self.connections.values()):
            conn.shutdown()
        self.connections.clear()

    def status(self) -> dict[str, object]:
        """Return connection status."""
        return {
            "ok": True,
            "servers": [
                {
                    "name": name,
                    "command": conn.command,
                    "info": conn.server_info,
                    "tool_count": len(conn.tools),
                }
                for name, conn in self.connections.items()
            ],
        }
