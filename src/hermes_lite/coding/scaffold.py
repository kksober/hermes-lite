"""Project scaffolding — generate standard file structures for new projects."""
from __future__ import annotations

from typing import Any


_TEMPLATES: dict[str, dict[str, str]] = {
    "python-app": {
        "pyproject.toml": (
            '[project]\n'
            'name = "my-app"\n'
            'version = "0.1.0"\n'
            'requires-python = ">=3.11"\n'
            'dependencies = []\n\n'
            '[project.optional-dependencies]\n'
            'dev = ["pytest", "ruff", "mypy"]\n\n'
            '[tool.ruff]\n'
            'line-length = 100\n\n'
            '[tool.pytest.ini_options]\n'
            'testpaths = ["tests"]\n'
        ),
        "src/my_app/__init__.py": "",
        "src/my_app/main.py": (
            '"""Entry point for my-app."""\n\n'
            'def main() -> None:\n'
            '    print("Hello from my-app!")\n\n'
            'if __name__ == "__main__":\n'
            '    main()\n'
        ),
        "tests/__init__.py": "",
        "tests/test_main.py": (
            '"""Tests for main module."""\n'
            'from my_app.main import main\n\n\n'
            'def test_main_runs() -> None:\n'
            '    main()  # smoke test\n'
        ),
        ".hermes/rules.md": (
            "# Project Rules\n\n"
            "- Use type hints everywhere\n"
            "- Max line length 100\n"
            "- Tests must pass before committing\n"
        ),
    },
    "python-lib": {
        "pyproject.toml": (
            '[build-system]\n'
            'requires = ["hatchling"]\n'
            'build-backend = "hatchling.build"\n\n'
            '[project]\n'
            'name = "my-lib"\n'
            'version = "0.1.0"\n'
            'requires-python = ">=3.11"\n\n'
            '[project.optional-dependencies]\n'
            'dev = ["pytest", "ruff"]\n'
        ),
        "src/my_lib/__init__.py": (
            '"""my-lib — a Python library."""\n'
            '__version__ = "0.1.0"\n'
        ),
        "tests/__init__.py": "",
        "tests/test_my_lib.py": (
            '"""Tests for my-lib."""\n'
            'from my_lib import __version__\n\n\n'
            'def test_version() -> None:\n'
            '    assert __version__ == "0.1.0"\n'
        ),
    },
    "node-app": {
        "package.json": (
            '{\n'
            '  "name": "my-app",\n'
            '  "version": "0.1.0",\n'
            '  "type": "module",\n'
            '  "scripts": {\n'
            '    "test": "node --test",\n'
            '    "lint": "eslint ."\n'
            '  },\n'
            '  "devDependencies": {\n'
            '    "eslint": "^9.0.0"\n'
            '  }\n'
            '}\n'
        ),
        "src/index.js": (
            '// Entry point for my-app\n'
            'export function main() {\n'
            '  console.log("Hello from my-app!");\n'
            '}\n\n'
            'main();\n'
        ),
        "test/test_main.js": (
            'import { main } from "../src/index.js";\n\n'
            '// Basic smoke test\n'
            'main();\n'
        ),
    },
}


_TEMPLATE_LIST = sorted(_TEMPLATES.keys())


def scaffold_project(
    workspace_root: str,
    template: str,
    *,
    project_name: str = "",
) -> dict[str, Any]:
    """Generate project scaffold files from a built-in template.

    Parameters
    ----------
    workspace_root:
        Root directory to create files in.
    template:
        One of the keys from :func:`scaffold_list_templates`.
    project_name:
        Optional custom project name.

    Returns
    -------
    ``{ok, template, created: [file_path, ...]}``
    """
    from pathlib import Path

    if template not in _TEMPLATES:
        return {
            "ok": False,
            "error": "unknown_template",
            "available": _TEMPLATE_LIST,
            "message": f"Unknown template: {template}",
        }

    files = _TEMPLATES[template]
    root = Path(workspace_root)
    created: list[str] = []

    for rel_path, content in files.items():
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        target.write_text(content, encoding="utf-8")
        created.append(rel_path)

    return {
        "ok": True,
        "template": template,
        "created": created,
        "count": len(created),
    }


def scaffold_list_templates() -> dict[str, Any]:
    """Return the list of available scaffold templates."""
    return {
        "ok": True,
        "templates": _TEMPLATE_LIST,
    }
