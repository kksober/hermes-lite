# Hermes Lite

基于 [Pydantic AI](https://ai.pydantic.dev/) 构建的轻量级 Agent 框架，架构参考 [Hermes Agent](https://github.com/NousResearch/hermes-agent)。

**Hermes Lite** 提供了两种模式：

- **对话模式** — 多 provider、多轮对话、工具调用、持久记忆、技能系统
- **Coding Agent 模式** — 带源码仓库感知能力的 clean-room 编码代理，支持文件操作、命令执行、代码搜索、补丁应用、LSP/MCP 协议对接和 git worktree 隔离执行

## 核心特性

### 对话引擎

| 特性 | 说明 |
|------|------|
| **多 Provider** | OpenAI、Anthropic、DeepSeek、OpenRouter — 改配置即可切换模型 |
| **多轮 Agent 循环** | 自主工具调用循环，可配置最大轮次 |
| **工具注册系统** | 按 toolset 分组，支持 requirement 守卫和 JSON Schema 校验 |
| **持久记忆** | SQLite 持久化，跨会话保留 |
| **技能系统** | 文件式过程化知识，支持自动发现、加载、创建和热修补 |
| **会话管理** | SQLite + FTS5 全文搜索，支持跨会话检索历史 |
| **上下文压缩** | token 感知的上下文压缩，LLM 摘要触发 |

### Coding Agent

| 特性 | 说明 |
|------|------|
| **工作区管理** | 路径沙箱化，敏感文件保护（.env、.git、私钥、虚拟环境） |
| **交互式权限** | 三级决策（allow/ask/deny），支持前缀/路径/类别粒度的会话授权 |
| **命令执行** | 安全命令运行器，PTY 长会话支持，进程组管理和 atexit 清理 |
| **审计日志** | JSONL 格式权限决策和命令执行审计 |
| **文本编辑** | 精确文本替换 + 统一 diff 补丁（支持多 hunk、模糊匹配、dry-run） |
| **代码搜索** | ripgrep 加速全文搜索，Python 回退 |
| **文件排行** | 多因子相关性评分（名称精确匹配 200 分，路径匹配 30 分等） |
| **Repo Map** | token 感知的仓库结构压缩，适配 LLM 上下文窗口 |
| **LSP 客户端** | JSON-RPC over stdio，支持 pyright/pylsp/tsserver，诊断/定义/引用/符号/悬停 |
| **MCP 客户端** | JSON-RPC with Content-Length framing，工具发现和远程调用 |
| **Git Worktree 执行** | 隔离分支执行规划/构建/审查流水线，绝不自动 merge |
| **子代理编排** | 确定性 planner/builder/reviewer 三阶段流水线 |

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/kksober/hermes-lite.git
cd hermes-lite

# 安装依赖
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"

# 配置 API Key（推荐 DeepSeek — 便宜好用）
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY

# 验证组件（无需 API key）
python examples/demo.py

# 验证实时 API
python examples/live_test.py

# 运行全量测试
python -m pytest tests/ -v
```

### 基础用法

```python
import asyncio
from hermes_lite import HermesAgent, ProviderConfig, ToolRegistry, MemoryManager

async def main():
    config = ProviderConfig(provider="deepseek", model="deepseek-chat")
    memory = MemoryManager()
    tools = ToolRegistry()

    # 注册工具
    tools.register(
        name="get_weather",
        schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        handler=lambda city: f"{city}天气: 晴天，22°C",
        toolset="utility",
    )

    agent = HermesAgent(
        config=config,
        persona="你是一个有用的助手。",
        tool_registry=tools,
        memory_manager=memory,
    )

    result, _ = await agent.run("东京今天天气怎么样？")
    print(result)

asyncio.run(main())
```

### Coding Agent 模式

```bash
# 进入 coding agent 模式
hermes-lite --workspace /path/to/your/repo
```

在 coding agent 模式下，agent 拥有 40+ 个工作区感知工具，可以读文件、搜索代码、运行命令、应用补丁等。所有写操作和命令执行经过权限策略检查，敏感文件自动保护。

示例交互：

```
>> 帮我看看这个项目的整体结构
>> 找到所有处理用户认证的代码
>> 给 login 函数写一个单元测试
>> 修复 test_auth.py 中的类型错误
```

## 项目结构

```
src/hermes_lite/
├── agent.py              # 核心多轮 agent 循环
├── compression.py        # 上下文窗口压缩
├── cli.py                # CLI 入口和 REPL
├── api.py                # REST API 服务器
├── providers/            # LLM provider 适配器
├── tools/                # 工具注册系统和内置工具
├── memory/               # 持久记忆（SQLite）
├── skills/               # 文件式技能系统
├── sessions/             # 会话持久化 + 搜索
├── core/                 # 核心组件
├── prompts/              # 提示词模板
└── coding/               # Coding agent 模块
    ├── workspace.py      # 工作区抽象
    ├── permissions.py    # 交互式权限策略
    ├── shell.py          # 命令执行
    ├── sessions.py       # PTY 长会话管理
    ├── audit.py          # 审计日志
    ├── patches.py        # 统一 diff 补丁引擎
    ├── context.py        # 搜索和文件排行
    ├── diagnostics.py    # Python 语法诊断
    ├── extensibility.py  # Hook 和外部工具配置
    ├── git.py            # Git 操作封装
    ├── lsp.py            # LSP 客户端
    ├── mcp_client.py     # MCP 客户端
    ├── worktree_exec.py  # Git worktree 隔离执行
    └── subagents.py      # 子代理编排
```

## 开发指南

```bash
# 创建开发环境
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"

# 运行测试
python -m pytest tests/ -v

# 查看测试覆盖率
python -m pytest tests/ --cov=src/hermes_lite --cov-report=term-missing
```

### 测试

当前 213 个测试覆盖以下模块：

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_imports.py` | 导入、Provider 配置、工具注册、记忆、Agent |
| `test_coding_permissions_shell.py` | 权限策略和 shell 执行 |
| `test_coding_interactive_permissions.py` | 交互式权限（38 个测试） |
| `test_coding_sessions.py` | PTY 长命令会话（19 个测试） |
| `test_coding_editing.py` | 文本编辑和补丁应用（18 个测试） |
| `test_coding_context_enhanced.py` | 上下文索引和搜索（18 个测试） |
| `test_coding_context_diagnostics.py` | 上下文和诊断 |
| `test_coding_lsp_mcp.py` | LSP/MCP 客户端（22 个测试） |
| `test_coding_worktree.py` | Git worktree 子代理执行（6 个测试） |
| `test_coding_tools.py` | Coding 工具注册 |
| `test_compression.py` | 上下文压缩 |
| `test_sessions.py` | 会话管理 |
| `test_skills.py` | 技能系统 |

### 文档

```
doc/
├── specs/          # 技术规格说明
├── iterations/     # 产品迭代记录
├── verification/   # 技术验证报告
└── milestones/     # 里程碑文档
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — |
| `OPENAI_API_KEY` | OpenAI API 密钥 | — |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | — |
| `HERMES_PROVIDER` | 默认 LLM provider | `deepseek` |
| `HERMES_MODEL` | 默认模型 | `deepseek-chat` |
| `HERMES_WORKSPACE` | Coding agent 工作区路径 | — |

## License

MIT
