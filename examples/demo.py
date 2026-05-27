"""End-to-end demo of Hermes Lite agent framework.

Runs without API key (uses defer_model_check=True), demonstrating:
- Provider configuration
- Tool registration with toolset filtering
- Memory persistence
- Skill creation and loading
- Session save/search
- Context compression

Usage: .venv/bin/python examples/demo.py
"""

from hermes_lite import (
    HermesAgent,
    ProviderConfig,
    ToolRegistry,
    MemoryManager,
    SkillManager,
    SessionManager,
)
from hermes_lite.compression import estimate_tokens, should_compress, compress


def main():
    print("=" * 60)
    print("Hermes Lite — End-to-End Demo")
    print("=" * 60)

    # ── 1. Provider Config ──────────────────────────────────────
    print("\n[1] Provider Configuration")
    config = ProviderConfig(provider="openai", model="gpt-4o")
    print(f"    Provider: {config.provider}")
    print(f"    Model:    {config.model}")
    print(f"    Context:  {config.context_window:,} tokens")

    # ── 2. Tool Registry ────────────────────────────────────────
    print("\n[2] Tool Registry with toolset filtering")

    registry = ToolRegistry()

    registry.register(
        name="read_file",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=lambda path: f"Contents of {path}...",
        toolset="file",
    )

    registry.register(
        name="run_shell",
        schema={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        handler=lambda command: f"Ran: {command}",
        toolset="terminal",
    )

    registry.register(
        name="search_web",
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=lambda query: f"Search results for: {query}",
        toolset="web",
        requires=lambda: False,  # web search disabled
    )

    print(f"    All tools: {registry.list_tools()}")
    print(f"    File tools: {[t for t in registry.list_tools() if t['toolset'] == 'file']}")
    print(f"    Enabled (file+terminal): {len(registry.get_schemas({'file', 'terminal'}))} tools")
    print(f"    Enabled (all): {len(registry.get_schemas({'file', 'terminal', 'web'}))} tools")
    print(f"    (web tool hidden — requires=False)")

    # ── 3. Memory System ────────────────────────────────────────
    print("\n[3] Memory System (SQLite)")

    memory = MemoryManager(db_path=":memory:")
    memory.save("I am a Python developer who prefers type hints", target="user")
    memory.save("Project uses pytest for testing", target="memory")
    memory.save("Always use async/await patterns", target="memory")

    print(f"    Entries: {len(memory.list_all())}")
    print(f"    Injected:\n{memory.inject()}")
    print(f"    Dedup test: {memory.save('Always use async/await patterns', 'memory')}")
    print(f"    (duplicate blocked by >90% similarity check)")

    # ── 4. Skill System ─────────────────────────────────────────
    print("\n[4] Skill System (file-based)")

    import tempfile, os
    skills_dir = tempfile.mkdtemp(prefix="hl_skills_")
    skills = SkillManager(base_dir=skills_dir)

    skills.create(
        name="deploy",
        content="""---
name: deploy
description: Deployment workflow for the project
version: "1.0"
---

# Deploy Skill

1. Run all tests: `pytest`
2. Build Docker image: `docker build -t app .`
3. Push to registry: `docker push app`
4. Deploy: `kubectl apply -f deploy.yaml`
""",
    )

    skills.create(
        name="code-review",
        content="""---
name: code-review
description: Code review checklist
version: "1.0"
---

# Code Review Skill

- Check for type hints
- Verify test coverage
- Look for security issues
- Ensure async patterns are correct
""",
    )

    print(f"    Skills index:\n{skills.index()}")
    loaded = skills.load("deploy")
    print(f"    Loaded 'deploy' skill: {len(loaded)} chars")
    print(f"    Listed: {len(skills.list_all())} skills")

    # ── 5. Session Management ───────────────────────────────────
    print("\n[5] Session Management (SQLite + FTS5)")

    sessions = SessionManager(db_path=":memory:")
    sessions.save(
        session_id="demo-001",
        title="First demo session",
        messages_json='[{"role":"user","content":"Hello"},{"role":"assistant","content":"Hi there!"}]',
    )

    loaded_sess = sessions.load("demo-001")
    print(f"    Saved session: {loaded_sess['title']}")

    sessions.save(
        session_id="demo-002",
        title="Deploy discussion",
        messages_json='[{"role":"user","content":"How do I deploy with Docker?"}]',
    )

    recent = sessions.list_recent(limit=5)
    print(f"    Recent sessions: {len(recent)}")
    print(f"      - {recent[0]['title']}")

    results = sessions.search("Docker")
    print(f"    Search for 'Docker': {len(results)} result(s)")

    # ── 6. Context Compression ──────────────────────────────────
    print("\n[6] Context Compression")

    messages = [
        {"role": "system", "content": "You are an AI assistant."},
        {"role": "user", "content": "Explain Python decorators in detail."},
        {"role": "assistant", "content": "Decorators are functions that modify other functions..."},
        {"role": "user", "content": "Show me an example."},
        {"role": "assistant", "content": "Here's a simple decorator: @timer..."},
        {"role": "user", "content": "What about class-based decorators?"},
        {"role": "assistant", "content": "Class-based decorators use __call__..."},
    ]

    token_count = estimate_tokens(messages)
    print(f"    Message tokens: {token_count}")

    needs = should_compress(messages, max_tokens=token_count * 2)
    print(f"    Needs compression (at 50% threshold): {needs}")

    compressed = compress(messages, keep_recent=4)
    print(f"    Compressed: {len(compressed)} messages (was {len(messages)})")
    print(f"    First message role: {compressed[0]['role']}")

    # ── 7. Agent Construction ───────────────────────────────────
    print("\n[7] Full Agent Construction")

    agent = HermesAgent(
        config=config,
        persona="You are a helpful coding assistant.",
        tool_registry=registry,
        memory_manager=memory,
        defer_model_check=True,  # no API call on init
    )

    system_prompt = agent.build_system_prompt()
    print(f"    Agent created successfully")
    print(f"    Tools registered: {len(agent.tool_registry.list_tools())}")
    print(f"    System prompt length: {len(system_prompt)} chars")
    print(f"    Memory active: {agent.memory is not None}")

    print("\n" + "=" * 60)
    print("All systems operational!")
    print("=" * 60)


if __name__ == "__main__":
    main()
