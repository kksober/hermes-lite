# Coding Agent Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clean-room coding-agent layer to Hermes Lite, covering workspace safety, permissions, shell/git/file tools, coding workflow prompts, context indexing, diagnostics, hooks/MCP scaffolding, and subagent/worktree orchestration.

**Architecture:** Keep the existing Pydantic AI agent loop and add a focused `hermes_lite.coding` package. Coding tools are registered as an opt-in toolset when a workspace is configured. Safety decisions flow through `Workspace` and `PermissionPolicy` before file writes or command execution.

**Tech Stack:** Python 3.11, Pydantic AI, pytest, stdlib subprocess/pathlib/shlex/json/ast, existing ToolRegistry and CLI.

---

## File Structure

- Create `src/hermes_lite/coding/__init__.py`: public exports for the coding layer.
- Create `src/hermes_lite/coding/workspace.py`: workspace root, path checks, protected paths, summaries.
- Create `src/hermes_lite/coding/permissions.py`: structured allow/deny/ask decisions and conservative policy.
- Create `src/hermes_lite/coding/shell.py`: subprocess runner with policy checks, timeouts, truncation, and JSON-ready results.
- Create `src/hermes_lite/coding/context.py`: file listing, text search, project map, file ranking.
- Create `src/hermes_lite/coding/patches.py`: exact text patch application.
- Create `src/hermes_lite/coding/git.py`: git status, diff, and worktree inspection helpers.
- Create `src/hermes_lite/coding/diagnostics.py`: Python syntax diagnostics and symbol extraction as the first diagnostics backend.
- Create `src/hermes_lite/coding/extensibility.py`: local hook and external tool configuration loading.
- Create `src/hermes_lite/coding/subagents.py`: planner/build/review role plans and worktree task descriptions.
- Create `src/hermes_lite/prompts/__init__.py`: prompt package marker.
- Create `src/hermes_lite/prompts/coding_agent.py`: additive coding-agent prompt fragment.
- Create `src/hermes_lite/tools/coding.py`: coding tool registration functions backed by `coding/*`.
- Modify `src/hermes_lite/__init__.py`: export key coding objects.
- Modify `src/hermes_lite/cli.py`: add `--workspace`, coding prompt/tool registration, `/status`, `/diff`, `/permissions`, `/projectmap`.
- Modify `src/hermes_lite/api.py`: optionally enable coding tools with `HERMES_WORKSPACE`.
- Modify `src/hermes_lite/tools/__init__.py`: export `register_coding_tools`.
- Create `tests/test_coding_workspace.py`: workspace path and protection behavior.
- Create `tests/test_coding_permissions_shell.py`: permission decisions and command runner behavior.
- Create `tests/test_coding_tools.py`: tool JSON contracts for read/list/search/patch/git.
- Create `tests/test_coding_context_diagnostics.py`: project map, ranking, diagnostics, symbols.
- Create `tests/test_coding_cli.py`: parser and runtime wiring checks.
- Create `tests/test_coding_extensibility_subagents.py`: hooks, external tool config, subagent plans.

## Task 1: Workspace Core

**Files:**
- Test: `tests/test_coding_workspace.py`
- Create: `src/hermes_lite/coding/__init__.py`
- Create: `src/hermes_lite/coding/workspace.py`

- [ ] **Step 1: Write failing tests**

```python
def test_workspace_rejects_outside_paths(tmp_path):
    ws = Workspace(tmp_path)
    check = ws.resolve("../outside.txt", operation="read")
    assert check.ok is False
    assert check.error == "outside_workspace"
```

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_workspace.py -q`

Expected: FAIL because `hermes_lite.coding` does not exist yet.

- [ ] **Step 3: Implement minimal workspace module**

Create `PathCheck` and `Workspace` with `resolve()`, `is_protected_path()`, `read_text()`, `write_text()`, `list_dir()`, and `summary()`.

- [ ] **Step 4: Verify tests pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_workspace.py -q`

Expected: PASS.

## Task 2: Permission and Shell Core

**Files:**
- Test: `tests/test_coding_permissions_shell.py`
- Create: `src/hermes_lite/coding/permissions.py`
- Create: `src/hermes_lite/coding/shell.py`

- [ ] **Step 1: Write failing tests**

```python
def test_policy_denies_destructive_command(tmp_path):
    policy = PermissionPolicy()
    decision = policy.decide_command("rm -rf build")
    assert decision.allowed is False
    assert decision.reason == "destructive_command"
```

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_permissions_shell.py -q`

Expected: FAIL because permission and shell modules are missing.

- [ ] **Step 3: Implement permission policy and command runner**

Implement `PermissionDecision`, `PermissionPolicy.summary()`, `decide_read()`, `decide_write()`, `decide_command()`, and `CommandRunner.run()`.

- [ ] **Step 4: Verify tests pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_permissions_shell.py -q`

Expected: PASS.

## Task 3: Context, Patch, and Git Helpers

**Files:**
- Test: `tests/test_coding_context_diagnostics.py`
- Create: `src/hermes_lite/coding/context.py`
- Create: `src/hermes_lite/coding/patches.py`
- Create: `src/hermes_lite/coding/git.py`

- [ ] **Step 1: Write failing tests**

```python
def test_apply_text_patch_replaces_exact_match(tmp_path):
    path = tmp_path / "app.py"
    path.write_text("print('old')\n", encoding="utf-8")
    ws = Workspace(tmp_path)
    result = apply_text_patch(ws, "app.py", "old", "new")
    assert result["ok"] is True
    assert path.read_text(encoding="utf-8") == "print('new')\n"
```

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_context_diagnostics.py -q`

Expected: FAIL because helper modules are missing.

- [ ] **Step 3: Implement helpers**

Implement file listing, text search, project map, file ranking, exact patch replacement, git status, git diff, and worktree listing.

- [ ] **Step 4: Verify tests pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_context_diagnostics.py -q`

Expected: PASS.

## Task 4: Coding Toolset

**Files:**
- Test: `tests/test_coding_tools.py`
- Create: `src/hermes_lite/tools/coding.py`
- Modify: `src/hermes_lite/tools/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
def test_coding_tools_register_workspace_status(tmp_path):
    registry = ToolRegistry()
    register_coding_tools(registry, Workspace(tmp_path), PermissionPolicy())
    names = {tool["name"] for tool in registry.list_tools()}
    assert "workspace_status" in names
    assert "apply_patch" in names
```

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_tools.py -q`

Expected: FAIL because `register_coding_tools` is missing.

- [ ] **Step 3: Implement tool registration**

Register JSON-returning handlers for `workspace_status`, `list_files`, `search_text`, `read_file`, `write_file`, `apply_patch`, `run_command`, `git_status`, `git_diff`, `project_map`, `python_diagnostics`, `python_symbols`, `external_tools`, `hook_status`, `subagent_plan`, and `worktree_status`.

- [ ] **Step 4: Verify tests pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_tools.py -q`

Expected: PASS.

## Task 5: Agent Workflow and CLI

**Files:**
- Test: `tests/test_coding_cli.py`
- Create: `src/hermes_lite/prompts/__init__.py`
- Create: `src/hermes_lite/prompts/coding_agent.py`
- Modify: `src/hermes_lite/cli.py`
- Modify: `src/hermes_lite/api.py`
- Modify: `src/hermes_lite/__init__.py`

- [ ] **Step 1: Write failing tests**

```python
def test_cli_parser_accepts_workspace(tmp_path):
    parser = build_parser()
    args = parser.parse_args(["--workspace", str(tmp_path)])
    assert args.workspace == str(tmp_path)
```

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_cli.py -q`

Expected: FAIL because `build_parser` and workspace wiring are missing.

- [ ] **Step 3: Implement prompt and CLI wiring**

Add coding prompt composition, parser extraction, workspace runtime construction, and slash commands for `/status`, `/diff`, `/permissions`, and `/projectmap`.

- [ ] **Step 4: Verify tests pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_cli.py -q`

Expected: PASS.

## Task 6: Extensibility and Subagent Roadmap Runtime

**Files:**
- Test: `tests/test_coding_extensibility_subagents.py`
- Create: `src/hermes_lite/coding/diagnostics.py`
- Create: `src/hermes_lite/coding/extensibility.py`
- Create: `src/hermes_lite/coding/subagents.py`

- [ ] **Step 1: Write failing tests**

```python
def test_subagent_plan_includes_clean_room_roles():
    plan = create_subagent_plan("fix tests")
    assert [task.role for task in plan.tasks] == ["planner", "builder", "reviewer"]
```

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_extensibility_subagents.py -q`

Expected: FAIL because extensibility and subagent modules are missing.

- [ ] **Step 3: Implement diagnostics, external config, hooks, and subagent plans**

Implement Python syntax diagnostics, Python symbol extraction, `.hermes/tools.json` loading, `.hermes/hooks.json` loading, hook status reporting, role-based subagent plans, and worktree task metadata.

- [ ] **Step 4: Verify tests pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_coding_extensibility_subagents.py -q`

Expected: PASS.

## Task 7: Full Verification

**Files:**
- Modify only if tests reveal integration defects.

- [ ] **Step 1: Run all tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/ -q`

Expected: all tests pass.

- [ ] **Step 2: Run git status and inspect diff**

Run: `git status --short`

Expected: only planned files are modified or added.

Run: `git diff --stat`

Expected: changes map to the design nodes.

## Self-Review Checklist

- The plan covers Node 1 through Node 9 with concrete modules and tests.
- No OpenCode source code or implementation details are copied.
- Every production module has at least one failing test before implementation.
- Existing generic Hermes Lite behavior remains available without `--workspace`.
- Coding mode is opt-in through CLI `--workspace` or API `HERMES_WORKSPACE`.
