# Hermes Lite

A lightweight agent framework built on [Pydantic AI](https://ai.pydantic.dev/).  
Inspired by the architecture of [Hermes Agent](https://github.com/NousResearch/hermes-agent).

## Features

- **Multi-Provider**: OpenAI, Anthropic, DeepSeek, OpenRouter — swap models with a config change
- **Multi-Turn Agent Loop**: Autonomous tool-calling loop with configurable max turns
- **Tool Registry**: Toolset-based grouping with requirement guards
- **Persistent Memory**: SQLite-backed — survives across sessions
- **Skill System**: File-based procedural knowledge with auto-discovery, load/create/patch
- **Session Management**: SQLite + FTS5 full-text search across past conversations
- **Context Compression**: Token-aware compression with LLM summarization

## Quick Start

```bash
# Install
pip install -e .

# Or with uv
uv pip install -e .
```

```python
import asyncio
from hermes_lite import HermesAgent, ProviderConfig, ToolRegistry, MemoryManager

async def main():
    config = ProviderConfig(provider="openai", model="gpt-4o")
    memory = MemoryManager()
    tools = ToolRegistry()

    # Register a tool
    tools.register(
        name="get_weather",
        schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        handler=lambda city: f"Weather in {city}: sunny, 22°C",
        toolset="utility",
    )

    agent = HermesAgent(
        config=config,
        persona="You are a helpful assistant.",
        tool_registry=tools,
        memory_manager=memory,
    )

    # Ask the agent — it will use the tool if needed
    result = await agent.run("What's the weather in Tokyo?")
    print(result)

asyncio.run(main())
```

## Architecture

```
src/hermes_lite/
├── agent.py          # Core multi-turn agent loop
├── compression.py    # Context window compression
├── providers/        # LLM provider adapters
├── tools/            # Tool registry with toolset grouping
├── memory/           # Persistent memory (SQLite)
├── skills/           # File-based skill system
└── sessions/         # Session persistence + search
```

## Development

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
python -m pytest tests/ -v
```
