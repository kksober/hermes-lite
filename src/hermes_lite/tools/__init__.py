"""Tool registry — register, discover, and dispatch tools."""

from hermes_lite.tools.coding import register_coding_tools
from hermes_lite.tools.registry import ToolRegistry

__all__ = [
    "ToolRegistry",
    "register_coding_tools",
]
