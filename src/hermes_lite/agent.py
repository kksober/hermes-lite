"""Core agent loop — multi-turn conversation with tool dispatch.

The HermesAgent orchestrates: building system prompts, calling the LLM,
dispatching tool calls, injecting memory, and looping until the model
produces a final text response.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Literal

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)

from hermes_lite.memory.manager import MemoryManager
from hermes_lite.providers.adapters import ProviderConfig, create_agent
from hermes_lite.tools.registry import ToolRegistry


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
        memory_inject_limit: int = 10,
        defer_model_check: bool = False,
    ) -> None:
        """Initialise the agent.

        Args:
            config: Provider configuration.
            persona: System prompt persona text.
            tool_registry: Optional pre-configured ToolRegistry.
            memory_manager: Optional MemoryManager for persistent memory.
            memory_inject_limit: Max memory entries to inject into the system prompt.
            defer_model_check: Passed through to pydantic-ai Agent.
        """
        self._config = config
        self._persona = persona
        self._tool_registry = tool_registry or ToolRegistry()
        self._memory = memory_manager
        self._memory_inject_limit = memory_inject_limit
        self._defer_model_check = defer_model_check

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

    def _build_agent(self) -> Agent[None, str]:
        """Create (or recreate) the underlying pydantic-ai Agent."""
        return create_agent(
            self._config,
            system_prompt=self.build_system_prompt(),
            tools=self._tool_registry.as_pydantic_tools(),
            defer_model_check=self._defer_model_check,
        )

    @property
    def _pydantic_agent(self) -> Agent[None, str]:
        """Return the underlying pydantic-ai Agent, creating it lazily."""
        if not hasattr(self, "_pydantic_agent_cache"):
            self._pydantic_agent_cache = self._build_agent()
        return self._pydantic_agent_cache

    def build_system_prompt(self) -> str:
        """Assemble the full system prompt.

        Composed from: persona + injected memory + tool schemas.

        Returns:
            Complete system prompt string.
        """
        parts: list[str] = [self._persona]

        # Inject memory if available
        if self._memory is not None:
            mem_text = self._memory.inject(limit=self._memory_inject_limit)
            if mem_text:
                parts.append("\n" + mem_text)

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
    ) -> str:
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

        Returns:
            Final text response from the model.
        """
        # Rebuild system prompt in case memory/tools changed
        system_prompt = self.build_system_prompt()

        # Build initial message history
        messages: list[ModelMessage] = [
            ModelRequest(parts=[SystemPromptPart(content=system_prompt)]),
            ModelRequest(parts=[UserPromptPart(content=user_input)]),
        ]

        turn = 0
        while turn < max_turns:
            turn += 1

            # Call the pydantic-ai agent with accumulated history
            result = await self._pydantic_agent.run(
                user_prompt=None,
                message_history=messages,
                output_type=result_type if result_type else str,
            )

            # Use result.all_messages() — pydantic-ai guarantees correct
            # message ordering (tool results immediately follow tool_calls).
            messages = result.all_messages()

            # Extract the response parts
            response_parts = result.new_messages()
            if not response_parts:
                # If nothing was returned, try to use result.output directly
                return str(result.output) if result.output else ""

            # Collect tool calls and text from response
            has_tool_calls = False
            text_parts: list[str] = []

            for msg in response_parts:
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        has_tool_calls = True
                    elif isinstance(part, TextPart):
                        text_parts.append(part.content)

            # If we have text output and no tool calls, we're done
            if text_parts and not has_tool_calls:
                return "\n".join(text_parts)

            # If there are tool calls, pydantic-ai has already executed
            # them and result.all_messages() includes everything in order.
            # Continue the loop with the updated message history.
            if has_tool_calls:
                continue

            # No tool calls and no text — force break
            if result.output:
                return str(result.output)
            break

        # Fallback: use final result output
        return str(result.output) if result.output else ""

    async def run_stream(
        self,
        user_input: str,
        max_turns: int = 50,
    ) -> AsyncGenerator[str, None]:
        """Stream text output from the agent, yielding chunks as they are produced.

        The streaming loop is identical to :meth:`run` but yields text parts
        from each LLM turn as soon as they arrive.  Tool calls are handled
        transparently by pydantic-ai (auto-executed) and do not produce
        visible output — only final text responses are yielded.

        Args:
            user_input: The user's message.
            max_turns: Maximum tool-call iterations before forcing a response.

        Yields:
            Text chunks as they are produced by the model.
        """
        # Rebuild system prompt in case memory/tools changed
        system_prompt = self.build_system_prompt()

        # Build initial message history
        messages: list[ModelMessage] = [
            ModelRequest(parts=[SystemPromptPart(content=system_prompt)]),
            ModelRequest(parts=[UserPromptPart(content=user_input)]),
        ]

        turn = 0
        while turn < max_turns:
            turn += 1

            # Call the pydantic-ai agent with accumulated history
            result = await self._pydantic_agent.run(
                user_prompt=None,
                message_history=messages,
                output_type=str,
            )

            # Use result.all_messages() for correct message ordering
            messages = result.all_messages()

            # Extract the response parts
            response_parts = result.new_messages()
            if not response_parts:
                if result.output:
                    yield str(result.output)
                return

            # Collect tool calls and text from response
            has_tool_calls = False
            text_parts: list[str] = []

            for msg in response_parts:
                for part in msg.parts:
                    if isinstance(part, ToolCallPart):
                        has_tool_calls = True
                    elif isinstance(part, TextPart):
                        text_parts.append(part.content)

            # If we have text output and no tool calls, yield and finish
            if text_parts and not has_tool_calls:
                yield "\n".join(text_parts)
                return

            # If there are tool calls, pydantic-ai has already executed
            # them and result.all_messages() includes everything in order.
            # Continue the loop with the updated message history.
            if has_tool_calls:
                continue

            # No tool calls and no text — force break
            if result.output:
                yield str(result.output)
            break

        # Fallback: yield final result output
        if result.output:
            yield str(result.output)

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

            # Rebuild the cached pydantic agent with updated tools
            self._pydantic_agent_cache = self._build_agent()
            return func

        return decorator
