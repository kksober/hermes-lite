# Coding Agent 能力审查

> 审查时间：2026-05-27
> 审查对象：hermes-lite @ 9c0865c
> 审查范围：读代码、装 Skill、写代码、测试、CLI 交互
> 文件总数：44 个 Python 文件

---

## 总体评价：B+（有完整 coding agent 骨架，缺实战打磨）

项目已经从通用 agent 框架进化成了 coding agent。44 个文件，分工清晰，
覆盖了读代码→理解代码→写代码→测试→Git 操作的完整链路。
但每个环节都有「能用但不顺手」的地方。

---

## 一、读代码能力：B+

### 有的

| 工具 | 来源 | 能力 |
|------|------|------|
| `read_file` | `tools/builtin.py` | 读取文件，支持 offset/limit 分页，返回带行号的内容 |
| `search_text` | `coding/context.py` | ripgrep 加速的文本搜索，降级到纯 Python |
| `build_project_map` | `coding/context.py` | 扫描项目结构，识别语言分类 |
| `list_files` | `coding/context.py` | 列出文件列表 |
| `recent_changes` | `coding/context.py` | 最近修改的文件 |
| `repo_map_summary` | `coding/context.py` | 仓库结构摘要 |
| LSP 系列 | `coding/lsp.py` | `lsp_definition`、`lsp_references`、`lsp_hover`、`lsp_diagnostics`、`lsp_symbols` |

### 缺的

- **没有文件名搜索**——`search_text` 搜内容，但没有 `find_files(pattern="*.py")` 按 glob 找文件
- **没有文件内容计数**——不知道一个文件多少行、多少函数，依赖 LSP 但 LSP 需要 server 先启动
- **没有二进制文件检测**——可能把图片当文本读
- **项目地图一次性全量**——大型 monorepo 会爆 token

### 对比你用的 Hermes

Hermes 有 `search_files(pattern, target="content"|"files", file_glob, output_mode)` 和 `read_file(path, offset, limit)`。hermes-lite 的 `search_text` + `read_file` 覆盖了 60%，但缺了按文件名找文件、按模式过滤、输出计数模式。

---

## 二、装 Skill 能力：C+

### 有的

- `SkillManager` (`skills/manager.py`)——Markdown 文件存储、YAML frontmatter、自动发现
- 3 个内置 skill（code-review、filesystem、web-research）
- `build_system_prompt()` 注入了 skill 索引

### 缺的

- **Skill 只是文本注入**——Agent 看到的是 `<available_skills>\n- code-review: ...</available_skills>`，不会自动加载。Agent 需要自己判断「这个任务需要 code-review skill」然后去读文件，但**没有工具让它读 skill**。
- **没有 skill_view 工具**——Agent 无法加载 skill 全文到上下文
- **没有 skill_manage 工具**——Agent 不能创建/修补 skill，不能从经验中学习
- **Skill 索引格式简陋**——没有 category 分组，没有 trigger 条件

### 对比 Hermes

Hermes 的 skill 系统有三个关键设计这里都没有：
1. `skill_view(name)` 工具——Agent 可以按需加载 skill 全文
2. `skill_manage(action="create")` 工具——Agent 能从成功经验中自我改进
3. Skill 的 description 本身就是 trigger——LLM 看到匹配的任务自动加载

---

## 三、写代码能力：B

### 有的

| 工具 | 来源 | 能力 |
|------|------|------|
| `write_file` | `tools/builtin.py` | 写入文件，有 workspace 沙箱 |
| `apply_text_patch` | `coding/patches.py` | 文本替换（find-and-replace） |
| `apply_unified_diff` | `coding/patches.py` | 应用 unified diff |
| `patch_dry_run` | `coding/patches.py` | 预演 patch |
| `GitClient` | `coding/git.py` | status、diff、branch |

### 缺的

- **没有 search-and-replace 工具给 Agent 用**——`apply_text_patch` 存在但没看到注册为 tool 的代码。Agent 只能用 `run_shell("sed ...")`，这既危险又不准确。
- **没有自带 `patch` 工具**——指 `patch(path, old_string, new_string)` 这种模糊匹配的编辑器
- **write_file 不支持指定编码**——默认 UTF-8
- **没有 diff 预览**——Agent 写完代码后没法用 `diff` 看改了什么（除非手动调 GitClient）

### 对比 Hermes

Hermes 的核心代码编辑工具 `patch(path, old_string, new_string)` 使用模糊匹配（9 种策略），可以容忍空格/缩进漂移。hermes-lite 没有等价物——要么全量覆盖（write_file），要么精确匹配（apply_text_patch），中间地带缺失。

---

## 四、测试能力：B+

### 有的

- `run_tests` (`coding/testing.py`)——pytest 执行 + 结构化输出解析
- 自动发现 `.venv`
- 解析 passed/failed/errors/skipped 计数
- 提取失败详情

### 缺的

- **没有 `--only` 模式**——不能只跑单个测试文件或单个测试函数
- **没有增量测试**——不能只跑改过的文件的测试
- **失败输出可能截断**——`raw[:4000]`
- **只支持 pytest**——没有 unittest、jest、go test 等

### 对比 Hermes

hermes-lite 的测试工具在设计上比 Hermes 更结构化（Hermes 只是 `terminal("pytest tests/")`）。但 Hermes 的灵活性更高——可以用任意命令跑任意测试框架，不限于 pytest。

---

## 五、CLI 交互：B

### 有的

- prompt_toolkit 支持，有历史记录
- `--provider --model` 参数
- `/help /quit /memory /skills /tools /model /clear` 斜杠命令
- 多轮对话历史保持
- 权限确认（allow/ask/deny）
- ASCII art banner
- Workspace + Git 状态显示

### 缺的

- **没有 `/retry`**——打错了不能重发
- **没有 `/undo`**——不能撤销上一轮
- **没有 `/compact`**——上下文太长时不能主动压缩
- **没有 `/diff`**——看不到当前改了哪些文件
- **斜杠命令少**——跟 Hermes 的 30+ 命令比，这里只有 8 个
- **没有 `/btw`（旁路提问）**——问一个不打断主任务的问题
- **没有 streaming 输出**——CLI 用的是 `run()` 不是 `run_stream()`，等全部完成才显示

### 对比 Hermes

Hermes CLI 有 `/retry`、`/undo`、`/btw`、`/compress`、`/rollback`、`/background`、`/branch`、`/save`、`/usage`、`/status`、`/verbose` 等。hermes-lite CLI 只覆盖了最基础的 25%。

---

## 六、亮点（超出预期的地方）

1. **Permission 系统**——`allow/ask/deny` 三级，带 confirm callback，安全设计完整
2. **LSP 集成**——definition/references/hover/diagnostics/symbols，这是大多数 coding agent 没有的
3. **Subagent 系统**——plan-based 多 agent 编排 + WorktreeExecutor 隔离执行
4. **MCP 客户端**——可以接入外部工具服务器
5. **Audit 日志**——所有操作可追溯
6. **Context 压缩集成**——agent loop 里已经接了 ContextWindow，会主动压缩
7. **错误恢复**——tool 失败后有分类、重试提示、连续错误降级
8. **Notebook 支持**——可以操作 Jupyter cell，极少见

---

## 七、优先级改进建议

### 🔴 马上修（影响日常使用）

1. **给 Agent 加 `skill_view` 工具**——让它能读取 skill 全文，否则 skill 系统形同虚设
2. **注册 `apply_text_patch` 为 Agent 可用的 tool**——目前 Agent 只能用 write_file 全量覆盖
3. **CLI 用 `run_stream()` 替代 `run()`**——不等全部完成才显示
4. **加 `search_files` 工具**——支持按文件名 glob 查找

### 🟡 尽快修（提升体验）

5. **CLI 加 `/retry` `/undo` `/diff` 命令**
6. **`read_file` 加文件大小限制**——防止读大文件爆 context
7. **`run_tests` 支持 `--only` 指定单测试**
8. **Skill 加 `skill_manage` 工具**——让 Agent 能创建/修补 skill

### 🟢 锦上添花

9. **浏览器工具**——web_fetch 只能抓文本，不能交互
10. **Session search**——搜索历史对话
11. **Cron 定时任务**

---

## 总结

这个项目已经是一个有完整 coding agent 能力的框架了。能读代码、能搜索、能理解（LSP）、能写、能测试、有权限控制、有子代理编排。但「能跑」和「好用」之间还差一轮打磨——主要集中在工具注册（有些写好了没注册）、CLI 丰富度、和 skill 系统的真正激活。

如果满分是 Claude Code/Hermes 的水平（A+），那 hermes-lite 目前是 B+。差距主要在 UX 打磨和工具的齐全度，不在架构。
