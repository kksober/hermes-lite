"""Tests for coding CLI wiring."""

from __future__ import annotations


def test_cli_parser_accepts_workspace(tmp_path) -> None:
    from hermes_lite.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["--workspace", str(tmp_path)])

    assert args.workspace == str(tmp_path)


def test_create_workspace_runtime_registers_coding_tools(tmp_path) -> None:
    from hermes_lite.cli import create_workspace_runtime
    from hermes_lite.tools.registry import ToolRegistry

    registry = ToolRegistry()
    runtime = create_workspace_runtime(str(tmp_path), registry)

    assert runtime is not None
    assert runtime.workspace.root == tmp_path.resolve()
    assert "workspace_status" in {tool["name"] for tool in registry.list_tools()}


def test_build_persona_adds_coding_prompt(tmp_path) -> None:
    from hermes_lite.cli import build_persona
    from hermes_lite.coding.permissions import PermissionPolicy
    from hermes_lite.coding.workspace import Workspace

    persona = build_persona(
        "Base persona.",
        workspace=Workspace(tmp_path),
        permission_policy=PermissionPolicy(),
    )

    assert "Base persona." in persona
    assert "coding agent" in persona.lower()
    assert str(tmp_path.resolve()) in persona
