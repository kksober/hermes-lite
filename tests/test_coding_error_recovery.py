"""Tests for agent error recovery and self-correction."""
from __future__ import annotations


def test_classify_tool_error_returns_retryable_hint() -> None:
    from hermes_lite.agent import classify_tool_error
    import json

    result = classify_tool_error(json.dumps({"ok": False, "error": "permission_denied"}))
    assert result["category"] == "permission_denied"
    assert result["retryable"] is False


def test_classify_tool_error_not_found_is_retryable() -> None:
    from hermes_lite.agent import classify_tool_error
    import json

    result = classify_tool_error(json.dumps({"ok": False, "error": "not_found"}))
    assert result["category"] == "not_found"
    assert result["retryable"] is True


def test_classify_tool_error_ok_result() -> None:
    from hermes_lite.agent import classify_tool_error
    import json

    result = classify_tool_error(json.dumps({"ok": True, "data": "success"}))
    assert result["category"] == "ok"
    assert result["retryable"] is False


def test_classify_tool_error_test_failure_has_hint() -> None:
    from hermes_lite.agent import classify_tool_error
    import json

    data = {"ok": False, "total": 10, "passed": 5, "failed": 3, "errors": 2}
    result = classify_tool_error(json.dumps(data))
    assert result["category"] == "test_failure"
    assert "failed" in result["hint"]


def test_classify_tool_error_plain_text() -> None:
    from hermes_lite.agent import classify_tool_error

    result = classify_tool_error("execution_error: something went wrong")
    assert result["category"] == "execution_error"
    assert result["retryable"] is True


def test_error_counts_accumulate() -> None:
    from hermes_lite.agent import HermesAgent
    from hermes_lite.providers.adapters import ProviderConfig

    config = ProviderConfig(provider="openai", model="gpt-4o")
    agent = HermesAgent(config=config, defer_model_check=True)

    assert agent._consecutive_errors == 0
    assert agent._error_counts == {}
    agent._error_counts["permission_denied"] = 3
    agent._error_counts["not_found"] = 1
    agent._consecutive_errors = 5

    prompt = agent._build_error_recovery_prompt()
    assert "permission_denied" in prompt
    assert "5+" in prompt or "consecutive" in prompt.lower()


def test_build_error_recovery_prompt_empty_when_no_errors() -> None:
    from hermes_lite.agent import HermesAgent
    from hermes_lite.providers.adapters import ProviderConfig

    config = ProviderConfig(provider="openai", model="gpt-4o")
    agent = HermesAgent(config=config, defer_model_check=True)

    prompt = agent._build_error_recovery_prompt()
    assert prompt == ""


def test_max_consecutive_errors_triggers_escalation() -> None:
    from hermes_lite.agent import HermesAgent
    from hermes_lite.providers.adapters import ProviderConfig

    config = ProviderConfig(provider="openai", model="gpt-4o")
    agent = HermesAgent(config=config, defer_model_check=True)

    agent._consecutive_errors = 10
    agent._max_consecutive_errors = 10
    prompt = agent._build_error_recovery_prompt()
    assert "LIMIT" in prompt or "Stop" in prompt


def test_reset_error_state_clears_counters() -> None:
    from hermes_lite.agent import HermesAgent
    from hermes_lite.providers.adapters import ProviderConfig

    config = ProviderConfig(provider="openai", model="gpt-4o")
    agent = HermesAgent(config=config, defer_model_check=True)

    agent._error_counts["not_found"] = 5
    agent._consecutive_errors = 3
    agent._reset_error_state()

    assert agent._error_counts == {}
    assert agent._consecutive_errors == 0


def test_build_system_prompt_includes_error_recovery() -> None:
    from hermes_lite.agent import HermesAgent
    from hermes_lite.providers.adapters import ProviderConfig

    config = ProviderConfig(provider="openai", model="gpt-4o")
    agent = HermesAgent(config=config, defer_model_check=True)
    agent._consecutive_errors = 5
    agent._error_counts["not_found"] = 3

    prompt = agent.build_system_prompt()
    assert "Recent Tool Errors" in prompt
