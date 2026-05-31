"""Tests for context window management."""
from __future__ import annotations


def test_context_window_defaults() -> None:
    from hermes_lite.compression import ContextWindow

    cw = ContextWindow(max_tokens=128000)
    assert cw.max_tokens == 128000
    assert cw.threshold == 0.8
    assert cw.keep_recent == 10
    assert cw.compress_count == 0


def test_context_window_estimate_small() -> None:
    from hermes_lite.compression import ContextWindow

    cw = ContextWindow(max_tokens=128000)
    msgs = [{"role": "user", "content": "hello"}]
    est = cw.estimate(msgs)
    assert est > 0
    assert est < 100


def test_context_window_usage_ratio_zero_when_zero_max() -> None:
    from hermes_lite.compression import ContextWindow

    cw = ContextWindow(max_tokens=0)
    assert cw.usage_ratio([{"role": "user", "content": "hello"}]) == 0.0


def test_context_window_needs_compression_empty() -> None:
    from hermes_lite.compression import ContextWindow

    cw = ContextWindow(max_tokens=100, threshold=0.8)
    # Small message list won't trigger compression
    assert not cw.needs_compression([{"role": "user", "content": "hello"}])


def test_context_window_needs_compression_large() -> None:
    from hermes_lite.compression import ContextWindow

    cw = ContextWindow(max_tokens=100, threshold=0.8)
    large_msg = {"role": "user", "content": "hello world " * 100}  # ~300+ tokens
    assert cw.needs_compression([large_msg])


def test_context_window_compress_if_needed() -> None:
    from hermes_lite.compression import ContextWindow

    cw = ContextWindow(max_tokens=100, threshold=0.8, keep_recent=2)
    msgs = [
        {"role": "user", "content": "x" * 400},
        {"role": "assistant", "content": "y" * 400},
        {"role": "user", "content": "recent1"},
        {"role": "assistant", "content": "recent2"},
    ]
    result = cw.compress_if_needed(msgs, model_name="gpt-4o")
    # Should have compressed: summary + 2 recent messages
    assert len(result) < len(msgs)


def test_context_window_record_tracks_usage() -> None:
    from hermes_lite.compression import ContextWindow

    cw = ContextWindow(max_tokens=1000)
    cw.record_usage(100, 50)
    assert cw.tokens_used == {"prompt": 100, "completion": 50}
    assert cw.token_budget_remaining == 850


def test_context_window_clear_resets() -> None:
    from hermes_lite.compression import ContextWindow

    cw = ContextWindow(max_tokens=1000)
    cw.record_usage(100, 50)
    cw.compress_if_needed([{"role": "user", "content": "x" * 500}])
    cw.clear()
    assert cw.compress_count == 0
    assert cw.tokens_used == {"prompt": 0, "completion": 0}


def test_agent_has_context_window() -> None:
    from hermes_lite.agent import HermesAgent
    from hermes_lite.providers.adapters import ProviderConfig

    config = ProviderConfig(provider="openai", model="gpt-4o")
    agent = HermesAgent(config=config, defer_model_check=True)
    assert hasattr(agent, "context_window")
    cw = agent.context_window
    assert cw.max_tokens == 128000
    assert cw.threshold == 0.8


def test_agent_clear_context() -> None:
    from hermes_lite.agent import HermesAgent
    from hermes_lite.providers.adapters import ProviderConfig

    config = ProviderConfig(provider="openai", model="gpt-4o")
    agent = HermesAgent(config=config, defer_model_check=True)
    agent._consecutive_errors = 5
    agent._error_counts["not_found"] = 3
    result = agent.clear_context()
    assert result["ok"] is True
    assert agent._consecutive_errors == 0
    assert agent._error_counts == {}


def test_model_context_sizes_known() -> None:
    from hermes_lite.agent import _MODEL_CONTEXT_SIZES

    assert _MODEL_CONTEXT_SIZES["gpt-4o"] == 128000
    assert _MODEL_CONTEXT_SIZES["claude-sonnet-4-6"] == 200000
    assert _MODEL_CONTEXT_SIZES["deepseek-v4"] == 131072
