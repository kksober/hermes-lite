# 技术验证 (Verification)

## 用途

存放验证报告、兼容性测试结果、性能基准测试和其他技术验证文档。

## 内容示例

- `pydantic-ai-migration.md` — pydantic_ai 依赖升级验证报告
- `deepseek-integration.md` — DeepSeek API 对接测试报告
- `cli-smoke-test-2026-05-30.md` — CLI 冒烟测试结果
- `cross-platform-notes.md` — 跨平台兼容性记录
- `perf-baseline.md` — 工具调用和补丁应用的性能基准

## 命名规范

- `<topic>-YYYY-MM-DD.md` 或 `<topic>.md`（对长期有效的文档）
- 每个验证报告包含: 测试环境、步骤、预期 vs 实际结果、已知局限
