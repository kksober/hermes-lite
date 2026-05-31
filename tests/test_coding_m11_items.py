"""Tests for M11 P2 items: cost, watch, diagram, security."""
from __future__ import annotations


# -- cost ---------------------------------------------------------------

def test_cost_estimate_known_model() -> None:
    from hermes_lite.agent import cost_estimate

    result = cost_estimate("deepseek-v4", 1_000_000, 1_000_000)
    assert result["model"] == "deepseek-v4"
    assert result["input_cost"] == 0.14
    assert result["output_cost"] == 0.28
    assert result["total_cost"] == 0.42


def test_cost_estimate_unknown_model() -> None:
    from hermes_lite.agent import cost_estimate

    result = cost_estimate("unknown-model", 1_000_000, 1_000_000)
    assert result["total_cost"] == 0.0


def test_cost_estimate_zero_tokens() -> None:
    from hermes_lite.agent import cost_estimate

    result = cost_estimate("gpt-4o", 0, 0)
    assert result["total_cost"] == 0.0


def test_agent_usage_includes_cost() -> None:
    from hermes_lite.agent import HermesAgent
    from hermes_lite.providers.adapters import ProviderConfig

    config = ProviderConfig(provider="openai", model="gpt-4o")
    agent = HermesAgent(config=config, defer_model_check=True)
    agent._total_prompt_tokens = 1000
    agent._total_completion_tokens = 500
    usage = agent.usage
    assert "cost_usd" in usage
    assert "cost_detail" in usage
    assert usage["cost_usd"] > 0


# -- watch --------------------------------------------------------------

def test_watch_status(tmp_path) -> None:
    from hermes_lite.coding.watch import watch_status

    (tmp_path / "a.py").write_text("x=1")
    (tmp_path / "b.py").write_text("y=2")
    (tmp_path / "c.txt").write_text("z=3")

    result = watch_status(str(tmp_path), ["*.py"])
    assert result["ok"] is True
    assert result["file_count"] == 2


def test_watch_status_invalid_root() -> None:
    from hermes_lite.coding.watch import watch_status

    result = watch_status("/nonexistent", ["*.py"])
    assert result["ok"] is False


# -- diagram ------------------------------------------------------------

def test_render_diagram_returns_source_preview() -> None:
    from hermes_lite.tools.coding import _render_diagram

    source = "graph TD\n  A-->B\n  B-->C"
    result = _render_diagram(source)
    assert result["ok"] is True
    assert result["format"] == "mermaid"
    assert "graph TD" in result["source_preview"]


def test_render_diagram_saves_to_file(tmp_path) -> None:
    from hermes_lite.tools.coding import _render_diagram

    out = str(tmp_path / "diagram.mmd")
    result = _render_diagram("graph LR\n  X-->Y", output_path=out)
    assert result["ok"] is True
    assert result["saved"] is True
    assert (tmp_path / "diagram.mmd").exists()


# -- security audit -----------------------------------------------------

def test_security_audit_no_ecosystem(tmp_path) -> None:
    from hermes_lite.coding.subagents import security_audit

    result = security_audit(str(tmp_path))
    assert result["ok"] is True
    assert not result["audited"]


def test_security_audit_python_ecosystem(tmp_path) -> None:
    from hermes_lite.coding.subagents import security_audit

    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'")
    result = security_audit(str(tmp_path))
    assert result["ok"] is True
    # pip-audit may or may not be installed, but the check runs
    assert result["audited"] is True
    assert len(result["results"]) > 0
