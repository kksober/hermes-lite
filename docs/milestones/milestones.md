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
