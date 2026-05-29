# 产品迭代记录

## 迭代 1: 交互式权限 + PTY 长命令会话

**日期**: 2026-05-15 前

**目标**: 为 coding agent 模式奠定安全和进程管理基础

**新增文件**:
- `src/hermes_lite/coding/permissions.py` — 权限策略重写
- `src/hermes_lite/coding/sessions.py` — PTY 长会话管理
- `src/hermes_lite/coding/audit.py`  — 审计日志
- `tests/test_coding_interactive_permissions.py` — 38 个测试
- `tests/test_coding_sessions.py` — 19 个测试

**关键决策**:
- 命令决策采用 6 层分级 (shell control → destructive → prefix auth → classification → safe)
- 无 confirm 回调时 ask → deny 作为安全默认
- 会话授权支持 prefix/path/category 三种粒度，once/session 两种范围

**工程教训**:
- 前缀授权必须放在命令分类之前，否则 "pip install requests" 被网络命令拒绝后根本到不了前缀匹配
- `sys.stdin.read()` 会永久阻塞，PTY 交互必须用 `readline()`
- 进程被 kill 后 `running` 属性需要检查 `process.poll()` 而不只依赖 `_eof` 标记

---

## 迭代 2: 增强编辑系统 + ripgrep 上下文索引

**日期**: 2026-05-20 前

**目标**: 实现生产级 diff 补丁应用和 ripgrep 加速搜索

**新增/重写文件**:
- `src/hermes_lite/coding/patches.py` — 统一 diff 补丁引擎（重写）
- `src/hermes_lite/coding/context.py` — ripgrep 加速上下文索引（重写）
- `tests/test_coding_editing.py` — 18 个测试
- `tests/test_coding_context_enhanced.py` — 18 个测试

**关键决策**:
- hunk 头解析简化为 `line.startswith("@@")`，三年前的正则过于复杂且不兼容
- 文件排名采用多因子加权: 精确名 200 > 包含 100 > 路径 30 > 词干 25 > 片段 15-50
- ripgrep --json 模式提供结构化输出，回退到 Python 字符串扫描

**工程教训**:
- `@@ -1,3 +1,3 @@` 这种标准 hunk 头包含了 " @@" 子串，旧的正则 `no " @@" in line` 直接跳过所有 hunk

---

## 迭代 3: LSP/MCP 客户端 + Worktree 隔离执行

**日期**: 2026-05-25 前

**目标**: 对接 LSP 和 MCP 协议，实现 git worktree 隔离子代理执行

**新增文件**:
- `src/hermes_lite/coding/lsp.py` — LSP 客户端（pyright/pylsp/tsserver）
- `src/hermes_lite/coding/mcp_client.py` — MCP 客户端
- `src/hermes_lite/coding/worktree_exec.py` — Git worktree 执行器
- `src/hermes_lite/coding/subagents.py` — 子代理编排（增强）
- `tests/test_coding_lsp_mcp.py` — 22 个测试
- `tests/test_coding_worktree.py` — 6 个测试

**关键决策**:
- LSP 和 MCP 均使用 JSON-RPC 2.0 over stdio + Content-Length 头帧格式
- 连接池按 `{root_uri}:{language}` 键控，复用连接
- WorktreeExecutor 绝不自动 merge，始终返回人工审核建议
- 子代理流水线: planner -> builder -> reviewer，每个阶段有独立角色

**工程教训**:
- `WorktreeRun` 重构时需要同步填充 `tasks` 列表，否则 `execute_step` 因 `invalid_task_index` 失败
- CLI 中新增 `/todo`、`/resume`、`/run` 命令时删除了旧存根，避免重复 case 处理器

---

## 迭代 4: CLI 全链路验证 + 稳定性修复

**日期**: 2026-05-30

**目标**: 验证 CLI 端到端可用性，修复环境兼容性问题

**修复**:
- `pydantic_ai` 1.103.0 中 `Tool.__init__` 不再接收 `parameter_json_schema`，改用 `Tool.from_schema()`
- 冒烟测试脚本需使用 `.venv/bin/python` 而非系统 Python（避免 `ModuleNotFoundError`）

**验证结果**:
- 213/213 测试全部通过
- 11 个核心 coding 工具冒烟测试通过
- DeepSeek API 集成正常，多轮对话 + 工具调用验证通过
- CLI REPL 启动/退出正常

---

## 迭代 5: 文档规范化

**日期**: 2026-05-30

**目标**: 建立项目文档体系

**变更**:
- `.md` 格式的 README 中文化
- 创建 docs/ 目录结构（specs/iterations/verification/milestones）
- 编写 coding agent 架构规格文档
