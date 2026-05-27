"""FastAPI server for Hermes Lite — REST API with SSE streaming.

Usage::

    hermes-lite-api          # starts on 0.0.0.0:8000
    python -m hermes_lite.api
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from hermes_lite.agent import HermesAgent
from hermes_lite.memory.manager import MemoryManager
from hermes_lite.providers.adapters import ProviderConfig
from hermes_lite.skills.manager import SkillManager
from hermes_lite.tools.builtin import register_builtin_tools
from hermes_lite.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def _load_env() -> None:
    """Load .env from project root or current directory."""
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Request body for POST /chat."""

    message: str
    stream: bool = False


class MemoryAddRequest(BaseModel):
    """Request body for POST /memory."""

    content: str
    target: str = Field(default="memory", pattern=r"^(user|memory)$")


class MemoryDeleteRequest(BaseModel):
    """Request body for DELETE /memory."""

    content: str


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str
    model: str
    tools: str


class ChatResponse(BaseModel):
    """Response body for non-streaming POST /chat."""

    response: str


# ---------------------------------------------------------------------------
# App factory & shared state
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Hermes Lite API",
    description="REST API for the Hermes Lite agent framework",
    version="0.1.0",
)

_agent: HermesAgent | None = None
_memory: MemoryManager | None = None
_skills: SkillManager | None = None


def _get_agent() -> HermesAgent:
    """Return the shared agent instance, creating it lazily."""
    global _agent, _memory, _skills
    if _agent is None:
        _load_env()

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY not set in environment or .env file. "
                "Set it with: export DEEPSEEK_API_KEY=***"
            )

        config = ProviderConfig(
            provider="deepseek",
            model="deepseek-chat",
        )

        tools = ToolRegistry()
        register_builtin_tools(tools)

        _skills = SkillManager(base_dir="skills/")
        _memory = MemoryManager()

        _agent = HermesAgent(
            config=config,
            persona=(
                "You are Hermes Agent, an intelligent AI assistant created by "
                "Nous Research. You are helpful, knowledgeable, and direct. You "
                "assist users with a wide range of tasks including answering "
                "questions, writing and editing code, analyzing information, "
                "creative work, and executing actions via your tools. You "
                "communicate clearly, admit uncertainty when appropriate, and "
                "prioritize being genuinely useful over being verbose unless "
                "otherwise directed below. Be targeted and efficient in your "
                "exploration and investigations."
            ),
            tool_registry=tools,
            memory_manager=_memory,
        )
    return _agent


def _get_memory() -> MemoryManager:
    """Return the shared memory manager, creating the agent if needed."""
    _get_agent()  # ensures _memory is set
    assert _memory is not None
    return _memory


def _get_skills() -> SkillManager:
    """Return the shared skill manager, creating the agent if needed."""
    _get_agent()  # ensures _skills is set
    assert _skills is not None
    return _skills


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint — returns agent status and configuration."""
    try:
        agent = _get_agent()
        tools_list = agent.tool_registry.list_tools()
        tool_names = ", ".join(t["name"] for t in tools_list) if tools_list else "none"
        return HealthResponse(
            status="ok",
            model=f"{agent.config.provider}:{agent.config.model}",
            tools=tool_names,
        )
    except Exception as exc:
        return HealthResponse(status="error", model="", tools=str(exc))


@app.post("/chat")
async def chat(req: ChatRequest):
    """Chat endpoint — supports both non-streaming and streaming (SSE) modes.

    Set ``stream: true`` in the request body to receive a Server-Sent Events
    stream.  Each SSE event contains a JSON object with a ``text`` field.
    """
    agent = _get_agent()

    if req.stream:
        async def event_stream() -> AsyncGenerator[str, None]:
            """SSE generator yielding text chunks from the agent."""
            try:
                async for chunk in agent.run_stream(req.message):
                    payload = json.dumps({"text": chunk})
                    yield f"data: {payload}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:
                error_payload = json.dumps({"error": str(exc)})
                yield f"data: {error_payload}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming path
    try:
        response = await agent.run(req.message)
        return ChatResponse(response=response)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/memory")
async def get_memory():
    """List all stored memory entries."""
    memory = _get_memory()
    entries = memory.list_all()
    return {
        "count": len(entries),
        "entries": [
            {
                "id": e.id,
                "target": e.target,
                "content": e.content,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
            }
            for e in entries
        ],
    }


@app.post("/memory")
async def add_memory(req: MemoryAddRequest):
    """Add a new memory entry (or update timestamp if duplicate)."""
    memory = _get_memory()
    entry_id = memory.save(content=req.content, target=req.target)
    return {"status": "ok", "id": entry_id}


@app.delete("/memory")
async def delete_memory(req: MemoryDeleteRequest):
    """Delete a memory entry by exact content match."""
    memory = _get_memory()
    removed = memory.remove(req.content)
    if not removed:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {"status": "ok", "removed": True}


@app.get("/skills")
async def get_skills():
    """List all registered skills."""
    skills = _get_skills()
    return {"skills": skills.list_all()}


@app.get("/sessions")
async def get_sessions():
    """Return recent sessions (stub — SessionManager not wired by default).

    To enable sessions, set the ``HERMES_SESSIONS_DB`` env var to a path.
    """
    sessions_db = os.getenv("HERMES_SESSIONS_DB", "")
    if not sessions_db:
        return {"sessions": [], "note": "Sessions not configured. Set HERMES_SESSIONS_DB env var."}

    from hermes_lite.sessions.manager import SessionManager
    sm = SessionManager(db_path=sessions_db)
    return {"sessions": sm.list_recent()}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the FastAPI server via uvicorn."""
    import uvicorn

    host = os.getenv("HERMES_HOST", "0.0.0.0")
    port = int(os.getenv("HERMES_PORT", "8000"))

    uvicorn.run(
        "hermes_lite.api:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
