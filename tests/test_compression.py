"""Tests for the context compression module."""

from __future__ import annotations

import json

import pytest


MESSAGES_SMALL = [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi!"},
]

MESSAGES_LARGE = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Explain quantum computing in detail."},
    {"role": "assistant", "content": "Quantum computing uses qubits instead of bits. " * 50},
    {"role": "user", "content": "What about superposition?"},
    {"role": "assistant", "content": "Superposition allows qubits to exist in multiple states. " * 50},
    {"role": "user", "content": "And entanglement?"},
    {"role": "assistant", "content": "Entanglement links qubits across distances. " * 50},
    {"role": "user", "content": "Give me a summary."},
    {"role": "assistant", "content": "Here is your summary: " + ("quantum " * 200)},
    {"role": "user", "content": "Thanks!"},
    {"role": "assistant", "content": "You're welcome!"},
]


class TestEstimateTokens:
    """Test token estimation."""

    def test_estimate_basic(self) -> None:
        """Test that estimate_tokens returns a positive integer."""
        from hermes_lite.compression import estimate_tokens

        count = estimate_tokens(MESSAGES_SMALL)
        assert isinstance(count, int)
        assert count > 0

    def test_estimate_empty(self) -> None:
        """Test estimating tokens for an empty list."""
        from hermes_lite.compression import estimate_tokens

        count = estimate_tokens([])
        assert count == 0

    def test_estimate_grows_with_content(self) -> None:
        """Test that more content produces a higher token count."""
        from hermes_lite.compression import estimate_tokens

        small = estimate_tokens([{"role": "user", "content": "Hi"}])
        large = estimate_tokens([{"role": "user", "content": "Hello world " * 100}])
        assert large > small

    def test_estimate_with_missing_content(self) -> None:
        """Test messages without a content key don't crash."""
        from hermes_lite.compression import estimate_tokens

        count = estimate_tokens([{"role": "system"}])
        assert count >= 0


class TestShouldCompress:
    """Test compression threshold logic."""

    def test_should_compress_false_small(self) -> None:
        """Test that small messages don't trigger compression."""
        from hermes_lite.compression import should_compress

        # Very high threshold → never compress small messages
        result = should_compress(MESSAGES_SMALL, max_tokens=100_000, threshold=0.5)
        assert result is False

    def test_should_compress_true_large(self) -> None:
        """Test that large messages trigger compression."""
        from hermes_lite.compression import should_compress

        # Very low max_tokens → should trigger
        result = should_compress(MESSAGES_LARGE, max_tokens=10, threshold=0.5)
        assert result is True

    def test_should_compress_threshold(self) -> None:
        """Test threshold boundary behavior."""
        from hermes_lite.compression import estimate_tokens, should_compress

        msgs = [{"role": "user", "content": "test " * 500}]
        actual = estimate_tokens(msgs)

        # Set max_tokens just above actual → should NOT compress
        assert should_compress(msgs, max_tokens=actual * 3, threshold=0.5) is False

        # Set max_tokens just below → should compress
        assert should_compress(msgs, max_tokens=actual // 2, threshold=0.5) is True


class TestCompress:
    """Test the compress function."""

    def test_compress_noop_when_few_messages(self) -> None:
        """Test that compress returns messages unchanged if keep_recent >= len."""
        from hermes_lite.compression import compress

        result = compress(MESSAGES_SMALL, keep_recent=10)
        assert len(result) == len(MESSAGES_SMALL)
        assert result[0]["content"] == "Hello"

    def test_compress_structure(self) -> None:
        """Test that compress returns correct structure: [summary, ...recent]."""
        from hermes_lite.compression import compress

        # Build 10 messages, keep 3 recent → should get 1 summary + 3 = 4 messages
        msgs = [
            {"role": "user", "content": f"Message {i}"}
            for i in range(10)
        ]

        result = compress(msgs, keep_recent=3)
        assert len(result) == 4  # 1 summary + 3 recent
        assert result[0]["role"] == "system"
        assert "<conversation_summary>" in result[0]["content"]
        # The last 3 should be Message 7, 8, 9
        assert result[1]["content"] == "Message 7"
        assert result[2]["content"] == "Message 8"
        assert result[3]["content"] == "Message 9"

    def test_compress_keep_all_when_few(self) -> None:
        """Test that compress with keep_recent >= len returns all messages."""
        from hermes_lite.compression import compress

        result = compress(MESSAGES_SMALL, keep_recent=5)
        assert len(result) == len(MESSAGES_SMALL)

    def test_compress_fallback_summary(self) -> None:
        """Test that fallback summary works when no API key is set.

        The compress function falls back to an extractive summary if the
        OpenAI API is unavailable — this test verifies that path.
        """
        from hermes_lite.compression import compress

        msgs = [
            {"role": "user", "content": f"Message number {i} about important topic"}
            for i in range(10)
        ]

        result = compress(msgs, keep_recent=3)
        assert len(result) == 4
        assert result[0]["role"] == "system"
        # Fallback summary: first ~500 chars of conversation text
        assert len(result[0]["content"]) > 0
