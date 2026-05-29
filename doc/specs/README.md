# 规范文档 (Specs)

## 用途

存放项目的技术规格说明和设计文档。当引入新功能或重大变更时，先编写 spec 明确需求、接口、副作用和验收标准。

## 内容示例

- `coding-agent-spec.md` — Coding agent 模式的功能规格和权限模型
- `lsp-mcp-protocol.md` — LSP/MCP 协议对接方案
- `worktree-isolation.md` — Git worktree 隔离执行方案
- `permission-model.md` — 交互式权限系统的决策模型

## 命名规范

- 文件名使用小写英文 + 连字符: `<topic>.md`
- 每个 spec 必须包含: 目标、非目标、接口定义、副作用、验收标准
