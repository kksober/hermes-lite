# 里程碑 (Milestones)

## 用途

记录项目关键里程碑，每个里程碑对应一组已完成的迭代和验证，标记能力边界的变化。

## 内容示例

- `m1-core-agent.md` — M1: 核心 agent 框架（多 provider、工具注册、记忆、技能、会话、压缩）
- `m2-coding-agent.md` — M2: Coding agent 模式（workspace/权限/命令执行/git）
- `m3-editing-and-context.md` — M3: 编辑系统与上下文索引（diff 补丁、rg 搜索、文件排行）
- `m4-lsp-mcp-worktree.md` — M4: LSP/MCP 客户端 + 隔离执行
- `m5-production-hardening.md` — M5: 生产加固（稳定性、兼容性、文档）

## 命名规范

- `m<N>-<slug>.md`，N 从 1 开始递增
- 每个里程碑包含: 目标、涉及的能力模块、测试数量、依赖版本、发布日期
