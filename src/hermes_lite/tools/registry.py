"""Tool registry — stores tool definitions and dispatches invocations.

Tools are grouped into named toolsets (e.g. 'terminal', 'file', 'memory').
Each tool can declare runtime requirements via a callable `requires` check.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from pydantic_ai.tools import Tool


class ToolRegistry:
    """Registry for tools with toolset grouping and requirement guards.

    Tools are registered with a name, JSON Schema description, handler callable,
    optional toolset label, and an optional requirement checker.

    Usage::

        registry = ToolRegistry()
        registry.register(
            name="run_shell",
            schema={"command": {"type": "string"}},
            handler=lambda command: subprocess.run(command, capture_output=True, text=True).stdout,
            toolset="terminal",
            requires=lambda: shutil.which("bash") is not None,
        )
    """

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        schema: dict[str, Any],
        handler: Callable[..., Any],
        toolset: str = "default",
        requires: Callable[[], bool] | None = None,
    ) -> None:
        """Register a tool.

        Args:
            name: Unique tool name.
            schema: JSON Schema dict describing the tool parameters.
            handler: Async or sync callable that executes the tool.
            toolset: Logical group for filtering (default, terminal, file, etc.).
            requires: Optional callable returning True if the tool's prerequisites are met.
        """
        self._tools[name] = {
            "name": name,
            "schema": schema,
            "handler": handler,
            "toolset": toolset,
            "requires": requires,
        }

    def get_schemas(self, enabled_toolsets: set[str] | None = None) -> list[dict[str, Any]]:
        """Return tool schemas filtered by enabled toolsets.

        Only tools whose requirements are met (or have no requirements) and whose
        toolset is enabled are included.

        Args:
            enabled_toolsets: Set of toolset names to include. If None, all are included.

        Returns:
            List of tool schema dicts suitable for LLM function-calling definitions.
        """
        result: list[dict[str, Any]] = []
        for name, entry in self._tools.items():
            # Check toolset filter
            if enabled_toolsets is not None and entry["toolset"] not in enabled_toolsets:
                continue
            # Check requirements
            req = entry["requires"]
            if req is not None and not req():
                continue
            result.append({
                "name": name,
                "description": entry["schema"].get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": entry["schema"].get("properties", {}),
                    "required": entry["schema"].get("required", []),
                },
            })
        return result

    def dispatch(self, name: str, args: dict[str, Any]) -> str:
        """Execute a registered tool and return the result as a JSON string.

        Args:
            name: Tool name.
            args: Keyword arguments for the tool handler.

        Returns:
            JSON-encoded result string.

        Raises:
            KeyError: If the tool name is not registered.
        """
        entry = self._tools.get(name)
        if entry is None:
            return json.dumps({"error": f"Unknown tool: {name}"})
        handler = entry["handler"]
        try:
            result = handler(**args)
        except Exception as exc:
            return json.dumps({"error": str(exc)})
        if result is None:
            return json.dumps({"result": None})
        # Try to serialise; fall back to string representation
        try:
            return json.dumps({"result": result})
        except (TypeError, ValueError):
            return json.dumps({"result": str(result)})

    def list_tools(self) -> list[dict[str, str]]:
        """Return a compact listing of all registered tools.

        Returns:
            List of dicts with 'name' and 'toolset' keys.
        """
        return [
            {"name": e["name"], "toolset": e["toolset"]}
            for e in self._tools.values()
        ]

    def as_pydantic_tools(self) -> list[Tool[None]]:
        """Convert registered tools to pydantic-ai Tool objects.

        Uses Tool.from_function() to wrap handlers as structured tools.

        Returns:
            List of pydantic_ai Tool instances.
        """
        result: list[Tool[None]] = []
        for name, entry in self._tools.items():
            tool = Tool(
                entry["handler"],
                name=name,
                description=entry["schema"].get("description", ""),
                require_parameter_descriptions=False,
            )
            result.append(tool)
        return result
