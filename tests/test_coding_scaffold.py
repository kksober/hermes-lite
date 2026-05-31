"""Tests for coding conventions and project scaffolding."""
from __future__ import annotations


def test_discover_conventions_found(tmp_path) -> None:
    from hermes_lite.coding.context_inject import discover_conventions

    (tmp_path / ".hermes").mkdir()
    (tmp_path / ".hermes" / "conventions.md").write_text("Use type hints.")
    result = discover_conventions(tmp_path)
    assert result["found"] is True
    assert "type hints" in result["content"]


def test_discover_conventions_not_found(tmp_path) -> None:
    from hermes_lite.coding.context_inject import discover_conventions

    result = discover_conventions(tmp_path)
    assert result["found"] is False


def test_scaffold_python_app(tmp_path) -> None:
    from hermes_lite.coding.scaffold import scaffold_project

    result = scaffold_project(str(tmp_path), "python-app")
    assert result["ok"] is True
    assert "pyproject.toml" in result["created"]
    assert "src/my_app/__init__.py" in result["created"]
    assert "tests/test_main.py" in result["created"]
    assert (tmp_path / "pyproject.toml").exists()


def test_scaffold_python_lib(tmp_path) -> None:
    from hermes_lite.coding.scaffold import scaffold_project

    result = scaffold_project(str(tmp_path), "python-lib")
    assert result["ok"] is True
    assert "src/my_lib/__init__.py" in result["created"]


def test_scaffold_node_app(tmp_path) -> None:
    from hermes_lite.coding.scaffold import scaffold_project

    result = scaffold_project(str(tmp_path), "node-app")
    assert result["ok"] is True
    assert "package.json" in result["created"]
    assert "src/index.js" in result["created"]


def test_scaffold_unknown_template(tmp_path) -> None:
    from hermes_lite.coding.scaffold import scaffold_project

    result = scaffold_project(str(tmp_path), "unknown")
    assert result["ok"] is False
    assert "available" in result


def test_scaffold_list_templates() -> None:
    from hermes_lite.coding.scaffold import scaffold_list_templates

    result = scaffold_list_templates()
    assert result["ok"] is True
    assert "python-app" in result["templates"]
    assert "python-lib" in result["templates"]
    assert "node-app" in result["templates"]


def test_scaffold_skips_existing_files(tmp_path) -> None:
    from hermes_lite.coding.scaffold import scaffold_project

    (tmp_path / "pyproject.toml").write_text("existing")
    result = scaffold_project(str(tmp_path), "python-app")
    assert result["ok"] is True
    assert "pyproject.toml" not in result["created"]
