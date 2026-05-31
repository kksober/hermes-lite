"""Tests for M14: CLI commands (/retry, /undo, /compact) and agent reflection."""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Agent undo / turn counter / reflection
# ---------------------------------------------------------------------------


class TestAgentUndo:
    def test_undo_without_snapshot_fails(self) -> None:
        from hermes_lite import HermesAgent, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(config=config, defer_model_check=True)
        result = agent.undo_last_turn()
        assert result["ok"] is False
        assert result["error"] == "no_snapshot"

    def test_undo_restores_snapshot(self) -> None:
        from hermes_lite import HermesAgent, ProviderConfig
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(config=config, defer_model_check=True)

        # Simulate a message history
        msg = ModelRequest(parts=[UserPromptPart(content="hello")])
        agent._last_messages = [msg]
        agent._snapshot_history()
        assert agent._history_snapshot is not None
        assert len(agent._history_snapshot) == 1

        # Modify and undo
        agent._last_messages = []
        result = agent.undo_last_turn()
        assert result["ok"] is True
        assert len(agent._last_messages) == 1

    def test_undo_clears_snapshot(self) -> None:
        from hermes_lite import HermesAgent, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(config=config, defer_model_check=True)
        agent._snapshot_history()
        agent.undo_last_turn()
        # Second undo should fail — snapshot consumed
        result = agent.undo_last_turn()
        assert result["ok"] is False


class TestTurnCounter:
    def test_turn_starts_at_zero(self) -> None:
        from hermes_lite import HermesAgent, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(config=config, defer_model_check=True)
        assert agent.turn_count == 0

    def test_reflection_interval_default(self) -> None:
        from hermes_lite import HermesAgent, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(config=config, defer_model_check=True)
        assert agent.reflection_interval == 5

    def test_reflection_interval_configurable(self) -> None:
        from hermes_lite import HermesAgent, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(config=config, defer_model_check=True)
        agent.reflection_interval = 3
        assert agent.reflection_interval == 3

    def test_reflection_interval_minimum_one(self) -> None:
        from hermes_lite import HermesAgent, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(config=config, defer_model_check=True)
        agent.reflection_interval = 0
        assert agent.reflection_interval == 1
        agent.reflection_interval = -5
        assert agent.reflection_interval == 1


class TestReflectionPrompt:
    def test_reflection_prompt_includes_key_phrases(self) -> None:
        from hermes_lite import HermesAgent, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(config=config, defer_model_check=True)
        prompt = agent._build_reflection_prompt()
        assert "skill_manage" in prompt
        assert "reusable code" in prompt
        assert "mistakes" in prompt
        assert "<reflection>" in prompt


# ---------------------------------------------------------------------------
# CLI command handlers (unit-level)
# ---------------------------------------------------------------------------


class TestCliCommands:
    def test_cli_build_parser_has_workspace_flag(self) -> None:
        from hermes_lite.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["--workspace", "/tmp/test"])
        assert args.workspace == "/tmp/test"

    def test_cli_build_parser_defaults(self) -> None:
        from hermes_lite.cli import build_parser

        parser = build_parser()
        args = parser.parse_args([])
        assert args.workspace == ""


# ---------------------------------------------------------------------------
# Reflection injection integration (tests _snapshot_history is called)
# ---------------------------------------------------------------------------


class TestSnapshotIntegration:
    def test_snapshot_history_saves_current_messages(self) -> None:
        from hermes_lite import HermesAgent, ProviderConfig
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(config=config, defer_model_check=True)

        agent._last_messages = [
            ModelRequest(parts=[UserPromptPart(content="turn 1")]),
        ]
        agent._snapshot_history()
        assert agent._history_snapshot is not None
        assert len(agent._history_snapshot) == 1

        # Modify and verify snapshot is unchanged
        agent._last_messages.append(
            ModelRequest(parts=[UserPromptPart(content="turn 2")]),
        )
        assert len(agent._history_snapshot) == 1
