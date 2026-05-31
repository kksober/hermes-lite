# 里程碑

## M1: 核心 Agent 框架

**能力边界**: 多 provider 对话引擎 + 工具注册 + 持久记忆 + 技能系统 + 会话管理 + 上下文压缩

**模块**:
- `agent.py` — 多轮 agent 循环
- `providers/` — OpenAI/Anthropic/DeepSeek/OpenRouter 适配
- `tools/registry.py` — toolset 分组 + requirement 守卫
- `memory/` — SQLite 持久化
- `skills/` — 文件式技能系统
- `sessions/` — SQLite + FTS5 全文搜索
- `compression.py` — token 感知压缩

**测试**: 基础导入 + 工具注册 + 记忆 + 会话 + 压缩

---

## M2: Coding Agent 模式

**能力边界**: 工作区沙箱化 + 交互式权限 + 命令执行 + Git 操作 + 审计日志

**新增模块**:
- `coding/workspace.py` — 路径沙箱 + 敏感文件保护
- `coding/permissions.py` — 三级决策 + 会话授权
- `coding/shell.py` — 安全命令执行
- `coding/sessions.py` — PTY 长会话管理
- `coding/audit.py` — JSONL 审计日志
- `coding/git.py` — Git 操作封装
- `coding/extensibility.py` — Hook 和外部工具
- `coding/diagnostics.py` — Python 语法诊断

**测试增量**: +57（交互式权限 38 + 会话 19）

---

## M3: 编辑系统与上下文索引

**能力边界**: 统一 diff 补丁 + ripgrep 加速搜索 + 多因子文件排行 + 仓库地图

**新增/重写模块**:
- `coding/patches.py` — 多 hunk diff 补丁 + 模糊匹配 + dry-run
- `coding/context.py` — rg 加速搜索 + 文件排行 + repo map

**测试增量**: +36（编辑 18 + 上下文 18）

---

## M4: LSP / MCP / Worktree

**能力边界**: LSP 和 MCP 协议客户端 + Git worktree 隔离子代理执行

**新增模块**:
- `coding/lsp.py` — JSON-RPC LSP 客户端
- `coding/mcp_client.py` — JSON-RPC MCP 客户端
- `coding/worktree_exec.py` — Git worktree 隔离执行
- `coding/subagents.py` — 子代理编排（增强）

**测试增量**: +28（LSP/MCP 22 + worktree 6）

---

## M5: 生产加固

**能力边界**: 依赖兼容 + 全链路验证 + 文档体系

**变更**:
- pydantic_ai 1.103.0 兼容性修复（`Tool.from_schema()`）
- CLI 冒烟测试（11 工具 + DeepSeek API + 多轮对话）
- 中文 README 重写
- docs/ 文档体系建立（specs/iterations/verification/milestones）

**当前状态**: 213 个测试全绿，CLI 可用

---

## M6: P0 竞品差距补齐

**能力边界**: 测试修复闭环 + 并行工具调用 + 上下文注入 + 错误恢复 + LSP 强化

**新增/增强模块**:
- `coding/testing.py` — .venv 发现 + pytest 解析 + 失败定位
- `coding/context_inject.py` — .hermes/rules.md 发现 + workspace 快照
- `agent.py` — parallel_safe 标记 + 错误分类 + 并行提示构建
- `coding/lsp.py` — lsp_setup_guide + lsp_startup_check + /lsp 增强

**CLI 命令**: `/test`, `/context`, `/rules`

**测试**: 250 (+37)

---

## M7: P1 竞品差距补齐

**能力边界**: Web 搜索 + 代码审查 + 计划持久化 + 任务追踪 + 编辑预览

**新增模块**:
- `coding/web.py` — DuckDuckGo Lite 搜索 + URL 抓取
- `coding/todo.py` — JSONL 持久化任务追踪

**增强模块**:
- `coding/subagents.py` — ReviewChecklist + run_code_review + plan persist/approve
- `tools/coding.py` — edit_file 统一编辑入口

**CLI 命令**: `/plan-approve`, `/todo` 增强

**测试**: 284 (+34)

---

## M8: P2 竞品差距补齐

**能力边界**: Token 追踪 + 桌面通知 + Hook 执行 + Notebook + 多模态 + 状态持久化 + 权限增强

**新增模块**:
- `coding/notify.py` — osascript/notify-send 桌面通知
- `coding/notebook.py` — .ipynb 单元格 CRUD (5 tools)
- `coding/multimodal.py` — 图片/PDF base64 data-URI + 模型能力检测

**增强模块**:
- `agent.py` — usage 属性 + token 计数追踪
- `coding/extensibility.py` — run_hooks 执行
- `coding/permissions.py` — ask_timeout + headless_webhook
- `cli.py` — /usage, /notify, 启动时 todo/plan 摘要

**CLI 命令**: `/usage`, `/notify`

**测试**: 311 (+27). 竞品差距 17 项全部补齐.

---

## M9: P0 体验阻断层

**能力边界**: CLI 流式输出 + 终端 UI 着色 + 编辑确认流程 + Agent 错误纠错 + LLM 子代理

**新增/增强模块**:
- `cli.py` — `run_stream()` 路径接入 REPL + diff 着色 (`color_diff`) + 编辑确认交互
- `coding/permissions.py` — `PermissionPolicy.edit_confirm` 模式 + `edit_preview` 字段
- `agent.py` — `classify_tool_error` 修复（data=None）+ 错误计数 + 最大工具调用限制
- `tools/coding.py` — `_render_edit_preview()` + `_apply_patch_with_confirm()`
- `coding/subagents.py` — 子代理角色获得独立工具集（planner/builder/reviewer）

**CLI 命令**: `/test`, `/context`, `/rules`

**测试**: 339 (+28)

---

## M10: P1 竞争力差异层

**能力边界**: 语义搜索 + 上下文窗口管理 + 每轮刷新 + 会话持久化 + 编辑后自动工具链

**新增模块**:
- `coding/embeddings.py` — TF-IDF 语义代码搜索（`SemanticIndex` 类 + `semantic_search` 工具）
- `coding/conversation_store.py` — JSON 会话持久化（save/load/list/delete）

**增强模块**:
- `compression.py` — `ContextWindow` 类（自动压缩 80% 阈值 + `compress_if_needed`）
- `agent.py` — `ContextWindow` 集成 + `clear_context()` + `/resume` 消息恢复
- `context_inject.py` — `per_turn_context()` git/branch/file 摘要注入
- `extensibility.py` — `run_post_edit_hooks`（auto_trigger: post_edit）
- `cli.py` — `/clear` 命令 + `/resume` 恢复 + 每轮上下文注入 + 自动保存

**测试**: 378 (+39)

---

## M11: P2 高级能力层

**能力边界**: 编码规范引擎 + Debugger + 多项目管理 + 成本追踪 + Watch + 图表 + 安全审计

**新增模块**:
- `coding/scaffold.py` — 项目脚手架（python-app/python-lib/node-app 模板）
- `coding/watch.py` — 文件监视（`watch_status` 快照 + `watch_files` 轮询）

**增强模块**:
- `context_inject.py` — `discover_conventions()` + `.hermes/conventions.md` 注入
- `testing.py` — `debug_error()` traceback 源码映射（文件/行号/上下文）
- `agent.py` — `_MODEL_PRICING` 成本表 + `cost_estimate()` + `usage` 增强
- `cli.py` — `/cd <path>` + `/ref <path>` 多项目切换 + `/usage` 成本显示
- `tools/coding.py` — `_render_diagram()` Mermaid 图表生成支持
- `coding/subagents.py` — `security_audit()` pip-audit/npm audit 集成

**测试**: 400 (+22). Phase 2 竞品差距 17 项全部补齐.

---

## M12: 编辑精度 + Skill 闭环

**能力边界**: 模糊匹配 + 技能工具注册 + 文件查找 + 大文件保护

**新增/增强模块**:
- `coding/patches.py` — `_fuzzy_find()` 双策略模糊匹配（尾随空格容忍 + 缩进容忍）
- `coding/context.py` — `find_files()` glob 文件查找
- `coding/skills/manager.py` — `skill_view()` + `skill_manage()` 工具注册，从只读变为可写
- `tools/coding.py` — `find_files` + `skill_view` + `skill_manage` 工具注册；`read_file` 添加 `max_bytes=1_000_000` 保护
- `cli.py` — `create_workspace_runtime` 支持 `skill_manager` 参数
- `api.py` — `_skills` 创建移到 `register_coding_tools` 之前

**测试**: 417 (+17). Review 指出的 4 项编辑/技能缺口全部补齐.

---

## M13: 代码理解深度

**能力边界**: Python AST 解析 + 跨文件调用图 + 符号感知语义搜索

**新增模块**:
- `coding/ast_analysis.py` — 零依赖 Python 代码分析：`extract_symbols`（类/函数/参数/类型/装饰器/导入）、`build_call_graph`（跨文件 caller→callee 解析）、`find_references`（定义 + 引用 + callers）

**增强模块**:
- `coding/embeddings.py` — `index_files()` 支持 `symbols_per_file` 参数，TF-IDF 索引中函数/类名 2x 权重
- `coding/diagnostics.py` — `extract_python_symbols` 委托到 `ast_analysis.extract_symbols`，返回限定名方法（如 `Thing.method`）
- `coding/context.py` — `_enrich_symbol_counts()` 通过 `ast.walk` 扫描 Python 文件计数字段
- `tools/coding.py` — 注册 `code_structure`、`call_graph`、`find_symbol` 工具

**测试**: 430 (+13). 零新依赖.

---

## M14: 多文件编辑 + 知识闭环 + CLI 增强

**能力边界**: 原子性多文件编辑 + 对话回滚/重试 + 上下文手动压缩 + 知识自动提炼

**新增/增强模块**:
- `coding/patches.py` — `edit_batch()` 多文件原子编辑（dry-run-all → apply-all 策略，全或无语义）
- `tools/coding.py` — `edit_batch` 工具注册 + 权限检查 + 交互式预览
- `agent.py` — `_turn_count` 计数器 + `_reflection_interval`（默认 5 轮）+ `_snapshot_history()` / `undo_last_turn()` 对话回滚 + `_build_reflection_prompt()` 知识提炼提示
- `cli.py` — `/undo`（恢复消息快照）+ `/retry`（undo + 重发上次输入）+ `/compact`（手动压缩上下文）+ `_last_user_input` 追踪

**CLI 命令**: `/undo`, `/retry`, `/compact`

**测试**: 432 (+17). 7 轮 review 建议全部落地，多文件编辑有事务性保证.

---

**总览**:

| 里程碑 | 测试 | 状态 |
|--------|------|------|
| M1: 核心 Agent | 基础 | done |
| M2: Coding 模式 | +57 | done |
| M3: 编辑与索引 | +36 | done |
| M4: LSP/MCP/Worktree | +28 | done |
| M5: 生产加固 | 213 | done |
| M6: P0 补齐 | 250 | done |
| M7: P1 竞争力 | 284 | done |
| M8: P2 质量 | 311 | done |
| M9: P0 体验阻断 | 339 | done |
| M10: P1 竞争力差异 | 378 | done |
| M11: P2 高级能力 | 400 | done |
| M12: 编辑精度 + Skill 闭环 | 417 | done |
| M13: 代码理解深度 | 430 | done |
| M14: 多文件编辑 + 知识闭环 | 432 | done |
