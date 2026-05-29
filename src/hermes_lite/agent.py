"""Core agent loop — multi-turn conversation with tool dispatch.

The HermesAgent orchestrates: building system prompts, calling the LLM,
dispatching tool calls, injecting memory, and looping until the model
produces a final text response.
"""

from __future__ import annotations

import asyncio
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

    def _log_tool_failures(self, response_parts: list) -> None:
        """Log any tool failures found in the response parts."""
        for msg in response_parts:
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    content = str(part.content) if part.content else ""
                    if "error" in content.lower() or "failed" in content.lower():
                        tool_name = getattr(part, "tool_name", "unknown")
                        logger.warning("tool_failed tool=%s error=%s", tool_name, content[:200])

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
                parts.append(f"- {t['name']} [{t['toolset']}]")
            parts.append("</available_tools>")

        return "\n".join(parts)

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
                logger.info("stream_end total_messages=%d", len(final_messages))
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
