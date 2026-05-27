"""Live integration test — uses DeepSeek API from .env.

Prerequisites:
    cp .env.example .env
    # Edit .env and add your DEEPSEEK_API_KEY

Usage:
    .venv/bin/python examples/live_test.py
"""

import asyncio
import os
import sys

from hermes_lite import HermesAgent, ProviderConfig, ToolRegistry, MemoryManager


async def main():
    # Check for API key
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key or key == "sk-your-key-here":
        print("ERROR: Set DEEPSEEK_API_KEY in .env file first.")
        print("  cp .env.example .env")
        print("  # edit .env with your real key")
        sys.exit(1)

    print("=" * 60)
    print("Hermes Lite — DeepSeek Live Test")
    print("=" * 60)

    # ── Setup ──
    config = ProviderConfig(
        provider="deepseek",
        model="deepseek-chat",  # DeepSeek V3
    )
    memory = MemoryManager()
    tools = ToolRegistry()

    # Register a simple calculator tool
    tools.register(
        name="calculate",
        schema={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Math expression to evaluate, e.g. '2+2*3'",
                }
            },
            "required": ["expression"],
        },
        handler=lambda expression: str(eval(expression)),
        toolset="utility",
    )

    agent = HermesAgent(
        config=config,
        persona="You are a helpful assistant. Keep answers concise.",
        tool_registry=tools,
        memory_manager=memory,
    )

    print(f"Provider: {config.provider}")
    print(f"Model:    {config.model}")
    print(f"Key:      {key[:8]}...{key[-4:]}")

    # ── Test 1: Basic chat ──
    print("\n--- Test 1: Basic Chat ---")
    try:
        result = await agent.run("Reply with exactly: HERMES_LITE_OK")
        print(f"Response: {result.strip()}")
    except Exception as e:
        print(f"ERROR: {e}")

    # ── Test 2: Tool use ──
    print("\n--- Test 2: Tool Use ---")
    try:
        result = await agent.run(
            "What is 123 * 456? Use the calculate tool."
        )
        print(f"Response: {result.strip()}")
    except Exception as e:
        print(f"ERROR: {e}")

    # ── Test 3: Memory ──
    print("\n--- Test 3: Memory ---")
    memory.save("The user's name is Ethan", target="user")
    result = await agent.run("What is my name?")
    print(f"Response: {result.strip()}")

    print("\n" + "=" * 60)
    print("All live tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
