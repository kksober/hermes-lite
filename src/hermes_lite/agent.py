"""Core agent loop — multi-turn conversation with tool dispatch.

The HermesAgent orchestrates: building system prompts, calling the LLM,
dispatching tool calls, injecting memory, and looping until the model
produces a final text response.

Supports parallel tool calls — when the LLM returns multiple independent
tool calls in a single turn, they are dispatched together.  Read-only tools
are marked ``parallel_safe`` so the model is encouraged to batch them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Literal

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from hermes_lite.memory.manager import MemoryManager
from hermes_lite.providers.adapters import ProviderConfig, create_agent
from hermes_lite.skills.manager import SkillManager
from hermes_lite.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# model context window sizes (tokens)
# ---------------------------------------------------------------------------

_MODEL_CONTEXT_SIZES: dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    "claude-sonnet-4-6": 200000,
    "claude-opus-4-7": 200000,
    "claude-haiku-4-5": 200000,
    "claude-3-5-sonnet": 200000,
    "deepseek-v4": 131072,
    "deepseek-v4-pro": 131072,
    "deepseek-v3": 65536,
    "deepseek-r1": 131072,
}

# ---------------------------------------------------------------------------
# model pricing ($ per 1M tokens) — input / output
# ---------------------------------------------------------------------------

_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "deepseek-v4": (0.14, 0.28),
    "deepseek-v4-pro": (0.14, 0.28),
    "deepseek-v3": (0.27, 1.10),
    "deepseek-r1": (0.55, 2.19),
}


def cost_estimate(model: str, prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
    """Estimate cost in USD from token counts and model pricing.

    Returns ``{input_cost, output_cost, total_cost, model}``.
    Prices are in USD per 1M tokens.
    """
    input_price, output_price = _MODEL_PRICING.get(model, (0.0, 0.0))
    input_cost = (prompt_tokens / 1_000_000) * input_price
    output_cost = (completion_tokens / 1_000_000) * output_price
    return {
        "model": model,
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(input_cost + output_cost, 6),
    }

# ---------------------------------------------------------------------------
# error classification
# ---------------------------------------------------------------------------

_ERROR_PATTERNS: dict[str, tuple[bool, str]] = {
    "permission_denied": (False, "Permission denied — you cannot perform this operation."),
    "not_found": (True, "Resource not found — check the path or name, then retry."),
    "execution_error": (True, "Command execution error — review the command and retry."),
    "timeout": (True, "Operation timed out — try a smaller scope or increase timeout."),
    "invalid_task_index": (False, "Invalid worktree task index."),
    "not_git_repo": (False, "Not a git repository — git operations unavailable."),
    "pytest_not_found": (True, "pytest is not installed — install it or use the .venv python."),
    "test_failure": (False, "Some tests failed — review failures and fix the code."),
}


def classify_tool_error(result_str: str) -> dict[str, Any]:
    """Classify a tool error response and return actionable metadata.

    Parameters
    ----------
    result_str:
        The JSON string or plain text returned by a tool.

    Returns
    -------
    Dict with ``category``, ``retryable``, and ``hint`` keys.
    """
    category = "unknown"
    retryable = True
    hint = ""

    # Try to parse as JSON
    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        data = None

    if isinstance(data, dict):
        ok = data.get("ok", True)
        if ok is True:
            return {"category": "ok", "retryable": False, "hint": ""}

        error_key = str(data.get("error", "")).lower()
        # Check for test failures (ok=False but has test metrics)
        if "total" in data and ("passed" in data or "failed" in data):
            failed_count = data.get("failed", 0)
            error_count = data.get("errors", 0)
            return {
                "category": "test_failure",
                "retryable": False,
                "hint": f"{failed_count} failed, {error_count} errors — review the failures list for details.",
            }

        # Match error key against known patterns
        for pattern_key, (retry, hint_msg) in _ERROR_PATTERNS.items():
            if pattern_key in error_key or pattern_key in result_str.lower():
                return {"category": pattern_key, "retryable": retry, "hint": hint_msg}

        # Check if error message suggests a workaround
        if error_key:
            return {"category": error_key, "retryable": True, "hint": str(data.get("message", ""))}

    # Plain text error
    result_lower = result_str.lower()
    for pattern_key, (retry, hint_msg) in _ERROR_PATTERNS.items():
        if pattern_key in result_lower:
            return {"category": pattern_key, "retryable": retry, "hint": hint_msg}

    return {"category": "unknown", "retryable": True, "hint": hint}


def build_parallel_hint(registry: ToolRegistry) -> str:
    """Generate a system prompt hint listing tools safe for parallel calls."""
    parallel_tools = [
        name for name, entry in registry._tools.items()
        if entry.get("parallel_safe", False)
    ]
    if not parallel_tools:
        return ""
    names = ", ".join(sorted(parallel_tools))
    return (
        f"\nYou may call multiple independent read-only tools in a single response "
        f"for efficiency. These tools are safe to batch: {names}.\n"
    )


def _model_messages_to_dicts(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert pydantic_ai ModelMessage list to plain dicts for token estimation."""
    result: list[dict[str, Any]] = []
    for msg in messages:
        role = "system" if hasattr(msg, "parts") and any(
            "SystemPromptPart" in str(type(p)) for p in msg.parts
        ) else "user"
        content = ""
        if hasattr(msg, "parts"):
            parts_content: list[str] = []
            for p in msg.parts:
                if hasattr(p, "content"):
                    parts_content.append(str(p.content))
                elif hasattr(p, "text"):
                    parts_content.append(str(p.text))
                else:
                    parts_content.append(str(p))
            content = " ".join(parts_content)
        result.append({"role": role, "content": content})
    return result


def _dicts_to_model_messages(dicts: list[dict[str, Any]]) -> list[Any]:
    """Convert plain dicts back to pydantic_ai ModelMessage objects."""
    from pydantic_ai.messages import ModelRequest, ModelResponse, SystemPromptPart, UserPromptPart, TextPart

    result: list[Any] = []
    for d in dicts:
        role = d.get("role", "user")
        content = d.get("content", "")
        if role == "system":
            result.append(ModelRequest(parts=[SystemPromptPart(content=content)]))
        elif role == "assistant":
            result.append(ModelResponse(parts=[TextPart(content=content)]))
        else:
            result.append(ModelRequest(parts=[UserPromptPart(content=content)]))
    return result


class HermesAgent:
    """Main agent class — builds the system prompt, runs the multi-turn loop.

    Usage::

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(config=config, persona="You are a helpful assistant.")
        result = await agent.run("What is 2+2?")
    """

    def __init__(
        self,
        config: ProviderConfig,
        *,
        persona: str = "You are a helpful AI assistant.",
        tool_registry: ToolRegistry | None = None,
        memory_manager: MemoryManager | None = None,
        skill_manager: SkillManager | None = None,
        memory_inject_limit: int = 10,
        defer_model_check: bool = False,
    ) -> None:
        """Initialise the agent.

        Args:
            config: Provider configuration.
            persona: System prompt persona text.
            tool_registry: Optional pre-configured ToolRegistry.
            memory_manager: Optional MemoryManager for persistent memory.
            skill_manager: Optional SkillManager for skill indexing.
            memory_inject_limit: Max memory entries to inject into the system prompt.
            defer_model_check: Passed through to pydantic-ai Agent.
        """
        self._config = config
        self._persona = persona
        self._tool_registry = tool_registry or ToolRegistry()
        self._memory = memory_manager
        self._skills = skill_manager
        self._memory_inject_limit = memory_inject_limit
        self._defer_model_check = defer_model_check
        self._last_messages: list[ModelMessage] = []
        # Turn tracking and reflection
        self._turn_count = 0
        self._reflection_interval = 5
        self._history_snapshot: list[ModelMessage] | None = None
        # Token usage tracking
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._call_count = 0
        # Error recovery tracking
        self._error_counts: dict[str, int] = {}
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10
        # Context window management
        from hermes_lite.compression import ContextWindow
        ctx_size = _MODEL_CONTEXT_SIZES.get(config.model, 128000)
        self._context_window = ContextWindow(ctx_size, threshold=0.8, keep_recent=10)
        self._pending_resume_messages: list[Any] | None = None

    @property
    def config(self) -> ProviderConfig:
        """Return the provider configuration."""
        return self._config

    @property
    def tool_registry(self) -> ToolRegistry:
        """Return the tool registry (for registering tools at runtime)."""
        return self._tool_registry

    @property
    def memory(self) -> MemoryManager | None:
        """Return the memory manager, if configured."""
        return self._memory

    @property
    def skills(self) -> SkillManager | None:
        """Return the skill manager, if configured."""
        return self._skills

    @property
    def last_messages(self) -> list[ModelMessage]:
        """Return the message history from the most recent :meth:`run` or
        :meth:`run_stream` call.

        Pass this value as ``message_history`` on the next call to maintain
        conversation continuity across invocations.
        """
        return self._last_messages

    @property
    def usage(self) -> dict[str, object]:
        """Return cumulative token usage for this session with cost estimate."""
        cost = cost_estimate(
            self._config.model,
            self._total_prompt_tokens,
            self._total_completion_tokens,
        )
        return {
            "prompt_tokens": self._total_prompt_tokens,
            "completion_tokens": self._total_completion_tokens,
            "total_tokens": self._total_prompt_tokens + self._total_completion_tokens,
            "call_count": self._call_count,
            "model": self._config.model,
            "cost_usd": cost["total_cost"],
            "cost_detail": cost,
        }

    def _log_tool_failures(self, response_parts: list) -> int:
        """Log tool failures, track error counts, and return the count of failed tools."""
        failed_count = 0
        for msg in response_parts:
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    content = str(part.content) if part.content else ""
                    classification = classify_tool_error(content)
                    if classification["category"] != "ok":
                        failed_count += 1
                        tool_name = getattr(part, "tool_name", "unknown")
                        cat = classification["category"]
                        self._error_counts[cat] = self._error_counts.get(cat, 0) + 1
                        logger.warning(
                            "tool_failed tool=%s category=%s count=%d retryable=%s hint=%s",
                            tool_name, cat, self._error_counts[cat],
                            classification["retryable"],
                            classification["hint"][:120],
                        )
        if failed_count > 0:
            self._consecutive_errors += 1
        else:
            self._consecutive_errors = 0
        return failed_count

    def _build_error_recovery_prompt(self) -> str:
        """Build an error recovery prompt when errors accumulate.

        Injects corrective guidance when the same error repeats or when
        consecutive errors exceed a threshold.
        """
        if self._consecutive_errors == 0:
            return ""

        parts: list[str] = []

        # Repeated same-category errors
        for cat, count in self._error_counts.items():
            if count >= 3:
                for pattern_key, (_retry, hint) in _ERROR_PATTERNS.items():
                    if pattern_key == cat:
                        parts.append(f"  - You have hit '{cat}' {count} times. {hint}")
                        break

        if self._consecutive_errors >= 5:
            parts.append(
                "  - You have had 5+ consecutive tool errors. "
                "Try a different approach instead of retrying the same action."
            )

        if self._consecutive_errors >= self._max_consecutive_errors:
            parts.append(
                "  - ERROR LIMIT REACHED. Stop retrying and explain the problem to the user."
            )

        if not parts:
            return ""

        return (
            "\n## Recent Tool Errors\n"
            "Some of your recent tool calls have failed. Please adjust your approach:\n"
            + "\n".join(parts)
        )

    def _reset_error_state(self) -> None:
        """Reset error tracking for a new conversation."""
        self._error_counts.clear()
        self._consecutive_errors = 0

    def clear_context(self) -> dict[str, object]:
        """Clear conversation history and reset context window.

        Call this to start fresh without restarting the CLI.
        Returns a status dict.
        """
        self._last_messages = []
        self._reset_error_state()
        self._context_window.clear()
        return {
            "ok": True,
            "message": "Conversation history cleared. Starting fresh.",
            "compress_count_reset": self._context_window.compress_count == 0,
        }

    def set_message_history(self, messages: list[dict[str, Any]]) -> None:
        """Set the message history from a previously saved session.

        Converts plain dicts to pydantic_ai ModelMessage objects
        so they can be passed to ``run()`` as ``message_history``.
        """
        self._pending_resume_messages = _dicts_to_model_messages(messages)

    @property
    def context_window(self):
        """Access the ContextWindow tracker (for inspection/CLI)."""
        return self._context_window

    @property
    def turn_count(self) -> int:
        """Number of completed turns in this session."""
        return self._turn_count

    @property
    def reflection_interval(self) -> int:
        """Turns between automatic reflection prompts."""
        return self._reflection_interval

    @reflection_interval.setter
    def reflection_interval(self, value: int) -> None:
        self._reflection_interval = max(1, value)

    def _snapshot_history(self) -> None:
        """Save the current message history for potential undo."""
        self._history_snapshot = list(self._last_messages) if self._last_messages else None

    def undo_last_turn(self) -> dict[str, object]:
        """Restore message history to the snapshot taken before the last turn.

        Returns a status dict indicating whether undo was possible.
        """
        if self._history_snapshot is None:
            return {"ok": False, "error": "no_snapshot", "message": "No snapshot to restore."}
        self._last_messages = self._history_snapshot
        self._history_snapshot = None
        if self._turn_count > 0:
            self._turn_count -= 1
        return {"ok": True, "message": f"Restored to turn {self._turn_count}.", "turn": self._turn_count}

    async def _call_with_retry(
        self,
        agent: Agent,
        messages: list[ModelMessage],
        output_type: type,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> Any:
        """Call agent.run() with timeout and retry for transient errors.

        Retries on timeout (120s) and HTTP 429/503 errors with exponential
        backoff.  Raises the last error if all retries are exhausted.
        """
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                result = await asyncio.wait_for(
                    agent.run(
                        user_prompt=None,
                        message_history=messages,
                        output_type=output_type,
                    ),
                    timeout=120,
                )
                # Track token usage
                self._call_count += 1
                try:
                    usage_info = getattr(result, "usage", None)
                    if usage_info:
                        self._total_prompt_tokens += getattr(usage_info, "request_tokens", 0) or 0
                        self._total_completion_tokens += getattr(usage_info, "response_tokens", 0) or 0
                    else:
                        raw = getattr(result, "_usage", None)
                        if raw and isinstance(raw, dict):
                            self._total_prompt_tokens += raw.get("prompt_tokens", 0)
                            self._total_completion_tokens += raw.get("completion_tokens", 0)
                except Exception:
                    pass
                return result
            except asyncio.TimeoutError:
                last_exc = RuntimeError("LLM call timed out after 120s")
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "LLM call timed out, retrying in %.1fs (attempt %d/%d)",
                        delay, attempt + 2, max_retries,
                    )
                    await asyncio.sleep(delay)
            except ModelHTTPError as exc:
                last_exc = exc
                if exc.status_code in (429, 503):
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            "LLM call failed HTTP %d, retrying in %.1fs (attempt %d/%d)",
                            exc.status_code, delay, attempt + 2, max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue
                raise
            except Exception as exc:
                # Check for HTTP status in nested exceptions
                http_status = None
                inner = exc
                while inner is not None:
                    http_status = getattr(inner, "status_code", None)
                    if http_status in (429, 503):
                        break
                    inner = getattr(inner, "__cause__", None)
                if http_status in (429, 503):
                    last_exc = exc
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            "LLM call failed HTTP %d (nested), retrying in %.1fs (attempt %d/%d)",
                            http_status, delay, attempt + 2, max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue
                raise

        raise last_exc or RuntimeError("LLM call failed after all retries")

    def _build_agent(self) -> Agent[None, str]:
        """Create (or recreate) the underlying pydantic-ai Agent.

        The system prompt is passed as an empty string here to avoid
        duplication — the real system prompt is injected as a
        ``SystemPromptPart`` in the message history at the start of each
        ``run()`` / ``run_stream()`` call.
        """
        return create_agent(
            self._config,
            system_prompt="",
            tools=self._tool_registry.as_pydantic_tools(),
            defer_model_check=self._defer_model_check,
        )

    def build_system_prompt(self) -> str:
        """Assemble the full system prompt.

        Composed from: persona + injected memory + skill index + tool schemas.

        Returns:
            Complete system prompt string.
        """
        parts: list[str] = [self._persona]

        # Inject memory if available
        if self._memory is not None:
            mem_text = self._memory.inject(limit=self._memory_inject_limit)
            if mem_text:
                parts.append("\n" + mem_text)

        # Inject skill index if available
        if self._skills is not None:
            skill_text = self._skills.index()
            if skill_text:
                parts.append("\n" + skill_text)

        # Append tool schemas as a compact description
        tools_list = self._tool_registry.list_tools()
        if tools_list:
            parts.append("\n<available_tools>")
            for t in tools_list:
                parallel_mark = " [parallel_safe]" if t.get("parallel_safe") else ""
                parts.append(f"- {t['name']} [{t['toolset']}]{parallel_mark}")
            parts.append("</available_tools>")

        # Add parallel tool call hint
        parallel_hint = build_parallel_hint(self._tool_registry)
        if parallel_hint:
            parts.append(parallel_hint)

        # Inject error recovery guidance when errors are accumulating
        error_prompt = self._build_error_recovery_prompt()
        if error_prompt:
            parts.append(error_prompt)

        return "\n".join(parts)

    def _build_reflection_prompt(self) -> str:
        """Build a lightweight reflection prompt injected every N turns.

        The prompt encourages the agent to consider creating or updating skills,
        abstracting reusable patterns, and noting mistakes to avoid.
        """
        return (
            "\n<reflection>\n"
            "You have completed another round of work. Consider:\n"
            "1. Did you learn a pattern or convention worth remembering? "
            "If so, use skill_manage to create or update a skill.\n"
            "2. Is there reusable code you should abstract? If so, suggest it.\n"
            "3. Any mistakes you made that future-you should avoid?\n"
            "</reflection>\n"
        )

    async def run(
        self,
        user_input: str,
        max_turns: int = 50,
        result_type: type | None = None,
        message_history: list[ModelMessage] | None = None,
    ) -> tuple[str, list[ModelMessage]]:
        """Run the agent with a user prompt in a multi-turn loop.

        The loop:
        1. Calls the LLM with the conversation history.
        2. If the model returns tool calls, pydantic-ai dispatches them
           and result.all_messages() contains the correct message ordering.
        3. Repeats until the model produces a final text response or max_turns is hit.

        Args:
            user_input: The user's message.
            max_turns: Maximum tool-call iterations before forcing a response.
            result_type: Optional Pydantic model for structured output.
            message_history: Optional pre-existing message history to continue
                a conversation.  If provided, the new user_input is appended
                to it instead of building a fresh message list from scratch.

        Returns:
            Tuple of (final_text_response, final_message_list).
            The final_message_list can be passed back as ``message_history``
            on the next call to maintain conversation continuity.
        """
        # Rebuild system prompt in case memory/tools changed
        system_prompt = self.build_system_prompt()

        # Build or extend message history
        if message_history is not None:
            messages = list(message_history) + [
                ModelRequest(parts=[UserPromptPart(content=user_input)]),
            ]
        else:
            messages: list[ModelMessage] = [
                ModelRequest(parts=[SystemPromptPart(content=system_prompt)]),
                ModelRequest(parts=[UserPromptPart(content=user_input)]),
            ]

        # Check context window and auto-compress if needed
        if message_history is not None:
            msg_dicts = _model_messages_to_dicts(messages)
            ratio_before = self._context_window.usage_ratio(msg_dicts)
            if self._context_window.needs_compression(msg_dicts):
                compressed_dicts = self._context_window.compress_if_needed(
                    msg_dicts, self._config.model,
                )
                messages = _dicts_to_model_messages(compressed_dicts)
                ratio_after = self._context_window.usage_ratio(compressed_dicts)
                self._last_context_ratio = ratio_after
                if self._context_window.compress_count == 1:
                    pass  # first compression, silent

        turn = 0
        result: Any = None
        while turn < max_turns:
            turn += 1

            # Rebuild the pydantic agent every turn to pick up any
            # newly registered tools (via the @agent.tool decorator).
            agent = self._build_agent()

            # Call the pydantic-ai agent with accumulated history (with timeout + retry)
            result = await self._call_with_retry(
                agent,
                messages,
                result_type if result_type else str,
            )

            # Log any tool failures
            self._log_tool_failures(result.all_messages())

            # Use result.all_messages() — pydantic-ai guarantees correct
            # message ordering (tool results immediately follow tool_calls).
            messages = result.all_messages()

            # Extract the response parts
            response_parts = result.new_messages()
            if not response_parts:
                # If nothing was returned, try to use result.output directly
                final = str(result.output) if result.output else ""
                logger.info(
                    "turn=%d tool_calls=0 text_len=%d (empty response, fallback)",
                    turn, len(final),
                )
                return final, messages

            # Collect tool calls and text from response
            has_tool_calls = False
            text_parts: list[str] = []

            for msg in response_parts:
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        has_tool_calls = True
                    elif isinstance(part, TextPart):
                        text_parts.append(part.content)

            tool_count = sum(
                1 for msg in response_parts
                for part in msg.parts
                if isinstance(part, ToolCallPart)
            )
            text_len = sum(len(t) for t in text_parts)
            logger.info("turn=%d tool_calls=%d text_len=%d", turn, tool_count, text_len)

            # If we have text output and no tool calls, we're done
            if text_parts and not has_tool_calls:
                return "\n".join(text_parts), messages

            # If there are tool calls, pydantic-ai has already executed
            # them and result.all_messages() includes everything in order.
            # Continue the loop with the updated message history.
            if has_tool_calls:
                continue

            # No tool calls and no text — force break
            if result.output:
                return str(result.output), messages
            break

        logger.warning("max_turns=%d reached — forcing response", max_turns)
        # Fallback: use final result output
        final = str(result.output) if result and result.output else ""
        return final, messages

    async def run_stream(
        self,
        user_input: str,
        max_turns: int = 50,
        message_history: list[ModelMessage] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream text output token-by-token using pydantic-ai native streaming.

        Uses ``agent.run_stream()`` under the hood to produce true streaming
        deltas rather than buffered per-turn chunks.  Tool calls are handled
        transparently by pydantic-ai in the background.

        After the generator is exhausted, the final message history is available
        via the :attr:`last_messages` attribute for use in subsequent calls.

        Args:
            user_input: The user's message.
            max_turns: Maximum tool-call iterations before forcing a response.
            message_history: Optional pre-existing message history to continue
                a conversation.

        Yields:
            Text chunks (typically token-level) as they are produced.
        """
        # Rebuild system prompt in case memory/tools changed
        system_prompt = self.build_system_prompt()

        # Snapshot current history for potential undo
        self._snapshot_history()

        # Build or extend message history
        if message_history is not None:
            messages = list(message_history) + [
                ModelRequest(parts=[UserPromptPart(content=user_input)]),
            ]
        else:
            messages: list[ModelMessage] = [
                ModelRequest(parts=[SystemPromptPart(content=system_prompt)]),
                ModelRequest(parts=[UserPromptPart(content=user_input)]),
            ]

        # Rebuild agent once — pydantic-ai handles the full multi-turn
        # execution including tool calls within run_stream().
        agent = self._build_agent()

        try:
            async with agent.run_stream(
                user_prompt=None,
                message_history=messages,
                output_type=str,
            ) as streamed_result:
                logger.info("stream_start text_len=%d", len(user_input))
                async for chunk in streamed_result.stream_text(
                    delta=True, debounce_by=None
                ):
                    yield chunk
                # After streaming completes, capture final messages
                final_messages = streamed_result.all_messages()
                self._last_messages = final_messages
                self._turn_count += 1
                # If reflection is due, yield the reflection prompt as an extra chunk
                if self._turn_count > 0 and self._turn_count % self._reflection_interval == 0:
                    reflection = self._build_reflection_prompt()
                    if reflection:
                        yield "\n\n" + reflection
                logger.info("stream_end total_messages=%d turn=%d", len(final_messages), self._turn_count)
        except Exception:
            logger.exception("stream_error")
            raise

    def tool(
        self,
        toolset: str = "default",
        requires: Any = None,
    ):
        """Decorator to register a function as a tool on the agent.

        Usage::

            @agent.tool("terminal")
            def run_shell(command: str) -> str:
                ...

        Args:
            toolset: Logical group for the tool.
            requires: Optional callable returning True if prerequisites are met.

        Returns:
            A decorator that registers the function.
        """
        import inspect

        def decorator(func):
            # Build a simple schema from the function signature
            sig = inspect.signature(func)
            properties: dict[str, dict[str, Any]] = {}
            required: list[str] = []
            for param_name, param in sig.parameters.items():
                param_type = "string"
                if param.annotation is not inspect.Parameter.empty:
                    if param.annotation is int:
                        param_type = "integer"
                    elif param.annotation is float:
                        param_type = "number"
                    elif param.annotation is bool:
                        param_type = "boolean"
                    elif param.annotation is list:
                        param_type = "array"
                    elif param.annotation is dict:
                        param_type = "object"
                properties[param_name] = {"type": param_type}
                if param.default is inspect.Parameter.empty:
                    required.append(param_name)

            schema: dict[str, Any] = {
                "description": (func.__doc__ or "").strip(),
                "properties": properties,
                "required": required,
            }

            self._tool_registry.register(
                name=func.__name__,
                schema=schema,
                handler=func,
                toolset=toolset,
                requires=requires,
            )

            # The agent is rebuilt on every run() call, so no cache
            # invalidation is needed here.
            return func

        return decorator
