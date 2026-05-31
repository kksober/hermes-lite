# 竞品差距分析 — Phase 2

**日期**: 2026-05-31
**对比基线**: Claude Code、OpenCode、Aider、Cursor、GitHub Copilot
**当前版本**: M11 完成（400 测试，17 项 Phase 2 差距全部补齐，44 工具，41 源文件）

## 评估方法

Phase 1（M5-M8）补齐了基础功能层面的 17 项差距，让 Hermes Lite 具备 production-grade coding agent 的完整工具链。Phase 2 着眼于**体验深度**和**智能程度**——

- **P0**: 日常使用中立刻感受到的摩擦点，阻塞真实场景高效使用
- **P1**: 显著提升产出效率的差异化能力
- **P2**: 高级场景和长尾需求

---

## P0 — 体验阻断层

### 1. CLI 流式输出未接入

**现状**: `agent.py` 已实现 `run_stream()` 方法（pydantic_ai 原生流式），但 CLI 的 `run_repl()` 调用的是 `agent.run()`（阻塞等待全部结果后才输出）。用户输入后盯着空白屏幕数秒等待。

**竞品做法**:
- Claude Code: token 级实时流式输出，首 token 延迟 < 500ms
- OpenCode: 同样 token 级 streaming
- Aider: 实时显示 LLM 思考过程

**差距**: 
- `run_stream()` 已经有现成实现，但 CLI 没走流式路径
- 长回复时用户体验极差 — 10s+ 空白等待

**建议方案**:
- 改造 REPL 循环走 `run_stream()` 路径
- 首 token 前显示 spinner，之后逐字刷新
- 保留 `agent.run()` 作为 fallback（不支持流式的 provider）

**涉及**: `cli.py` REPL 循环

### 2. 终端 UI 可用性薄弱

**现状**: REPL 使用 prompt_toolkit 做输入历史，但输出是纯文本 — 没有语法高亮、diff 着色、错误格式化。30+ 行 diff 输出难以阅读。

**竞品做法**:
- Claude Code: diff 用 +/- 颜色标记，JSON 着色，错误红色高亮
- OpenCode: `rich` 库驱动的格式化面板
- Cursor: VS Code 原生 diff 视图

**差距**:
- `unified_diff` 输出无颜色，难以判断改了什么
- 错误信息与普通输出无视觉区分
- 长 JSON 输出无缩进着色

**建议方案**:
- 引入 `rich` 库做 diff 高亮、错误着色、JSON 格式化
- 或在现有 prompt_toolkit 基础上做终端 escape code 着色
- 最小方案: diff 输出 +/- 行分别用红/绿色 ANSI code

**涉及**: `cli.py` 输出封装

### 3. 编辑确认流程缺失

**现状**: `edit_file` 和 `apply_patch` 工具直接写文件。虽然有 `preview_only` 参数，但 agent 调用时通常跳过预览直接写入。没有 "预览 → 用户确认 → 应用" 的交互闭环。

**竞品做法**:
- Claude Code: Edit 工具返回 inline diff 预览，用户可视确认后再应用
- Aider: 每次文件编辑展示 diff 等待用户 y/n
- Cursor: 实时 preview 面板

**差距**: agent 可能产生错误编辑，用户发现时文件已改。即使 git 可回滚，心智负担高。

**建议方案**:
- 权限策略新增 `edit_confirm` 模式
- agent 编辑文件时，CLI 展示 diff 预览并等待 y/n
- auto-apply 模式（`HERMES_AUTO_EDIT=true`）跳确认
- 最小方案: CLI 拦截 write 类工具结果，diff 着色展示，等待确认

**涉及**: `permissions.py` + `cli.py` 工具结果处理

### 4. Agent 自我纠错循环薄弱

**现状**: `classify_tool_error()` 能分类工具错误为 retryable/non-retryable，但 agent 只在 `_log_tool_failures()` 中记录日志，未将错误信息结构化注入下一轮提示让 LLM 自我修正。

**竞品做法**:
- Claude Code: 工具失败的结果直接作为 tool result 返回给模型，模型看到 "error: permission_denied" 后会换方案
- Aider: hunk 冲突时尝试 fuzzy matching，失败后改用 search/replace

**差距**:
- 错误信息确实返回给 LLM（作为 ToolReturnPart），但缺少**纠错引导**——LLM 看到 error 但不一定知道怎么改
- 同一类型错误重复发生时没有升级策略（如连续 3 次 permission_denied 应告诉用户而不是死循环）

**建议方案**:
- 在工具错误结果中附加 `hint` 字段（已有 `classify_tool_error` 的 hint，确保它出现在 tool return 中）
- 实现错误计数器: 同一错误 >= 3 次时，注入强提示要求 agent 改变策略
- 避免无限重试循环 — 设置全局最大工具调用次数 / turn 限额

**涉及**: `agent.py` run loop + `coding.py` tool return 增强

### 5. 子代理执行过于原始

**现状**: `subagent_execute_with_commands()` 在 worktree 中执行预定义 shell 命令列表。planner/builder/reviewer 角色各跑固定命令（`echo`、`ls`、`git diff` 占位），没有真正的 LLM 驱动子代理。

**竞品做法**:
- Claude Code: 子代理有独立 LLM 会话 + 工具权限子集，可并行运行多个子代理处理独立任务
- OpenCode: worktree 中子代理自主实现功能，reviewer 审查 diff 后产出结构化 review

**差距**:
- planner 不会真的检查仓库结构来制定计划
- builder 不会真的写代码 — 只是跑 shell 命令
- reviewer 只是跑 `git diff --stat`
- 等于骨架代码，实际无 LLM 驱动

**建议方案**:
- 每个子代理角色获得独立的 `HermesAgent` 实例 + 受限工具集
- planner: read_file + list_files + repo_map
- builder: read_file + write_file + run_command (test only)
- reviewer: read_file + git_diff + code_review
- 实现 `subagent_dispatch` 工具: LLM 将子任务委托给子代理，异步并行运行

**涉及**: `subagents.py` 重构 + `agent.py` subagent dispatch

---

## P1 — 竞争力差异层

### 6. 语义搜索缺失

**现状**: `search_text` 是 ripgrep/grep 文本匹配。`rank_files` 是关键词+stem 匹配。无法做 "找到处理用户认证的代码" 这种语义查询。

**竞品做法**:
- Claude Code: 无内建语义搜索（依赖 LLM 阅读文件），但 `rank_files` 启发式足够好
- Cursor: 基于 embeddings 的语义代码索引
- GitHub Copilot: workspace-wide semantic index

**差距**: 对不熟悉代码库的用户（或 agent 首次接触项目），文本搜索找不到语义相关代码。

**建议方案**:
- 可选嵌入后端（`sentence-transformers` 本地模型 或 OpenAI embeddings API）
- 在 `build_project_map` 时增量构建向量索引
- 新增 `semantic_search` 工具，返回 top-k 语义相关文件/函数
- 保持 `search_text` 作为精确匹配 fallback

**涉及**: 新模块 `coding/embeddings.py`

### 7. 上下文窗口智能管理

**现状**: `compression.py` 有基础的 token estimation 和 fallback summary。但没有结构化的上下文窗口管理 — 对话超长时行为不可预测。

**竞品做法**:
- Claude Code: 自动跟踪上下文使用率，接近限制时压缩历史消息，保留关键信息
- OpenCode: 基于 round 的上下文裁剪，保留最近的 N 轮 + 系统提示
- Aider: `/drop` 命令手动移除文件，`/clear` 清空历史

**差距**:
- 长对话（50+ 轮）时可能超出模型上下文窗口
- 没有自动摘要或智能裁剪
- 没有 `/clear` 或上下文重置机制

**建议方案**:
- 在每轮 `run()` 前估算当前 token 使用量
- 超过 80% 窗口时自动压缩: 保留系统提示 + 最近 10 轮 + 早期轮次的摘要
- 新增 `/clear` 命令和 `clear_context` 工具

**涉及**: `compression.py` 增强 + `agent.py` 上下文感知

### 8. 代码库感知的系统提示生成

**现状**: `build_context_preamble()` 注入 `.hermes/rules.md` + git branch + modified count。提示内容是静态的。

**竞品做法**:
- Claude Code: 每轮更新 git status、recent changes、current branch，动态注入
- OpenCode: `.opencode` 配置文件定义项目级提示
- Cursor: `.cursorrules` + 当前文件上下文

**差距**:
- 规则注入只在启动时做一次，多轮对话中项目状态变化不反映
- 没有检测项目使用的框架/语言并自动调整提示风格

**建议方案**:
- 在每轮对话开始时注入轻量上下文摘要（< 200 tokens）: 当前 branch, modified files, last commit
- 检测项目语言/框架（from pyproject.toml / package.json / go.mod）并注入相应编码规范
- 新增 `inject_context_every_turn` 配置开关

**涉及**: `context_inject.py` 增强 + `agent.py` per-turn context

### 9. 会话持久化与恢复

**现状**: 对话结束即丢失。虽有 memory 系统和 session log，但无法从昨天停下的地方继续。

**竞品做法**:
- Claude Code: 对话历史持久化，`/resume` 恢复上次会话
- OpenCode: SQLite 存储对话，支持跨重启恢复
- Aider: `.aider.chat.history.md` 保存完整对话

**差距**:
- CLI 有 29 个命令但 `/resume` 打的是 stub ("not yet implemented")
- memory 存的是提炼的知识条目，不是对话历史
- 重启 CLI 等于丢失全部上下文

**建议方案**:
- 实现 `/resume <session-id>` 命令
- 自动保存每次对话的 message_history 到 `.hermes/sessions/`
- 启动时展示最近会话列表
- `/sessions` 已有实现，打通到 resume 流程

**涉及**: `cli.py` + sessions 模块

### 10. 外部工具链集成

**现状**: 有 `external_tools`（加载配置但不执行）和 `hook_status`（列出 hooks）。各工具的调用完全由 LLM 决定。

**竞品做法**:
- Claude Code: `--mcp-config` 参数实现 MCP 服务器热插拔
- OpenCode: 外部 linter/formatter 自动在编辑后运行
- Aider: 可配置的 lint/test 命令在每次编辑后自动运行

**差距**:
- 编辑文件后不会自动运行 linter/formatter
- 没有 pre-commit hook 集成
- `load_external_tools` 加载了配置但 agent 不知道怎么用它们

**建议方案**:
- 实现 `post_edit` 自动触发: run hooks → format → lint
- agent 编辑文件后 CLI 自动注入 "文件已编辑，运行 lint 检查" 的提示
- external tools 配置中可声明 `auto_trigger` 事件

**涉及**: `extensibility.py` + `cli.py` post-edit flow

---

## P2 — 高级能力层

### 11. 结构化代码生成能力

**现状**: agent 可以写代码但完全是自由格式 — 没有模板系统、没有项目脚手架、没有生成最佳实践检查。

**竞品做法**:
- Claude Code: 通过 CLAUDE.md 中的规则约定代码风格
- OpenCode: `.opencode` 定义代码模板
- Aider: convention files 定义代码风格约定

**差距**:
- agent 生成的代码风格可能不一致（今天用 dataclass 明天用 namedtuple）
- 新项目初始化无脚手架

**建议方案**:
- 支持 `.hermes/conventions.md` 作为编码规范注入
- 新增 `scaffold` 工具: 基于项目类型生成标准文件结构
- LLM 生成代码后自动运行 `python_diagnostics` 检查语法

**涉及**: `context_inject.py` + 新模块 `coding/scaffold.py`

### 12. Debugger 交互

**现状**: agent 无法与调试器交互。错误发生时只能看 traceback 文本。

**竞品做法**:
- Claude Code: 可以阅读 traceback 并定位错误行
- Cursor: VS Code debugger 集成
- Aider: 读取 traceback 后自动定位并建议修复

**差距**:
- 运行时错误（pytest 失败等）只能看到 stdout/stderr 文本
- 没有交互式 pdb 支持
- 不能设置断点或检查变量

**建议方案**:
- 增强 `run_tests` 结果: 自动将 traceback 位置映射到源码上下文
- 新增 `debug_error` 工具: 接收 traceback，返回相关源码 + 变量
- 长期: pdb 协议交互（低优先级）

**涉及**: `testing.py` 增强

### 13. 多项目管理

**现状**: 一个 CLI 实例绑定一个 workspace。无法同时操作多个项目。

**竞品做法**:
- Claude Code: 单次会话一个项目，但可通过 `/workspace` 切换
- OpenCode: 同上

**差距**:
- 跨项目重构时需要手动切换 workspace
- 无法在一个对话中引用另一个项目的代码

**建议方案**:
- 新增 `--workspace` 运行时切换（`/cd <path>` 命令）
- 辅助项目只读引用（`/ref <path>` 将另一个项目加入只读上下文）

**涉及**: `cli.py` workspace management

### 14. 用量分析与成本洞察

**现状**: `/usage` 显示当前会话 token 用量。但没有成本估算、历史统计、使用趋势。

**竞品做法**:
- Claude Code: 无内建成本分析（依赖 API 账单）
- OpenCode: 本地运行模型，成本不敏感
- Aider: `--analytics` 可选，展示历史用量

**差距**:
- 用户不知道一次对话花了多少钱
- 无历史统计查看使用模式

**建议方案**:
- 基于模型定价表估算成本（DEEPSEEK: $0.14/1M input, $0.28/1M output）
- `/usage --cost` 显示 $ 估算
- 可选的历史用量 JSONL 持久化

**涉及**: `agent.py` usage 增强

### 15. 文件监视模式

**现状**: 完全 request-response 模式。agent 只在用户输入时响应。

**竞品做法**:
- Claude Code: 无 watch 模式（设计如此，保持人在环中）
- Aider: 无 watch 模式
- Cursor: 实时文件变更检测

**差距**: 这不适合所有场景，但对 CI/CD 修复、自动化测试修复等场景有价值。

**建议方案**:
- `/watch <glob>` 启动文件监视 — 文件变更时触发预定义 action
- 初始支持: 监视测试文件 → 变更时自动运行测试并报告
- 保持人在环中 — watch 模式仅做分析和报告，不做自动编辑

**涉及**: 新模块 `coding/watch.py`

### 16. 多模态输出

**现状**: 有 `read_image` 输入（base64 data-URI）。但 agent 无法生成图表、架构图等可视化输出。

**竞品做法**:
- Claude Code: 可生成 mermaid 图表（SVG 渲染）
- Cursor: 同上
- GitHub Copilot: 无图表生成

**差距**: 架构讨论时只能文字描述，无法直观展示。

**建议方案**:
- agent 生成 mermaid.js 代码块 → CLI 渲染为 ASCII art 或保存为 SVG
- 新增 `render_diagram` 工具: 接收 mermaid 源码，输出渲染结果
- 最小方案: 不做渲染，仅支持 mermaid 代码块格式约定

**涉及**: `cli.py` 输出处理

### 17. 安全审计与合规

**现状**: 权限系统有 `deny` 拦截 + `audit` 日志。但没有安全扫描、依赖审计、许可证检查。

**竞品做法**:
- Claude Code: 无内建安全扫描（依赖 code_review 子代理）
- GitHub Copilot: Microsoft 安全扫描后端
- Cursor: 无内建安全扫描

**差距**: 缺乏依赖安全审计能力，对供应链安全敏感的用户是风险。

**建议方案**:
- 新增 `security_audit` 工具: 调用 `pip-audit` / `npm audit` 扫描已知 CVE
- 对依赖变更（pyproject.toml / package.json）自动提示审计
- 集成到 code_review 检查清单

**涉及**: `subagents.py` code_review 增强

---

## 汇总

| # | 缺口 | 优先级 | 涉及模块 | 预估测试 | 复杂度 |
|---|------|--------|---------|---------|--------|
| 1 | CLI 流式输出 | P0 | `cli.py` | +5 | 低 |
| 2 | 终端 UI 着色 | P0 | `cli.py` 输出 | +8 | 中 |
| 3 | 编辑确认流程 | P0 | `permissions.py` + `cli.py` | +10 | 中 |
| 4 | Agent 自我纠错循环 | P0 | `agent.py` + `coding.py` | +8 | 中 |
| 5 | 子代理 LLM 驱动 | P0 | `subagents.py` 重构 | +15 | 高 |
| 6 | 语义搜索 | P1 | `coding/embeddings.py` | +12 | 中 |
| 7 | 上下文窗口管理 | P1 | `compression.py` + `agent.py` | +10 | 中 |
| 8 | 每轮上下文刷新 | P1 | `context_inject.py` | +8 | 低 |
| 9 | 会话持久化恢复 | P1 | `cli.py` + sessions | +8 | 中 |
| 10 | 编辑后自动工具链 | P1 | `extensibility.py` + `cli.py` | +8 | 低 |
| 11 | 编码规范引擎 | P2 | `context_inject.py` + scaffold | +10 | 中 |
| 12 | Debugger 交互 | P2 | `testing.py` | +8 | 中 |
| 13 | 多项目管理 | P2 | `cli.py` workspace | +6 | 低 |
| 14 | 用量成本洞察 | P2 | `agent.py` usage | +5 | 低 |
| 15 | 文件监视模式 | P2 | `coding/watch.py` | +8 | 中 |
| 16 | 多模态输出 | P2 | `cli.py` diagram | +6 | 低 |
| 17 | 安全审计 | P2 | `subagents.py` | +6 | 低 |

**Phase 2 总预计**: P0 约 46 测试，P1 约 46，P2 约 43，合计 135+ 测试增量。

## 完成状态（2026-05-31）

所有 17 项差距已通过 M9/M10/M11 三个里程碑全部补齐：

| # | 缺口 | 优先级 | 里程碑 | 实现模块 |
|---|------|--------|--------|---------|
| 1 | CLI 流式输出 | P0 | M9 | `cli.py` `run_stream()` 路径 |
| 2 | 终端 UI 着色 | P0 | M9 | `cli.py` `color_diff()` + rich 输出 |
| 3 | 编辑确认流程 | P0 | M9 | `permissions.py` edit_confirm + edit_preview |
| 4 | Agent 自我纠错循环 | P0 | M9 | `agent.py` classify_tool_error 修复 + 错误计数 |
| 5 | 子代理 LLM 驱动 | P0 | M9 | `subagents.py` 独立工具集 |
| 6 | 语义搜索 | P1 | M10 | `coding/embeddings.py` TF-IDF SemanticIndex |
| 7 | 上下文窗口管理 | P1 | M10 | `compression.py` ContextWindow + 自动压缩 |
| 8 | 每轮上下文刷新 | P1 | M10 | `context_inject.py` per_turn_context() |
| 9 | 会话持久化恢复 | P1 | M10 | `coding/conversation_store.py` + `/resume` |
| 10 | 编辑后自动工具链 | P1 | M10 | `extensibility.py` run_post_edit_hooks |
| 11 | 编码规范引擎 | P2 | M11 | `context_inject.py` discover_conventions + scaffold |
| 12 | Debugger 交互 | P2 | M11 | `testing.py` debug_error() |
| 13 | 多项目管理 | P2 | M11 | `cli.py` `/cd` + `/ref` |
| 14 | 用量成本洞察 | P2 | M11 | `agent.py` cost_estimate + usage 增强 |
| 15 | 文件监视模式 | P2 | M11 | `coding/watch.py` watch_status + watch_files |
| 16 | 多模态输出 | P2 | M11 | `tools/coding.py` _render_diagram() |
| 17 | 安全审计 | P2 | M11 | `coding/subagents.py` security_audit() |

**测试总数**: 311 → 400 (+89)

## 建议推进顺序

```
Phase 2 (本次):
  M9: P0 全部 —
    流式输出 → 终端着色 → 编辑确认 → 错误纠错 → LLM 子代理

  M10: P1 全部 —
    语义搜索 → 上下文管理 → 每轮刷新 → 会话恢复 → 自动工具链

  M11: P2 按需 —
    编码规范 → Debugger → 多项目 → 成本 → Watch → 图表 → 安全审计
```

## 架构演进方向

Phase 1（M5-M8）让 Hermes Lite **功能完备** — 它有了所有 coding agent 该有的工具。
Phase 2（M9-M11）让 Hermes Lite **体验优秀** — 它用起来像一个真正的产品，而不是开发中的原型。

**Phase 2 已于 2026-05-31 完成。** 所有 17 项体验深度与智能程度差距全部补齐，测试从 311 增长至 400。

关键转变：
- 从 "能用" 到 "好用"
- 从 "人适应工具" 到 "工具适应人"
- 从 "单轮问答" 到 "持续协作伙伴"
