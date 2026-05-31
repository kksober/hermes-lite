# Coding Agent 能力审查 — Phase 2

> 审查时间：2026-05-31
> 审查分支：codex/coding-agent-evolution
> 审查对象：hermes-lite @ 9b4ffce (M1-M11)
> 测试数量：400 passed in 29.35s
> 文件总数：81 files, +15,601 lines

---

## 总体评价：A-（生产级 coding agent，少量 UX 缺口）

11 个里程碑全部完成，从 M1 核心框架到 M11 高级能力，项目已经从一个「能用」的框架
进化成了一个「好用」的 coding agent。400 个测试全绿。

---

## 一、读代码能力：A-

### 评测要点

| 工具 | 文件 | 能力 |
|------|------|------|
| `read_file(path, offset, limit)` | `tools/builtin.py` | 分页读取，带行号，JSON 返回 |
| `search_text(pattern, ...)` | `coding/context.py` | ripgrep 加速搜索，降级纯 Python |
| `build_project_map()` | `coding/context.py` | 项目结构扫描 + 语言分类 |
| `list_files(glob)` | `coding/context.py` | 按 glob 列出文件 |
| `rank_files(query)` | `coding/context.py` | 多因子文件相关性排行 |
| `recent_changes()` | `coding/context.py` | 最近修改文件 |
| `repo_map_summary()` | `coding/context.py` | 仓库结构摘要 |
| `semantic_search(query)` | `coding/embeddings.py` | **新增** TF-IDF 语义代码搜索 |
| `lsp_definition/hover/references/diagnostics/symbols` | `coding/lsp.py` | LSP 协议客户端 |
| `extract_python_symbols()` | `coding/diagnostics.py` | Python 语法诊断 |
| `discover_conventions()` | `coding/context_inject.py` | **新增 M11** .hermes/conventions.md |
| `workspace_snapshot()` | `coding/context_inject.py` | 工作区快照 |

### 缺失

- 没有 `read_file` 的大文件检测——读二进制/超大文件会爆 context
- LSP 需要 server 预先安装，没有 fallback 提示
- `semantic_search` 用 TF-IDF 而非 embedding 模型，精度有限

### 评分理由

工具链完整度已接近 Hermes 的 90%。语义搜索（M10）和规范发现（M11）是超出预期的加分项。

---

## 二、装 Skill / 规范 / 规则能力：B+

### 评测要点

| 能力 | 文件 | 说明 |
|------|------|------|
| Skill 索引注入 | `agent.py:build_system_prompt()` | skill 列表注入 system prompt |
| 规范发现 | `coding/context_inject.py` | `.hermes/conventions.md` 自动发现 (M11) |
| 规则发现 | `coding/context_inject.py` | `.hermes/rules.md` 自动发现 (M6) |
| Workspace 快照 | `coding/context_inject.py` | git/branch/files 摘要 |
| 项目脚手架 | `coding/scaffold.py` | **新增 M11** python-app/lib、node-app 模板 |

### 缺失

- **仍然没有 `skill_view` 工具**——Agent 看得到 skill 索引，但无法加载全文
- **仍然没有 `skill_manage` 工具**——Agent 不能创建/修补 skill
- 规范/规则注入是文本级，没有版本控制或优先级

### 评分理由

规范系统和规则系统是加分项（M6 + M11），但 skill 系统的核心缺失从第一轮审查到现在没变——Agent 能看到 skill 名字但读不到内容。这就像一个图书馆只有目录没有书。

---

## 三、写代码能力：A-

### 评测要点

| 工具 | 文件 | 能力 |
|------|------|------|
| `write_file(path, content)` | `tools/builtin.py` | 写入文件，workspace 沙箱 |
| `edit_file(path, old, new)` | `tools/coding.py` | **增强 M7** 统一编辑入口，编辑预览 + 确认 |
| `apply_text_patch(...)` | `coding/patches.py` | find-and-replace 补丁 |
| `apply_unified_diff(...)` | `coding/patches.py` | unified diff 应用 |
| `patch_dry_run(...)` | `coding/patches.py` | 预演 patch |
| `diff_summary(...)` | `coding/patches.py` | diff 摘要 |
| `GitClient.status/diff/...` | `coding/git.py` | Git 操作封装 |
| `_render_edit_preview()` | `tools/coding.py` | **新增 M9** 编辑预览 + diff 着色 |
| `_apply_patch_with_confirm()` | `tools/coding.py` | **新增 M9** 确认后应用补丁 |
| `_render_diagram()` | `tools/coding.py` | **新增 M11** Mermaid 图表 |

### 评分理由

编辑预览 + diff 着色 + 确认流程（M9）是重大体验提升。Mermaid 图表（M11）是锦上添花。编辑工具链已经完整，唯一的小遗憾是 `apply_text_patch` 用的是精确匹配而非模糊匹配——换行/缩进差异会导致匹配失败。

---

## 四、测试能力：A-

### 评测要点

| 工具 | 文件 | 能力 |
|------|------|------|
| `run_tests(path, extra_args)` | `coding/testing.py` | pytest 执行 + 结构化输出解析 |
| `discover_venv_python()` | `coding/testing.py` | .venv 自动发现 |
| `parse_pytest_output()` | `coding/testing.py` | passed/failed/errors/skipped 解析 |
| `debug_error(traceback)` | `coding/testing.py` | **新增 M11** traceback 源码映射 |

### 缺失

- 没有 `run_test(only=file::test_name)` 单测指定
- 失败截断在 4000 字符——复杂错误可能被裁掉

### 评分理由

测试 → 解析 → 失败定位 → debug 映射的闭环完整（M6 + M11）。traceback 源码映射是聪明设计。

---

## 五、CLI 交互：A-

### 评测要点

| 功能 | 说明 | 里程碑 |
|------|------|--------|
| `run_stream()` 流式输出 | 逐 token 显示，隐藏光标 | M9 |
| `color_diff()` 着色 | ANSI 色彩 diff 预览 | M9 |
| 编辑确认流程 | 预览 → 确认 → 应用 | M9 |
| `/usage` 成本显示 | token + 费用追踪 | M8 + M11 |
| `/cd /ref` 多项目 | 工作区切换 | M11 |
| `/clear` 清上下文 | 重新开始 | M10 |
| `/resume` 恢复 | 加载历史会话 | M10 |
| `/test` 测试 | pytest 快捷运行 | M6 |
| `/context /rules` | 查看注入内容 | M6 |
| `/notify` | 桌面通知 | M8 |
| 每轮上下文注入 | git/branch/files 自动注入 | M10 |
| 自动保存 | 会话自动持久化 | M10 |

### 缺失

- 没有 `/retry` —— 打错了只能重新输入
- 没有 `/undo` —— 不能撤销上一轮
- 没有 `/compact` —— 不能主动触发压缩（但自动压缩在）
- 没有 `/btw` 旁路提问
- 没有 `/diff` 看当前改了什么（GitClient 有 diff 但没暴露为命令）

### 评分理由

从第一轮审查的 8 个斜杠命令到现在的 12+ 功能，CLI 已经非常实用。流式输出 + diff 着色 + 编辑确认是三个关键体验升级。跟 Hermes 的差距主要在 `/retry` `/undo` `/btw` 这些细节。

---

## 六、架构亮点（M9-M11 新增）

| 能力 | 模块 | 评注 |
|------|------|------|
| **语义搜索** | `coding/embeddings.py` | TF-IDF 实现，不需要外部 embedding API |
| **上下文窗口管理** | `compression.py → ContextWindow` | 80% 阈值自动压缩，集成 agent loop |
| **编码规范引擎** | `coding/context_inject.py` | `.hermes/conventions.md` 自动发现 (M11) |
| **Debugger** | `coding/testing.py` | traceback → 源码行映射 (M11) |
| **多项目切换** | `cli.py /cd /ref` | 一个 REPL 管理多个项目 (M11) |
| **成本追踪** | `agent.py cost_estimate` | 10 个模型定价表 + usage.cost_usd (M11) |
| **项目脚手架** | `coding/scaffold.py` | python-app/lib/node-app 三种模板 (M11) |
| **安全审计** | `coding/subagents.py` | pip-audit/npm audit 集成 (M11) |
| **编辑确认 + Diff** | `cli.py + tools/coding.py` | 操作前预览，ANSI 着色 (M9) |
| **会话持久化** | `coding/conversation_store.py` | JSON 文件存储，可恢复 (M10) |

---

## 七、里程碑演进轨迹

```
M1 - 核心框架     │████████░░░░░░░░░░  62 tests
M2 - Coding 模式  │██████████████░░░░  119 tests  
M3 - 编辑与索引   │████████████████░░  155 tests
M4 - LSP/MCP      │█████████████████░  183 tests
M5 - 生产加固     │██████████████████  213 tests
M6 - P0 补齐      │██████████████████  250 tests
M7 - P1 竞争力    │██████████████████  284 tests
M8 - P2 质量      │██████████████████  311 tests
M9 - P0 体验阻断  │██████████████████  339 tests
M10 - P1 竞争力   │██████████████████  378 tests
M11 - P2 高级     │██████████████████  400 tests
```

---

## 八、剩余差距（A- → A+ 的路）

### 🔴 还缺的（影响日常）

1. **Skill 不能用**——没有 `skill_view` / `skill_manage` 工具，skill 只有索引
2. **没有 `/retry` `/undo`**——两个最高频的交互命令缺失

### 🟡 可以加强的

3. **没有 `search_files(pattern, target="files")`**——只能搜内容，不能搜文件名
4. **`read_file` 无大小限制**——可能读巨型文件
5. **没有 browser 工具**——不能做 web 交互（PR review、网页操作）
6. **没有 cron / scheduling**

### 🟢 锦上添花

7. **Mermaid 图表只存不渲染**——需要外部工具渲染
8. **TF-IDF 语义搜索精度有限**——未来可换 embedding 模型
9. **Skill 没有 category 分组**

---

## 总结

| 维度 | 第一轮 (M1-M5) | 第二轮 (M1-M11) |
|------|---------------|----------------|
| 测试数 | 213 | 400 |
| 读代码 | B+ | A- |
| Skill/规范 | C+ | B+ |
| 写代码 | B | A- |
| 测试 | B+ | A- |
| CLI 交互 | B | A- |
| **总分** | **B+** | **A-** |

这是一个从「能用」到「好用」的质变。M9-M11 补齐的流式输出、编辑确认、上下文管理、成本追踪
是体验上的关键突破。

如果修掉 Skill 工具缺失和 `/retry` `/undo` 两个问题，就是 A。
