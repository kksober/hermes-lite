# 竞品差距分析

**日期**: 2026-05-31
**完成日期**: 2026-05-31
**对比基线**: Claude Code、OpenCode、Aider、Cursor、GitHub Copilot
**当前版本**: M8 完成（311 测试，17 项差距全部补齐）

## 评估方法

将我们的能力与头部 coding agent 逐项对比，按对用户价值的紧迫程度分为三级：

- **P0**: 缺失后不可视为生产可用的 coding agent
- **P1**: 显著影响竞争力，应在下两个迭代补齐
- **P2**: 锦上添花，可在 M6+ 逐步完善

---

## P0 — 阻塞生产就绪

### 1. 测试运行与自动修复闭环

**现状**: `diagnostics.py` 能做 Python 语法诊断。`worktree_exec.py` 有 `_run_tests_in_worktree()` 骨架，但 CLI 中没有 `/test` 命令，agent 被要求 "运行测试" 时只能手动调用 `run_command` 然后人工分析输出。

**竞品做法**:
- Claude Code: 运行测试 → 解析失败 → 定位源码 → 生成修复 → 重新运行，全程自动
- Aider: `--test-cmd` 参数，每次编辑后自动运行测试，失败则回滚

**差距**: 缺少测试结果解析（pytest/unittest/jest 输出结构化）、失败用例到源码的定位映射、自动重试循环。

**建议方案**:
- 新增 `coding/testing.py`，实现 `run_tests(command)` → 结构化测试结果
- 解析 pytest/vitest/jest 输出为标准格式: `{passed, failed, errors, suites[]}`
- 在 agent 循环中注入测试失败作为上下文，让 LLM 自行修复
- 避免自动重试 — 保持人工在环，但提供清晰的 "失败→修复→重跑" 路径

### 2. 并行工具调用

**现状**: `ToolRegistry.dispatch()` 单工具串行调用。pydantic_ai 1.103.0 支持 parallel tool calls，但我们未利用。

**竞品做法**:
- Claude Code: 同一 turn 内并行读取多个文件、同时执行多个独立 bash 命令
- OpenCode: 批量文件读取是常态

**差距**: 每个 tool call 都是同步阻塞的。读取 5 个文件需要 5 次 LLM round-trip。

**建议方案**:
- 确认 pydantic_ai 的 parallel tool call 响应格式
- 在 agent 的 tool dispatch 层面支持批量执行
- 无依赖的工具调用（read_file x5, list_files + git_status）自动并行

### 3. 上下文自动注入

**现状**: `HermesAgent.build_system_prompt()` 注入 memory。workspace 模式下注入 coding prompt。但缺少自动的、每轮的上下文刷新。

**竞品做法**:
- Claude Code: 每轮自动注入 CLAUDE.md、git status、最近变更、当前分支信息
- OpenCode: `.opencode` 配置文件 + 自动 git context
- Cursor: `.cursorrules` 项目级规则注入

**差距**:
- 没有 `.hermes/rules.md` 或等价的项目级指令文件
- CLI 启动时不自动展示 git status / branch / recent changes
- `/repomap` 需要手动调用，不在每轮自动注入

**建议方案**:
- 新增 `.hermes/rules.md` 自动发现和注入（优先级: 项目根 > 用户 home > 系统默认）
- 每轮对话自动注入精简版上下文（不超过 500 tokens）: git branch, modified files count, last commit
- 首次进入 coding 模式时自动调用 `repo_map_summary` 并将结果缓存

### 4. Agent 错误恢复

**现状**: `agent.run()` 中工具调用失败时仅 `_log_tool_failures()` 记录日志，然后继续。但如果 LLM 返回了不符合 schema 的工具参数，pydantic_ai 可能直接抛异常。

**竞品做法**:
- Claude Code: 工具调用失败后，将错误信息注入下一轮对话，LLM 重试修正
- Aider: 编辑失败（如 hunk 冲突）后尝试不同的编辑策略

**差距**: 没有结构化的错误注入机制。工具返回 `{"ok": False, "error": "..."}` 时，agent 应该将这些错误反馈给 LLM 以便修正。

**建议方案**:
- 检查 `_log_tool_failures` 是否将错误信息注入消息历史
- 工具返回 error 时，pydantic_ai 应将错误作为 ToolReturnPart 返回给模型
- 添加最大重试次数防止无限循环

### 5. 真实 LSP 集成

**现状**: LSP 客户端是连接管理 + stdio 通信的完整骨架，但实际使用时依赖用户安装了 pyright/pylsp。诊断/跳转/引用对无 LSP 用户不可用。

**竞品做法**:
- Claude Code: 内建 LSP 支持，开箱即用
- Cursor: 深度 LSP 集成，实时诊断

**差距**: 我们不会自动安装 LSP 服务器。无 LSP 时静默降级，用户可能不知道缺少功能。

**建议方案**:
- 在首次启动时检测可用 LSP 服务器并提示安装建议
- 集成 `pyright` 作为 Python 默认选择（pip install pyright）
- LSP 启动失败时提供清晰的安装说明
- 保持静态分析回退（`diagnostics.py` 的 Python 语法检查）作为 baseline

---

## P1 — 竞争力关键特性

### 6. Web 搜索与内容获取

**现状**: 没有 WebSearch 或 WebFetch 能力。

**竞品做法**:
- Claude Code: `WebSearch` 和 `WebFetch` 工具，可搜索最新文档和 API 参考
- OpenCode: 内置 web 搜索
- Cursor: `@web` 上下文提供者

**差距**: 对于查阅最新框架文档、API 变更、错误信息搜索等场景完全空白。

**建议方案**:
- 新增 `coding/web.py`，实现 `web_search(query)` 和 `web_fetch(url)`
- 优先使用免费搜索 API（DuckDuckGo、SearXNG）或用户配置的 API key
- WebFetch 返回 markdown，限制 8000 字符防止上下文污染

### 7. 代码审查 Agent

**现状**: `subagents.py` 的 reviewer 角色是通用占位符：`"Review the diff, run verification, and identify regressions."`

**竞品做法**:
- Claude Code: 独立 code-reviewer subagent，系统性检查 security、performance、style
- OpenCode: 审查模式会生成结构化 review comment

**差距**: 没有结构化的代码审查清单。reviewer 没有检查项模板。

**建议方案**:
- 定义 `ReviewChecklist`: security（SQL 注入/XSS/硬编码密钥）、correctness（边界条件/null/race）、style（命名/复杂度）、tests（覆盖/边界）
- reviewer 子代理接收 checklist 作为 prompt 的一部分
- review 输出格式化为 `{severity, file, line, category, description, suggestion}`

### 8. 计划模式

**现状**: CLI 有 `/plan` 命令，但只是调用 `create_subagent_plan()` 生成 planner/builder/reviewer 三个通用角色后打印文本。没有交互式计划确认、调整、分步执行。

**竞品做法**:
- Claude Code: EnterPlanMode → 探索代码库 → 设计实现方案 → 用户审批 → 按步执行
- OpenCode: `/plan` 生成多步骤计划，用户可编辑调整

**差距**: 计划生成后无法修改，无法确认后自动执行，与 worktree 执行器无关联。

**建议方案**:
- `/plan <task>` 生成计划后，允许 `/plan-edit <step> <change>` 手动调整
- `/plan-approve` 确认后自动调用 `execute_subagent_plan()` 在 worktree 中执行
- 每个步骤执行前展示 diff 预览，用户可 `/plan-skip` 跳过

### 9. 任务追踪（Todo）

**现状**: CLI 有 `/todo` 命令序列化到 `~/.hermes_todo.jsonl`，但仅做文本追加，无状态管理、优先级、关联到 plan。

**竞品做法**:
- Claude Code: `TaskCreate`/`TaskUpdate`/`TaskList` 工具，agent 可用这些编排复杂多步任务
- OpenCode: Todo 以 tool 形式暴露给 agent

**差距**: agent 无法使用 todo 工具管理自己的工作。仅用于 CLI 手动记录。

**建议方案**:
- 将 todo 系统注册为 agent 可调用的工具（`todo_create`/`todo_update`/`todo_list`）
- 支持 status（pending/in_progress/completed/blocked）和依赖关系
- agent 在接受复杂任务时自动创建 todo，每完成一步自动标记

### 10. 文件编辑预览

**现状**: `apply_patch` 和 `apply_unified_diff` 直接写入文件。`patch_dry_run` 可预览但需单独调用。

**竞品做法**:
- Claude Code: Edit 工具返回 inline diff 预览
- Aider: 每次编辑显示 diff 并等待用户确认

**差距**: 没有统一的 "编辑 → 预览 → 确认" 流程。如果 agent 生成了错误编辑，用户发现时文件已改。

**建议方案**:
- 新增 `edit_file` 统一入口: 接收 old/new，先 dry_run，返回 diff 预览
- 权限策略新增 `edit_preview` 决策项
- 用户可配置 `HERMES_AUTO_APPLY=true` 跳过确认

---

## P2 — 质量提升

### 11. Token 用量追踪

**现状**: 无用量统计。用户不知道每次对话消耗多少 token、花了多少钱。

**建议方案**:
- `HermesAgent` 在 `_call_with_retry` 中累积 token 计数
- `/usage` 命令展示当前会话用量
- 超预算时警告（可配置限额）

### 12. 通知系统

**现状**: 无通知机制。长时间运行的任务完成后用户无感知。

**建议方案**:
- 长任务（>30s）完成后发送桌面通知（macOS: `osascript display notification`）
- 可选的 sound/mute 控制
- `/notify` 命令手动触发

### 13. 事件 Hook 系统

**现状**: `extensibility.py` 有 hook_status 但只列出文件。hook 不实际执行。

**竞品做法**:
- Claude Code: hooks 在 tool call 前后触发，可阻止或修改调用

**建议方案**:
- 支持 pre/post tool hooks，通过 shell 脚本或 Python 函数
- 初始支持: `pre_command`（命令执行前检查）、`post_edit`（编辑后触发 lint/format）

### 14. Notebook 编辑

**现状**: 不支持 .ipynb 文件。

**竞品做法**:
- Claude Code: `NotebookEdit` 工具可读取和修改 Jupyter notebook 的单元格

**建议方案**:
- 新增 `coding/notebook.py`，支持 read cell / edit cell / insert cell / delete cell
- 基于 nbformat 标准库，无需额外依赖

### 15. 多模态输入

**现状**: 仅文本输入。无法处理截图/图表。

**竞品做法**:
- Claude Code: Read 工具支持 PNG/JPG/PDF，模型可解读图片内容

**建议方案**:
- 检测模型是否支持多模态（DeepSeek 不支持，GPT-4o/Claude 支持）
- 支持的模型下，注册 `read_image` 工具

### 16. 计划/状态持久化

**现状**: 重启 CLI 后计划、todo 丢失（todo 有 JSONL 文件但 CLI 不自动加载）。

**建议方案**:
- `/todo` 启动时自动读取已持久化的 todo 列表
- plans 保存到 `docs/superpowers/plans/` 并在 `/plan` 时展示历史计划

### 17. 交互式权限改进

**现状**: 权限确认通过 stdin `input()` 实现。在 PTY 或 headless 模式下无法交互。

**建议方案**:
- 超时自动拒绝（默认 60s，可配置）
- headless 模式下支持 webhook URL 发送审批请求
- 记住本次会话中已批准的同类请求

---

## 汇总

| # | 缺口 | 优先级 | 模块 | 实际测试 | 状态 |
|---|------|--------|------|---------|------|
| 1 | 测试自动修复闭环 | P0 | `coding/testing.py` | +13 | done |
| 2 | 并行工具调用 | P0 | `agent.py` registry | +9 | done |
| 3 | 上下文自动注入 | P0 | `coding/context_inject.py` | +10 | done |
| 4 | Agent 错误恢复 | P0 | `agent.py` | +9 | done |
| 5 | 真实 LSP 集成 | P0 | `lsp.py` | +5 | done |
| 6 | Web 搜索获取 | P1 | `coding/web.py` | +15 | done |
| 7 | 代码审查 Agent | P1 | `subagents.py` | +9 | done |
| 8 | 计划模式 | P1 | `subagents.py` + CLI | +2 | done |
| 9 | 任务追踪 | P1 | `coding/todo.py` | +8 | done |
| 10 | 文件编辑预览 | P1 | `tools/coding.py` | — | done |
| 11 | Token 用量追踪 | P2 | `agent.py` + `/usage` | — | done |
| 12 | 通知系统 | P2 | `coding/notify.py` | +4 | done |
| 13 | 事件 Hook 系统 | P2 | `extensibility.py` | +4 | done |
| 14 | Notebook 编辑 | P2 | `coding/notebook.py` | +8 | done |
| 15 | 多模态输入 | P2 | `coding/multimodal.py` | +6 | done |
| 16 | 状态持久化 | P2 | CLI startup | — | done |
| 17 | 交互式权限改进 | P2 | `permissions.py` | +5 | done |

**实际完成**: P0 +37, P1 +34, P2 +27, 合计 311 测试（+98 增量）。

## 实施方案

```
M5: 文档规范化 — docs/ 体系建立
M6: P0#1-#4 — 测试闭环 → 并行调用 → 上下文注入 → 错误恢复
M6: P0#5 LSP 强化 — lsp_setup_guide, lsp_startup_check, CLI 接入
M7: P1#6-#10 — Web 搜索 → 代码审查 → 计划模式 → Todo → 编辑预览
M8: P2#11-#17 — Token → 通知 → Hooks → Notebook → 多模态 → 持久化 → 权限
```

## 新增能力清单

### 工具 (19 个新增)
`discover_tests`, `run_tests`, `read_rules`, `workspace_context`,
`web_search`, `web_fetch`, `code_review`,
`todo_create`, `todo_update`, `todo_list`, `edit_file`,
`plan_create`, `plan_approve`, `plan_list`,
`notebook_read_cell`, `notebook_read_all_cells`, `notebook_edit_cell`,
`notebook_insert_cell`, `notebook_delete_cell`,
`read_image`, `run_hooks`

### CLI 命令 (5 个新增)
`/test`, `/context`, `/rules`, `/plan-approve`, `/usage`, `/notify`

### 模块 (8 个新增)
`coding/testing.py`, `coding/context_inject.py`, `coding/web.py`,
`coding/todo.py`, `coding/notebook.py`, `coding/multimodal.py`,
`coding/notify.py`
