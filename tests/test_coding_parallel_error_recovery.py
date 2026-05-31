"""Tests for parallel tool call tracking and error recovery."""
from __future__ import annotations


def test_parallel_safe_attribute_on_tool_schema() -> None:
    """Tools should have a parallel_safe flag in their schema."""
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(
        name="read_stuff",
        schema={"description": "Read things.", "properties": {}, "required": []},
        handler=lambda: "ok",
        toolset="coding",
        parallel_safe=True,
    )
    entry = registry._tools["read_stuff"]
    assert entry["parallel_safe"] is True


def test_parallel_safe_defaults_to_false() -> None:
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(
        name="write_stuff",
        schema={"description": "Write things.", "properties": {}, "required": []},
        handler=lambda: "ok",
        toolset="coding",
    )
    entry = registry._tools["write_stuff"]
    assert entry["parallel_safe"] is False


def test_error_classifier_categorizes_permission_denied() -> None:
    from hermes_lite.agent import classify_tool_error

    result = classify_tool_error('{"ok": false, "error": "permission_denied"}')
    assert result["category"] == "permission_denied"
    assert result["retryable"] is False


def test_error_classifier_categorizes_not_found() -> None:
    from hermes_lite.agent import classify_tool_error

    result = classify_tool_error('{"ok": false, "error": "not_found"}')
    assert result["category"] == "not_found"
    assert result["retryable"] is True
    assert "did you mean" in result["hint"].lower() or "check" in result["hint"].lower()


def test_error_classifier_categorizes_execution_error() -> None:
    from hermes_lite.agent import classify_tool_error

    result = classify_tool_error('{"ok": false, "error": "execution_error"}')
    assert result["category"] == "execution_error"
    assert result["retryable"] is True


def test_error_classifier_categorizes_test_failure() -> None:
    from hermes_lite.agent import classify_tool_error

    result = classify_tool_error(
        '{"ok": false, "total": 5, "passed": 3, "failed": 2}'
    )
    assert result["category"] == "test_failure"
    assert result["retryable"] is False


def test_error_classifier_returns_unknown_for_ok_result() -> None:
    from hermes_lite.agent import classify_tool_error

    result = classify_tool_error('{"ok": true, "result": "all good"}')
    assert result["category"] == "ok"


def test_build_parallel_hint_lists_safe_tools() -> None:
    from hermes_lite.agent import build_parallel_hint
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(
        name="read_file", schema={"description": "r"}, handler=lambda: "", toolset="coding", parallel_safe=True,
    )
    registry.register(
        name="list_files", schema={"description": "l"}, handler=lambda: "", toolset="coding", parallel_safe=True,
    )
    registry.register(
        name="write_file", schema={"description": "w"}, handler=lambda: "", toolset="coding",
    )

    hint = build_parallel_hint(registry)
    assert "read_file" in hint
    assert "list_files" in hint
    assert "write_file" not in hint


def test_error_aware_run_loop_injects_hints() -> None:
    """Verify that the build_system_prompt includes parallel hints."""
    from hermes_lite.agent import HermesAgent
    from hermes_lite.providers import ProviderConfig
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(
        name="read_file", schema={"description": "Read a file."}, handler=lambda: "", toolset="coding", parallel_safe=True,
    )

    agent = HermesAgent(
        config=ProviderConfig(provider="deepseek", model="deepseek-chat"),
        persona="Test persona.",
        tool_registry=registry,
        defer_model_check=True,
    )

    prompt = agent.build_system_prompt()
    assert "parallel" in prompt.lower() or "batch" in prompt.lower() or "同时" in prompt or "一次" in prompt
