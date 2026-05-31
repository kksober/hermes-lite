"""Tests for LSP setup guidance and first-start detection."""
from __future__ import annotations

import shutil


def test_lsp_setup_guide_python_when_no_servers() -> None:
    from hermes_lite.coding.lsp import lsp_setup_guide

    guide = lsp_setup_guide([])
    assert guide["python_available"] is False
    assert isinstance(guide["suggestions"], list)
    assert any("pip install" in s for s in guide["suggestions"])


def test_lsp_setup_guide_shows_available_servers() -> None:
    from hermes_lite.coding.lsp import lsp_setup_guide, LspAvailable

    available = [LspAvailable(name="pyright", languages=["python"], executable="/usr/bin/pyright")]
    guide = lsp_setup_guide(available)
    assert guide["python_available"] is True
    assert "pyright" in str(guide["available"])


def test_lsp_setup_guide_includes_typescript_hint() -> None:
    from hermes_lite.coding.lsp import lsp_setup_guide

    guide = lsp_setup_guide([])
    # Should mention tsserver for TS/JS projects
    all_suggestions = " ".join(guide["suggestions"])
    assert "npm" in all_suggestions.lower() or "tsserver" in all_suggestions.lower() or "typescript" in all_suggestions.lower()


def test_lsp_startup_check_returns_status(tmp_path) -> None:
    from hermes_lite.coding.lsp import lsp_startup_check

    result = lsp_startup_check(str(tmp_path))
    assert result["ok"] is True
    assert "servers" in result
    assert "setup_guide" in result


def test_lsp_unavailable_message_is_actionable() -> None:
    from hermes_lite.coding.lsp import _unavailable

    result = _unavailable("diagnostics")
    assert result["available"] is False
    assert "install" in result["message"].lower() or "pip" in result["message"].lower()

