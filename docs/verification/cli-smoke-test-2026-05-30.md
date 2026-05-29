# CLI 冒烟测试报告

**日期**: 2026-05-30
**环境**: macOS Darwin 24.3.0, Python 3.11.14, pydantic_ai 1.103.0
**API**: DeepSeek (deepseek-chat)

## 测试环境

```
Repository: /Users/ethan/Sandbox/hermes-lite
Branch: codex/coding-agent-evolution
Python: .venv/bin/python (uv venv)
Workspace: /tmp/_hl_smoke (git init --empty)
```

## 全量测试结果

```
python -m pytest tests/ -q
213 passed in 14.76s
```

所有 213 个测试全部通过，覆盖:
- 导入和配置 (27 个)
- 权限策略和命令执行 (38 个交互式权限 + shell)
- PTY 长命令会话 (19 个)
- 文本编辑和补丁应用 (18 个)
- 上下文索引和搜索 (18 个 + context)
- LSP/MCP 客户端 (22 个)
- Git worktree 子代理执行 (6 个)
- Coding 工具注册 + 上下文 + 诊断
- 上下文压缩、会话管理、技能系统

## 核心工具冒烟测试

| 工具 | 状态 |
|------|------|
| workspace_status | PASS |
| list_files | PASS |
| project_map | PASS |
| git_status | PASS |
| recent_changes | PASS |
| hook_status | PASS |
| external_tools | PASS |
| mcp_servers | PASS |
| lsp_status | PASS |
| mcp_status | PASS |
| subagent_plan | PASS |

## DeepSeek API 集成验证

### 基础对话
```
Prompt: "1+1等于几?"
Response: "2。"
```

### 工具调用
```
Prompt: "列出当前工作区有哪些文件"
Agent 调用了 workspace_status + list_files + project_map
Response: "当前工作区共有 2 个文件: src/app.py, tests/test_app.py"
```

### 多轮对话
```
Step 1: "读取 src/app.py 的内容" → 正确返回文件内容
Step 2: "用 project_map 展示项目结构" → 正确展示目录树
```

### CLI REPL
```
echo "quit" | hermes-lite --workspace /tmp/_hl_smoke
→ 显示 banner，接收命令，正常退出
```

## 已知局限

1. LSP/MCP 为客户端骨架：连接管理完整，但无真实 LSP/MCP 服务器时返回 `{"available": False}`
2. ripgrep 为可选加速：未安装 rg 时自动回退到 Python glob/字符串扫描
3. Git worktree 测试自动跳过：无 git 环境时 `pytest.skip`
4. 交互式权限非交互模式：无 confirm 回调时 ask 自动转为 deny

## 结论

CLI 端到端可用。213 个测试全绿，核心工具链完整，DeepSeek API 集成正常。
