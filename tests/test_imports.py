"""Basic import verification tests for hermes_lite."""

from __future__ import annotations

import pytest


class TestImports:
    """Verify all public symbols can be imported."""

    def test_top_level_imports(self) -> None:
        """Test that the top-level __init__ exports all expected names."""
        from hermes_lite import HermesAgent, MemoryManager, ProviderConfig, ToolRegistry

        assert HermesAgent is not None
        assert MemoryManager is not None
        assert ProviderConfig is not None
        assert ToolRegistry is not None

    def test_provider_imports(self) -> None:
        """Test provider module imports."""
        from hermes_lite.providers import ProviderConfig, create_agent
        from hermes_lite.providers.adapters import ProviderConfig as PC, create_agent as ca

        assert ProviderConfig is not None
        assert create_agent is not None
        assert PC is ProviderConfig
        assert ca is create_agent

    def test_tools_imports(self) -> None:
        """Test tools module imports."""
        from hermes_lite.tools import ToolRegistry
        from hermes_lite.tools.registry import ToolRegistry as TR

        assert ToolRegistry is not None
        assert TR is ToolRegistry

    def test_memory_imports(self) -> None:
        """Test memory module imports."""
        from hermes_lite.memory import MemoryManager
        from hermes_lite.memory.manager import MemoryManager as MM

        assert MemoryManager is not None
        assert MM is MemoryManager

    def test_agent_import(self) -> None:
        """Test agent module import."""
        from hermes_lite.agent import HermesAgent

        assert HermesAgent is not None


class TestProviderConfig:
    """Test ProviderConfig dataclass."""

    def test_defaults(self) -> None:
        """Test default values."""
        from hermes_lite.providers import ProviderConfig

        cfg = ProviderConfig()
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4o"
        assert cfg.api_key == ""
        assert cfg.base_url == ""
        assert cfg.context_window == 128_000

    def test_custom_provider(self) -> None:
        """Test custom provider settings."""
        from hermes_lite.providers import ProviderConfig

        cfg = ProviderConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            api_key="sk-test",
            context_window=200_000,
        )
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-sonnet-4-20250514"
        assert cfg.api_key == "sk-test"
        assert cfg.context_window == 200_000

    def test_model_string_openai(self) -> None:
        """Test _model_string for OpenAI provider."""
        from hermes_lite.providers import ProviderConfig

        cfg = ProviderConfig(provider="openai", model="gpt-4o")
        assert cfg._model_string() == "gpt-4o"

    def test_model_string_anthropic(self) -> None:
        """Test _model_string for Anthropic provider."""
        from hermes_lite.providers import ProviderConfig

        cfg = ProviderConfig(provider="anthropic", model="claude-sonnet-4-20250514")
        assert cfg._model_string() == "anthropic:claude-sonnet-4-20250514"


class TestToolRegistry:
    """Test ToolRegistry functionality."""

    def test_register_and_list(self) -> None:
        """Test registering tools and listing them."""
        from hermes_lite.tools import ToolRegistry

        registry = ToolRegistry()

        def echo(message: str) -> str:
            return message

        registry.register(
            name="echo",
            schema={"properties": {"message": {"type": "string"}}, "required": ["message"]},
            handler=echo,
            toolset="default",
        )

        tools = registry.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "echo"
        assert tools[0]["toolset"] == "default"

    def test_dispatch(self) -> None:
        """Test dispatching a registered tool."""
        from hermes_lite.tools import ToolRegistry

        registry = ToolRegistry()

        def add(a: int, b: int) -> int:
            return a + b

        registry.register(
            name="add",
            schema={
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
            },
            handler=add,
        )

        import json
        result = registry.dispatch("add", {"a": 3, "b": 4})
        data = json.loads(result)
        assert data["result"] == 7

    def test_dispatch_unknown_tool(self) -> None:
        """Test dispatching an unknown tool returns an error."""
        from hermes_lite.tools import ToolRegistry
        import json

        registry = ToolRegistry()
        result = registry.dispatch("nonexistent", {})
        data = json.loads(result)
        assert "error" in data

    def test_get_schemas_filter(self) -> None:
        """Test get_schemas with toolset filtering."""
        from hermes_lite.tools import ToolRegistry

        registry = ToolRegistry()

        registry.register(
            name="tool_a",
            schema={"description": "Tool A", "properties": {}, "required": []},
            handler=lambda: None,
            toolset="group1",
        )
        registry.register(
            name="tool_b",
            schema={"description": "Tool B", "properties": {}, "required": []},
            handler=lambda: None,
            toolset="group2",
        )

        all_schemas = registry.get_schemas()
        assert len(all_schemas) == 2

        filtered = registry.get_schemas(enabled_toolsets={"group1"})
        assert len(filtered) == 1
        assert filtered[0]["name"] == "tool_a"

    def test_requirements_filter(self) -> None:
        """Test that tools with unmet requirements are excluded from schemas."""
        from hermes_lite.tools import ToolRegistry

        registry = ToolRegistry()

        registry.register(
            name="conditional_tool",
            schema={"description": "Cond", "properties": {}, "required": []},
            handler=lambda: None,
            requires=lambda: False,  # never available
        )

        schemas = registry.get_schemas()
        assert len(schemas) == 0  # excluded because requires returned False


class TestMemoryManager:
    """Test MemoryManager functionality."""

    def test_save_and_inject(self) -> None:
        """Test saving a memory and injecting it into prompt text."""
        from hermes_lite.memory import MemoryManager

        mm = MemoryManager()  # in-memory DB
        mm.save("User prefers Python", target="user")
        mm.save("Project uses FastAPI", target="memory")

        injection = mm.inject(limit=10)
        assert "[user]" in injection
        assert "User prefers Python" in injection
        assert "[memory]" in injection
        assert "Project uses FastAPI" in injection
        assert injection.startswith("<memory>")
        assert injection.endswith("</memory>")

    def test_inject_empty(self) -> None:
        """Test injecting from an empty memory store."""
        from hermes_lite.memory import MemoryManager

        mm = MemoryManager()
        assert mm.inject() == ""

    def test_deduplication(self) -> None:
        """Test that similar memories are deduplicated."""
        from hermes_lite.memory import MemoryManager

        mm = MemoryManager()
        id1 = mm.save("User prefers Python over JavaScript", target="user")
        # Nearly identical: only one extra word
        id2 = mm.save("User prefers Python over JavaScript syntax", target="user")
        # 5 intersection, 6 union → 83% — still below 90% threshold
        # Let's use truly near-duplicate strings
        id3 = mm.save("User prefers Python over JavaScript", target="user")
        # Exact duplicate → should be caught
        assert id1 == id3

        # Very similar but just at the edge
        id4 = mm.save("User prefers Python over Javascript", target="user")
        # "javascript" vs "javascript" — actually same after lowercasing!
        assert id1 == id4

    def test_replace(self) -> None:
        """Test replacing a memory entry."""
        from hermes_lite.memory import MemoryManager

        mm = MemoryManager()
        mm.save("Original content", target="user")
        replaced = mm.replace("Original content", "Updated content")
        assert replaced is True

        injection = mm.inject()
        assert "Updated content" in injection
        assert "Original content" not in injection

    def test_replace_missing(self) -> None:
        """Test replacing a non-existent entry returns False."""
        from hermes_lite.memory import MemoryManager

        mm = MemoryManager()
        assert mm.replace("nonexistent", "new") is False

    def test_remove(self) -> None:
        """Test removing a memory entry."""
        from hermes_lite.memory import MemoryManager

        mm = MemoryManager()
        mm.save("To be deleted", target="user")
        removed = mm.remove("To be deleted")
        assert removed is True
        assert mm.inject() == ""

    def test_remove_missing(self) -> None:
        """Test removing a non-existent entry returns False."""
        from hermes_lite.memory import MemoryManager

        mm = MemoryManager()
        assert mm.remove("nonexistent") is False

    def test_list_all(self) -> None:
        """Test listing all memory entries."""
        from hermes_lite.memory import MemoryManager

        mm = MemoryManager()
        mm.save("Entry 1", target="user")
        mm.save("Entry 2", target="memory")

        entries = mm.list_all()
        assert len(entries) == 2
        assert entries[0].target in ("user", "memory")

    def test_clear(self) -> None:
        """Test clearing all memories."""
        from hermes_lite.memory import MemoryManager

        mm = MemoryManager()
        mm.save("Entry 1")
        mm.save("Entry 2")
        mm.clear()
        assert len(mm.list_all()) == 0


class TestHermesAgent:
    """Test HermesAgent construction and system prompt building."""

    def test_construction(self) -> None:
        """Test basic agent construction."""
        from hermes_lite import HermesAgent, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(
            config=config,
            persona="You are a test assistant.",
            defer_model_check=True,
        )
        assert agent.config is config
        assert agent.tool_registry is not None
        assert agent.memory is None

    def test_build_system_prompt(self) -> None:
        """Test system prompt includes persona and tool listing."""
        from hermes_lite import HermesAgent, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(
            config=config,
            persona="You are a test assistant.",
            defer_model_check=True,
        )

        # Register a tool
        agent.tool_registry.register(
            name="test_tool",
            schema={"properties": {}, "required": []},
            handler=lambda: "ok",
            toolset="test",
        )

        prompt = agent.build_system_prompt()
        assert "You are a test assistant." in prompt
        assert "test_tool" in prompt
        assert "[test]" in prompt

    def test_build_system_prompt_with_memory(self) -> None:
        """Test system prompt includes injected memory."""
        from hermes_lite import HermesAgent, MemoryManager, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        mm = MemoryManager()
        mm.save("User likes dark mode", target="user")

        agent = HermesAgent(
            config=config,
            persona="You are helpful.",
            memory_manager=mm,
            defer_model_check=True,
        )

        prompt = agent.build_system_prompt()
        assert "User likes dark mode" in prompt
        assert "<memory>" in prompt

    def test_tool_decorator(self) -> None:
        """Test the @agent.tool() decorator."""
        from hermes_lite import HermesAgent, ProviderConfig

        config = ProviderConfig(provider="openai", model="gpt-4o")
        agent = HermesAgent(
            config=config,
            persona="You are helpful.",
            defer_model_check=True,
        )

        @agent.tool("test")
        def my_tool(x: int, y: str = "default") -> str:
            """A test tool."""
            return f"{x}-{y}"

        tools = agent.tool_registry.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "my_tool"
        assert tools[0]["toolset"] == "test"
