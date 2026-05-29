# Coding Agent Evolution Design

## Status

Approved for design by the user on 2026-05-29.

## Goal

Evolve Hermes Lite from a lightweight general agent framework into a company-safe
coding agent with capabilities comparable in class to Claude Code or OpenCode,
without copying OpenCode source code, directory structure, or implementation
details.

## Scope

This design covers the first major evolution path: a clean-room Python
implementation built on the existing Hermes Lite architecture. It focuses on the
core coding-agent harness:

- Workspace-aware file and git operations
- Permission checks for reads, writes, and commands
- Safer shell execution with auditability
- Coding-specific tool surfaces
- Agent workflow instructions for planning, editing, verifying, and reporting
- CLI affordances needed for day-to-day coding work

Future phases such as LSP integration, MCP servers, hooks, subagents, and
worktree orchestration are included as roadmap nodes, but not in the first
implementation plan.

## Non-Goals

- Do not vendor or copy OpenCode source code.
- Do not reproduce OpenCode internal package layout, command names, or unique
  implementation details.
- Do not attempt to bypass company software scanning policies.
- Do not add IDE plugins, desktop apps, or browser UIs in the first phase.
- Do not build a broad provider marketplace; keep the existing provider adapter
  model and extend it only when needed.

## Existing Context

Hermes Lite already has these useful foundations:

- `HermesAgent` with a multi-turn Pydantic AI loop
- Provider adapters for OpenAI, Anthropic, DeepSeek, and OpenRouter
- A `ToolRegistry` that exposes grouped tools to the model
- Built-in `run_shell`, `read_file`, `write_file`, and `web_fetch` tools
- SQLite-backed memory and sessions
- File-based skills
- Context compression
- Interactive CLI and FastAPI API
- Passing baseline tests: 62 tests pass

The current gap is not the base agent loop. The gap is the coding-agent harness:
workspace boundaries, patch-oriented edits, command lifecycle management,
permissions, git awareness, project context discovery, and verification
workflow.

## High-Level Architecture

Hermes Lite should keep its current Python package shape and add a focused
coding layer:

```text
src/hermes_lite/
  coding/
    workspace.py       # Workspace root, path resolution, protected paths
    permissions.py     # Allow/ask/deny decisions and audit events
    shell.py           # Command execution policy, timeouts, output limits
    patches.py         # Patch application helpers and edit validation
    git.py             # Git status/diff helpers
    context.py         # Search, file listing, project summary helpers
  tools/
    coding.py          # Tool registrations backed by coding/*
  prompts/
    coding_agent.py    # Coding-agent system prompt fragments
```

The existing generic tools can remain for compatibility, but the CLI and API
should prefer the new coding tools when a workspace is configured.

## Core Components

### Workspace Core

`Workspace` owns the root directory and all path decisions. It resolves relative
and absolute paths, rejects writes outside the root, blocks protected paths, and
normalizes tool responses. File tools must use this layer instead of resolving
paths directly.

Initial protected paths:

- `.git/`
- `.env`
- `.env.*`
- private key files such as `id_rsa`, `id_ed25519`, and `*.pem`
- dependency and cache directories such as `.venv/`, `node_modules/`,
  `.pytest_cache/`, and `__pycache__/`

Reads can be less restrictive than writes, but sensitive files remain blocked
unless an explicit future policy allows them.

### Permission Core

`PermissionPolicy` decides whether a requested operation is allowed, denied, or
requires user approval. The first implementation should be non-interactive and
conservative:

- Safe reads inside the workspace are allowed.
- Writes inside the workspace are allowed only for non-protected paths.
- Writes outside the workspace are denied.
- Shell commands default to allow for low-risk commands and deny for destructive
  commands.
- Network commands are not specially enabled in phase 1.

The policy should return structured decisions so a later interactive approval
UI can be added without changing tool contracts.

### Shell Runtime

`CommandRunner` wraps subprocess execution with:

- `shell=False` by default
- configurable working directory under the workspace
- timeout
- stdout/stderr capture
- output truncation with clear metadata
- exit code reporting
- command classification through the permission policy

Long-running PTY sessions are deferred to a later node. The first version should
be reliable for tests, formatters, `git`, `rg`, and simple build commands.

### Coding Tools

The new coding toolset should expose model-friendly tools:

- `workspace_status`
- `list_files`
- `search_text`
- `read_file`
- `apply_patch`
- `write_file`
- `run_command`
- `git_status`
- `git_diff`

These tools should return JSON strings with stable fields, not ad hoc prose.
Stable responses make the agent loop easier to debug and test.

### Agent Workflow

The coding prompt should instruct the model to:

- Inspect project files before changing code.
- Prefer `rg` for search.
- Make minimal, focused edits.
- Preserve unrelated user changes.
- Use patch-oriented edits for existing files.
- Run focused tests after changes.
- Summarize modified files and verification results.
- Never claim success without verification output.

The prompt should be an additive persona fragment, not a fork of the existing
agent loop.

### CLI Integration

The CLI should accept a workspace path and enable coding tools:

```bash
hermes-lite --workspace /path/to/project
```

Useful first commands:

- `/status` shows workspace, provider, model, git state, and permission mode.
- `/diff` shows current git diff summary.
- `/tools` includes coding tools.
- `/permissions` shows the active policy summary.

Existing chat behavior should continue to work without a workspace.

## Data Flow

1. User starts Hermes Lite with `--workspace`.
2. CLI creates `Workspace`, `PermissionPolicy`, `CommandRunner`, and coding
   tool registrations.
3. `HermesAgent.build_system_prompt()` includes the coding prompt fragment and
   current workspace summary.
4. The model calls coding tools through `ToolRegistry`.
5. Each tool validates paths and permissions before performing work.
6. Tool results return structured JSON to the model.
7. The user receives a final response with changed files and verification.

## Error Handling

Errors should be explicit and recoverable:

- Path outside workspace: return `{"ok": false, "error": "outside_workspace"}`.
- Protected file write: return `{"ok": false, "error": "protected_path"}`.
- Permission denial: return `{"ok": false, "error": "permission_denied"}`.
- Command timeout: include timeout seconds, partial output, and exit metadata.
- Patch mismatch: include the target file and a short reason.
- Missing command: include the command name and working directory.

Tool handlers should not raise for expected user or model mistakes. They should
return structured failures and let the agent recover.

## Testing Strategy

Phase 1 should add unit tests before implementation code for:

- Workspace path resolution and outside-root rejection
- Protected path detection
- Permission decisions for reads, writes, and commands
- Command runner timeout, exit code, and output truncation
- File search and list behavior
- Patch application success and mismatch failure
- Git status and diff wrappers in a temporary git repo
- CLI argument parsing for `--workspace`

The existing test suite must keep passing.

## Roadmap Nodes

### Node 1: Workspace Core

Deliver a workspace abstraction, path safety, protected path rules, and basic
workspace summary. This makes every later coding capability safer.

### Node 2: Permission Core

Deliver allow/deny/ask decision objects and non-interactive conservative policy.
This provides an audit-ready foundation before stronger shell and write tools.

### Node 3: Coding Tools

Deliver model-facing tools for file listing, search, reading, patching, writing,
command execution, and git inspection. Replace direct use of the older generic
file and shell tools in coding mode.

### Node 4: Agent Workflow

Deliver coding prompt fragments, CLI `--workspace`, and slash commands for
status, diff, and permission inspection.

### Node 5: Verification and Hardening

Deliver focused tests, docs, and regression checks for coding mode. This is the
minimum bar for internal use.

### Node 6: Context Indexing

Add project maps, file ranking, incremental summaries, and better compression
for large repositories.

### Node 7: LSP Diagnostics

Add optional language-server integration for diagnostics, definitions,
references, and symbol search.

### Node 8: MCP, Hooks, and Extensibility

Add MCP-compatible external tools, project hooks, and richer skill loading.

### Node 9: Subagents and Worktrees

Add isolated worktree execution, planner/builder/reviewer roles, and parallel
task execution.

## Architecture Decisions

### ADR 1: Clean-Room Implementation

Decision: Hermes Lite will not copy OpenCode source code. It will implement
similar user-facing capabilities using original Python code and the existing
Hermes Lite architecture.

Rationale: The target environment bans OpenCode. Clean-room implementation
reduces compliance risk, avoids scanner matches, and keeps internal behavior
auditable.

Trade-off: This is slower than vendoring an existing implementation, but it is
the only appropriate path for company machines.

### ADR 2: Central Workspace Boundary

Decision: All coding file and command tools depend on a `Workspace` object.

Rationale: Path rules scattered across tools are easy to bypass. A central
workspace layer gives consistent behavior and simpler tests.

Trade-off: Existing generic tools may remain less capable until migrated or
deprecated in coding mode.

### ADR 3: Structured Tool Results

Decision: Coding tools return stable JSON-shaped results.

Rationale: Agent recovery, testing, API integration, and UI display all benefit
from predictable fields.

Trade-off: Some responses are less human-friendly when inspected raw, but the
agent can translate them for the user.

### ADR 4: Conservative Shell First

Decision: Phase 1 uses simple subprocess execution with strict timeouts instead
of PTY sessions.

Rationale: Most coding verification needs deterministic commands first. PTY and
long-running session management add complexity and risk.

Trade-off: Interactive CLIs and dev servers are deferred to a later node.

## Risks and Mitigations

- Risk: The model edits protected files accidentally.
  Mitigation: Workspace and permission checks block protected paths before write.

- Risk: The model runs destructive commands.
  Mitigation: Command classification denies known destructive patterns in phase 1.

- Risk: The user expects Claude Code parity immediately.
  Mitigation: Ship in nodes, with each node producing working and tested
  behavior.

- Risk: OpenCode similarity causes company concerns.
  Mitigation: No source copying, no vendored OpenCode files, no dependency on
  OpenCode packages, and architecture documented as clean-room.

- Risk: Existing general-agent behavior regresses.
  Mitigation: Workspace mode is opt-in, and existing tests remain part of every
  verification pass.

## Acceptance Criteria for Phase 1

- `hermes-lite --workspace /path/to/repo` starts a coding-capable REPL.
- The agent can list, search, and read files inside the workspace.
- The agent can apply focused patches inside the workspace.
- The agent cannot write outside the workspace.
- The agent cannot write protected files by default.
- The agent can run simple commands with timeout and structured results.
- The agent can report git status and diff.
- CLI `/status`, `/diff`, and `/permissions` work in workspace mode.
- All existing tests pass.
- New tests cover the workspace, permissions, shell, tools, and CLI changes.
