"""Tests for LSP client discovery, JSON-RPC, and MCP client."""

from __future__ import annotations


# ---------------------------------------------------------------------------
# LSP discovery
# ---------------------------------------------------------------------------

def test_discover_lsp_servers_returns_list() -> None:
    from hermes_lite.coding.lsp import discover_lsp_servers

    servers = discover_lsp_servers()
    assert isinstance(servers, list)
    # Each server entry has expected shape
    for s in servers:
        assert isinstance(s.name, str)
        assert isinstance(s.languages, list)
        assert isinstance(s.executable, str)


def test_lsp_status_returns_structured_data() -> None:
    from hermes_lite.coding.lsp import lsp_status

    result = lsp_status()
    assert result["ok"] is True
    assert "available_servers" in result
    assert "active_sessions" in result


def test_lsp_diagnostics_unavailable_graceful() -> None:
    from hermes_lite.coding.lsp import lsp_diagnostics

    result = lsp_diagnostics("/tmp/test", "test.py")
    assert result["ok"] is True
    assert result["available"] is False
    assert result["operation"] == "diagnostics"


def test_lsp_definition_unavailable_graceful() -> None:
    from hermes_lite.coding.lsp import lsp_definition

    result = lsp_definition("/tmp/test", "test.py", 1, 1)
    assert result["ok"] is True
    assert result["available"] is False


def test_lsp_references_unavailable_graceful() -> None:
    from hermes_lite.coding.lsp import lsp_references

    result = lsp_references("/tmp/test", "test.py", 1, 1)
    assert result["ok"] is True
    assert result["available"] is False


def test_lsp_symbols_unavailable_graceful() -> None:
    from hermes_lite.coding.lsp import lsp_symbols

    result = lsp_symbols("/tmp/test", "test.py")
    assert result["ok"] is True
    assert result["available"] is False


def test_lsp_hover_unavailable_graceful() -> None:
    from hermes_lite.coding.lsp import lsp_hover

    result = lsp_hover("/tmp/test", "test.py", 1, 1)
    assert result["ok"] is True
    assert result["available"] is False


# ---------------------------------------------------------------------------
# JSON-RPC formatting
# ---------------------------------------------------------------------------

def test_build_request_format() -> None:
    from hermes_lite.coding.lsp import _build_request

    req = _build_request("initialize", {"rootUri": "file:///tmp"})
    assert req["jsonrpc"] == "2.0"
    assert "id" in req
    assert req["method"] == "initialize"
    assert req["params"]["rootUri"] == "file:///tmp"


def test_build_notification_format() -> None:
    from hermes_lite.coding.lsp import _build_notification

    notif = _build_notification("initialized", {})
    assert notif["jsonrpc"] == "2.0"
    assert "id" not in notif
    assert notif["method"] == "initialized"


def test_severity_name_mapping() -> None:
    from hermes_lite.coding.lsp import _severity_name

    assert _severity_name(1) == "error"
    assert _severity_name(2) == "warning"
    assert _severity_name(3) == "information"
    assert _severity_name(4) == "hint"


def test_symbol_kind_mapping() -> None:
    from hermes_lite.coding.lsp import _symbol_kind

    assert _symbol_kind(5) == "class"
    assert _symbol_kind(6) == "method"
    assert _symbol_kind(12) == "function"
    assert _symbol_kind(99) == "unknown"


# ---------------------------------------------------------------------------
# MCP client manager
# ---------------------------------------------------------------------------

def test_mcp_client_manager_status(tmp_path) -> None:
    from hermes_lite.coding.mcp_client import McpClientManager
    from hermes_lite.coding.workspace import Workspace

    mgr = McpClientManager(Workspace(tmp_path))
    result = mgr.status()

    assert result["ok"] is True
    assert result["servers"] == []


def test_mcp_client_manager_connect_no_config(tmp_path) -> None:
    from hermes_lite.coding.mcp_client import McpClientManager
    from hermes_lite.coding.workspace import Workspace

    mgr = McpClientManager(Workspace(tmp_path))
    result = mgr.connect_all()

    assert result["ok"] is True
    assert result["connected"] == 0


def test_mcp_client_manager_list_tools_empty(tmp_path) -> None:
    from hermes_lite.coding.mcp_client import McpClientManager
    from hermes_lite.coding.workspace import Workspace

    mgr = McpClientManager(Workspace(tmp_path))
    result = mgr.list_all_tools()

    assert result["ok"] is True
    assert result["tools"] == []


def test_mcp_client_manager_call_tool_missing(tmp_path) -> None:
    from hermes_lite.coding.mcp_client import McpClientManager
    from hermes_lite.coding.workspace import Workspace

    mgr = McpClientManager(Workspace(tmp_path))
    result = mgr.call_tool("nonexistent", "tool", {})

    assert result["ok"] is False
    assert result["error"] == "server_not_found"


def test_mcp_client_manager_shutdown_all_noop(tmp_path) -> None:
    from hermes_lite.coding.mcp_client import McpClientManager
    from hermes_lite.coding.workspace import Workspace

    mgr = McpClientManager(Workspace(tmp_path))
    mgr.shutdown_all()  # Should not raise
    assert len(mgr.connections) == 0


# ---------------------------------------------------------------------------
# MCP JSON-RPC helpers
# ---------------------------------------------------------------------------

def test_mcp_jsonrpc_request_format() -> None:
    from hermes_lite.coding.mcp_client import _jsonrpc_request

    req = _jsonrpc_request("tools/list", {})
    assert req["jsonrpc"] == "2.0"
    assert "id" in req
    assert req["method"] == "tools/list"


# ---------------------------------------------------------------------------
# CLIP - new tools are registered
# ---------------------------------------------------------------------------

def test_new_tools_registered(tmp_path) -> None:
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace
    from hermes_lite.tools.coding import register_coding_tools
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_coding_tools(registry, Workspace(tmp_path), PermissionPolicy())

    names = {t["name"] for t in registry.list_tools()}
    expected_new = {
        "lsp_status", "lsp_diagnostics", "lsp_symbols", "lsp_definition",
        "lsp_references", "lsp_hover",
        "mcp_status", "mcp_connect", "mcp_list_tools", "mcp_call_tool",
        "subagent_execute",
        "discover_tests", "run_tests",
        "read_rules", "workspace_context",
    }
    assert expected_new <= names
