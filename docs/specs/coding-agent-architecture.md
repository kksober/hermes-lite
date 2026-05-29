# Coding Agent 架构规格

## 目标

在 Hermes Lite 对话引擎之上构建一个 clean-room 编码代理，不依赖 OpenCode 源码或内部实现细节，所有代码可审计、可解释。

## 非目标

- 不复制 OpenCode 的目录结构、内部模式或专有实现
- 不做自动 merge — 所有 git 写操作需人工审核
- 不支持破坏性 git 命令（push --force、hard reset、checkout . 等）

## 核心模块

### 1. Workspace（工作区抽象）

**职责**: 路径沙箱化、文件读写、敏感路径保护

```
workspace.py:
  - Workspace(root)          # 绑定根路径
  - resolve(path, operation) # 路径解析 + 安全检查
  - read_text(path)          # 带行号的文件读取
  - write_text(path, content) # 受控写入
  - summary()                # 工作区元信息

Protected paths:
  .env, .git/*, *.pem, *.key, *.p12, id_rsa*, __pycache__,
  .venv, venv, node_modules, .terraform, *.lock
```

### 2. PermissionPolicy（权限策略）

**职责**: 三级决策引擎，支持会话授权

```
permissions.py:
  - PermissionPolicy(interactive, confirm, audit)
  - decide_read(worktree_ref)    -> PermissionDecision
  - decide_write(worktree_ref)   -> PermissionDecision
  - decide_command(worktree_ref) -> PermissionDecision

决策层级（command）:
  Tier 1: 空命令拒绝
  Tier 2: shell 控制字符检测
  Tier 3: 破坏性命令拒绝（rm -rf /, git push --force 等）
  Tier 4: 会话授权匹配（前缀/路径/类别）
  Tier 5: 命令分类（network_command, risky_git）
  Tier 6: 安全命令放行

授权粒度:
  - scope: "once"（单次）/ "session"（会话内有效）
  - kind: "prefix"（命令前缀）/ "path"（路径）/ "category"（类别）
```

### 3. CommandRunner + SessionManager

**职责**: 安全命令执行 + PTY 长会话管理

```
shell.py:
  - CommandRunner(workspace, policy)
  - run(command, cwd, timeout_seconds) -> structured result

sessions.py:
  - CommandSession(start_command, pty, ring_buffer)
  - SessionManager(workspace, policy, audit)
  - start / read / write_stdin / stop / list / cleanup
  - PTY: pty.openpty() + os.setsid 进程组管理
  - Ring buffer: 5000 line 上限，atexit 注册的 cleanup 防止孤儿进程
```

### 4. Patches（补丁系统）

**职责**: 精确文本替换 + 统一 diff 补丁

```
patches.py:
  - apply_text_patch(path, old_text, new_text, replace_all)
  - apply_unified_diff(path, diff_text, dry_run, fuzzy)  # 多 hunk
  - patch_dry_run(path, diff_text, fuzzy)                 # 验证包装
  - diff_summary(path, old_content)                       # 变更摘要

Hunk 匹配:
  - `@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@` 正则解析
  - fuzzy >= 0 时，hunk 偏移 ±fuzzy 行滑动匹配
  - dry_run=True 时只验证不写入
```

### 5. Context Index（上下文索引）

**职责**: 代码搜索、文件排行、仓库地图

```
context.py:
  - list_files(pattern, limit)    # rg --files 或 Python glob 回退
  - search_text(query, path, limit) # rg --json 或 Python 字符串扫描
  - rank_files(query, limit)      # 多因子评分
  - recent_changes(count)         # git log 或 mtime 回退
  - find_test_files(source_path)  # 测试文件匹配
  - repo_map_summary(token_budget) # token 感知压缩
  - build_project_map(limit)      # 项目结构概览

rank_files 评分算法:
  精确名称匹配: 200 分
  名称包含匹配: 100 分
  词干匹配: 25 分
  路径匹配: 30 分
  片段匹配: 15-50 分（按片段长度加权）
```

### 6. LSP Client

**职责**: JSON-RPC over stdio 的 LSP 协议客户端

```
lsp.py:
  候选服务器: pyright, pylsp, tsserver（自动发现）
  
  LspClient (dataclass):
    - start(root_uri, language)      # 启动 LSP 进程
    - diagnostics(path)              # textDocument/diagnostic
    - definition(path, line, col)    # textDocument/definition
    - references(path, line, col)    # textDocument/references
    - symbols(path)                  # textDocument/documentSymbol
    - hover(path, line, col)         # textDocument/hover
    - shutdown()                     # 发送 shutdown + exit

  连接池: _lsp_pool 按 {root_uri}:{language} 缓存

  公开函数（无状态）:
    lsp_diagnostics, lsp_definition, lsp_references, lsp_symbols, lsp_hover, lsp_status
    全部在无 LSP 时返回 {"available": False}
```

### 7. MCP Client

**职责**: JSON-RPC with Content-Length framing 的 MCP 客户端

```
mcp_client.py:
  McpServerConnection:
    - start()         # 启动 MCP 服务器进程
    - list_tools()    # tools/list
    - call_tool(name, args)  # tools/call
    - shutdown()

  McpClientManager:
    - connect_all()      # 读取 .hermes/mcp.json 并启动所有服务器
    - list_all_tools()   # 聚合所有服务器工具列表
    - call_tool(server, tool, args)
    - shutdown_all()
    - status()
```

### 8. Worktree Executor

**职责**: Git worktree 隔离执行，绝不自动 merge

```
worktree_exec.py:
  WorktreeTask(role, description, status)
  WorktreeRun(run_id, worktree_path, branch_name, tasks, status)
  
  WorktreeExecutor:
    - create_run(task, roles)   # git worktree add -b <branch>
    - execute_step(run, index, commands)  # 在 worktree 中执行命令
    - review_gate(run)          # stat + diff + commit review
    - cleanup(run)              # git worktree remove --force
    - list_runs(statuses)
```

### 9. Subagent Orchestration

**职责**: planner -> builder -> reviewer 三阶段流水线

```
subagents.py:
  SubagentPlan(task, tasks[], clean_room, worktree_recommended)
  
  execute_subagent_plan(plan, workspace, policy, executor, auto_cleanup) -> review gate
  subagent_execute_with_commands(task, ...) -> 带显式命令的完整执行
```

## 安全约束

| 约束 | 实现位置 |
|------|----------|
| 路径不可逃逸沙箱 | `workspace.resolve()` |
| 破坏性 git 命令拦截 | `permissions.py::DESTRUCTIVE_PATTERNS` |
| 网络命令检测 | `permissions.py::NETWORK_COMMANDS` |
| 敏感文件保护 | `workspace.py::PROTECTED_PATHS` |
| 命令执行审计 | `audit.py::AuditLogger` |
| 无自动 merge | `worktree_exec.py::review_gate()` |
| Clean-room 约束 | 零 OpenCode 引用，自行设计所有接口 |

## 测试策略

- TDD: 先写失败测试 → 实现 → 回归全量
- 每个模块对应独立测试文件
- Git 相关测试自动跳过（无 git 环境时）
- 权限测试验证所有决策层级
- 当前测试总数: 213
