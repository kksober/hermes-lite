"""Context compression — token estimation and LLM-powered summarisation.

Helps keep conversations within token limits by detecting when compression
is needed and using an LLM to summarise early messages while preserving
recent context.
"""

from __future__ import annotations

import json
from typing import Any

import tiktoken


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate token count for a list of messages using tiktoken.

    Uses ``cl100k_base`` encoding (GPT-4 / GPT-3.5-turbo).  The estimate
    accounts for message framing tokens (roughly 4 tokens per message).

    Args:
        messages: List of dicts with at least a ``content`` key (and
                  optionally ``role``).

    Returns:
        Estimated total token count.
    """
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        # Fallback: rough char/4 estimate
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return total_chars // 4

    total = 0
    for msg in messages:
        # Each message carries ~4 tokens of framing overhead
        total += 4
        content = str(msg.get("content", ""))
        total += len(enc.encode(content))
    return total


def should_compress(
    messages: list[dict[str, Any]],
    max_tokens: int,
    threshold: float = 0.5,
) -> bool:
    """Determine whether context compression is advisable.

    Args:
        messages: Current conversation messages.
        max_tokens: Maximum token budget (e.g. model context window).
        threshold: Fraction of ``max_tokens`` at which compression triggers
                   (default 0.5 = 50%).

    Returns:
        ``True`` if estimated tokens exceed ``max_tokens * threshold``.
    """
    current = estimate_tokens(messages)
    return current > int(max_tokens * threshold)


def compress(
    messages: list[dict[str, Any]],
    model_name: str = "gpt-4o",
    keep_recent: int = 6,
) -> list[dict[str, Any]]:
    """Compress conversation context using LLM summarisation.

    Early messages (all but the most recent ``keep_recent``) are sent to an
    LLM to produce a concise summary.  The result is a new message list
    consisting of a system-style summary message followed by the preserved
    recent messages.

    Args:
        messages: Full conversation messages to compress.
        model_name: Model to use for summarisation (passed to tiktoken as
                    encoding hint; summarisation uses OpenAI).
        keep_recent: Number of most recent messages to preserve verbatim.

    Returns:
        A new list: ``[summary_system_msg, ...recent_messages]``.
    """
    if len(messages) <= keep_recent:
        return list(messages)

    early = messages[:-keep_recent]
    recent = messages[-keep_recent:]

    # Build a prompt for the summariser
    conversation_text = _messages_to_text(early)

    summary = _generate_summary(conversation_text, model_name)

    summary_msg: dict[str, Any] = {
        "role": "system",
        "content": (
            "<conversation_summary>\n"
            f"{summary}\n"
            "</conversation_summary>"
        ),
    }

    return [summary_msg] + recent


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    """Convert a list of message dicts to a compact text representation."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = str(msg.get("content", ""))
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)


def _generate_summary(conversation_text: str, model_name: str) -> str:
    """Generate a summary using the OpenAI API.

    Falls back to a simple extractive summary if the API is unavailable
    (e.g. in testing or when no API key is set).
    """
    try:
        import os

        import openai

        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a conversation summariser.  Summarise the "
                        "following exchange concisely, capturing key topics, "
                        "decisions, and action items.  Keep the summary under "
                        "300 words."
                    ),
                },
                {"role": "user", "content": conversation_text},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        return response.choices[0].message.content or ""

    except Exception:
        # Fallback: return a simple extractive summary (first ~500 chars)
        if len(conversation_text) <= 500:
            return conversation_text
        return conversation_text[:500] + "..."
