"""Hermes Lite — A lightweight agent framework built on Pydantic AI."""

from pathlib import Path

# Auto-load .env from project root or current directory
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
    else:
        load_dotenv()  # fallback: search current dir
except ImportError:
    pass

from hermes_lite.agent import HermesAgent
from hermes_lite.compression import compress, estimate_tokens
from hermes_lite.coding.permissions import PermissionPolicy
from hermes_lite.coding.workspace import Workspace
from hermes_lite.memory.manager import MemoryManager
from hermes_lite.providers.adapters import ProviderConfig
from hermes_lite.sessions.manager import SessionManager
from hermes_lite.skills.manager import SkillManager
from hermes_lite.tools.builtin import register_builtin_tools
from hermes_lite.tools.coding import register_coding_tools
from hermes_lite.tools.registry import ToolRegistry

__all__ = [
    "HermesAgent",
    "ProviderConfig",
    "ToolRegistry",
    "Workspace",
    "PermissionPolicy",
    "MemoryManager",
    "SkillManager",
    "SessionManager",
    "compress",
    "estimate_tokens",
    "register_builtin_tools",
    "register_coding_tools",
]
