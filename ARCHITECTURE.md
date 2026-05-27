# Hermes Lite — Architecture Specification

A lightweight agent framework built on Pydantic AI. Single-file simplicity where possible,
module boundaries where necessary.

## Project Structure

```
hermes-lite/
├── pyproject.toml
├── src/hermes_lite/
│   ├── __init__.py
│   ├── agent.py          # Core agent loop
│   ├── providers/
│   │   ├── __init__.py   # Provider factory + base
│   │   └── adapters.py   # OpenAI / Anthropic / DeepSeek adapters
│   ├── tools/
│   │   ├── __init__.py
│   │   └── registry.py   # Tool registry with toolset grouping
│   ├── memory/
│   │   ├── __init__.py
│   │   └── manager.py    # SQLite-backed persistent memory
│   ├── skills/
│   │   ├── __init__.py
│   │   └── manager.py    # File-based skill system (load/create/patch)
│   ├── sessions/
│   │   └── manager.py    # Session persistence + search
│   └── compression.py    # Context window compression
```

## Component Specs

### 1. providers/ — LLM Provider Abstraction

- `ProviderConfig`: model name, api_key, base_url, context_window
- `ProviderFactory.create(config) -> Agent`: returns a configured Pydantic AI Agent
- Support: OpenAI, Anthropic, DeepSeek, OpenRouter (all OpenAI-compatible)
- Anthropic adapter internally converts OpenAI format to Anthropic native

### 2. tools/registry.py — Tool Registry

- `ToolRegistry` class:
  - `register(name, schema, handler, toolset="default", requires=None)`
  - `get_schemas(enabled_toolsets) -> list[dict]` — only returns tools whose requirements are met
  - `dispatch(name, args) -> str` — execute a tool, returns JSON
- Built-in toolsets: "terminal", "file", "memory", "skills", "sessions"
- `check_requirements()` pattern: each tool has a callable that returns bool

### 3. core/agent.py — Agent Loop

- `HermesAgent` class:
  - `run(user_input, max_turns=50) -> str`
  - Internal loop: call LLM → if tool_calls → dispatch → append results → repeat
  - `result_type` support for structured output via Pydantic model
  - Automatic prompt caching awareness
- `build_system_prompt()` — assembles: persona + memory injection + skill index + tool schemas

### 4. memory/manager.py — Memory System

- SQLite schema: `(id, target, content, created_at, updated_at)`
- `target` is 'user' or 'memory'
- `inject(limit=10) -> str` — returns compact memory for system prompt
- `save(content, target)` — upsert
- `replace(old_text, new_text)` — targeted update
- `remove(old_text)` — delete by content match
- Deduplication: skip if content is >90% similar to existing entry

### 5. skills/manager.py — Skill System

- Skills stored as Markdown files: `skills/<name>/SKILL.md`
- YAML frontmatter: name, description, version
- `index() -> str` — returns compact list (name + description only)
- `load(name) -> str` — full SKILL.md content
- `create(name, content)` — write new skill file
- `patch(name, old_string, new_string)` — targeted edit
- `delete(name)` — remove skill directory
- Auto-discovery: scans `skills/` directory on init

### 6. sessions/manager.py — Session Management

- SQLite schema for session records
- `save_session(session_id, messages)` — persist conversation
- `list_recent(limit=20)` — recent sessions
- `search(query) -> list` — FTS5 full-text search
- `load(session_id) -> list[messages]` — restore session

### 7. compression.py — Context Compression

- `should_compress(messages, max_tokens, threshold=0.5) -> bool`
- `compress(messages, keep_recent=10) -> list`:
  - Summarize old messages via LLM
  - Return [summary_system_msg, ...recent_messages]
- Token counting via tiktoken

## API Design

```python
from hermes_lite import HermesAgent, ProviderConfig, ToolRegistry

# 1. Set up provider
config = ProviderConfig(
    provider="openai",  # or anthropic, deepseek, openrouter
    model="gpt-4o",
    api_key="...",      # or from env
)

# 2. Create agent with tools
agent = HermesAgent(
    config=config,
    persona="You are a helpful coding assistant.",
)

# 3. Register tools
@agent.tool("terminal")
def run_shell(command: str) -> str:
    ...

# 4. Run
result = agent.run("Fix the bug in auth.py")
print(result)

# 5. Structured output
from pydantic import BaseModel
class BugReport(BaseModel):
    file: str; line: int; severity: str; fix: str

report = agent.run("Find bugs in auth.py", result_type=BugReport)
```

## Non-Functional Requirements

- All async by default (use asyncio)
- Zero global state — everything is instance-scoped
- Works with any OpenAI-compatible API
- Memory/skills/sessions directories configurable via env or constructor
- Python 3.11+ only (use `Self` type, `StrEnum`, etc.)
