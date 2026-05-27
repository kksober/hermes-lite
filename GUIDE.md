# Hermes Lite 学习指南

> 写给有 Python 基础、第一次接触 AI Agent 框架的开发者。
> 读完这篇，你就能理解整个项目，并能自己动手改。

---

## 先搞清楚：Agent 到底是什么？

你用过 ChatGPT 网页版，对吧？你打字，它回复。这是一轮对话。

Agent 不一样。Agent 是一个**循环**：

```
你：「帮我看看项目里有多少个 Python 文件」
Agent 内部：
  第 1 轮：LLM 说「我需要执行 ls *.py 命令」
         → Agent 调系统执行命令，拿到结果
  第 2 轮：LLM 看到结果，说「有 15 个 Python 文件」
         → 没有更多工具要调了，返回给你
```

本质就是：**LLM 不只是说话，它能调用工具，然后根据工具的结果再决定下一步**。

---

## 项目的「骨架」：5 个核心概念

整个项目围绕这 5 个概念构建。你不需要先看懂代码，先理解它们是什么：

### 1. Provider — 选哪个模型

```python
config = ProviderConfig(provider="deepseek", model="deepseek-chat")
```

一句话：你想用哪个 LLM。DeepSeek、OpenAI、Anthropic 都可以，换一行配置就行。

**对应文件：** `src/hermes_lite/providers/adapters.py`（110 行，很短）

### 2. Tool — 让 LLM 能做的事

```python
tools.register(
    name="run_shell",
    handler=lambda command: subprocess.run(command, ...),
    toolset="terminal",
)
```

LLM 本身只能生成文字。Tool 让它能执行真实操作：跑命令、读文件、抓网页。

Tool 分 toolset（工具组）。你可以只启用"file"组的工具，不启用"terminal"组——控制权限。

**对应文件：** `src/hermes_lite/tools/registry.py`（150 行）

### 3. Agent Loop — 核心循环

这是整个项目的心脏。打开 `src/hermes_lite/agent.py`，找到 `run()` 方法，核心逻辑就这几行：

```python
while turn < max_turns:
    result = await agent.run(message_history=messages)
    if result 是文本 and 没有 tool_call:
        return result        # 结束了，返回给用户
    if result 有 tool_call:
        执行工具 → 把结果塞回 messages → 继续循环
```

就这么简单。LLM 说「我要调工具」→ 你帮它调 → 结果给 LLM → LLM 再决定。

**对应文件：** `src/hermes_lite/agent.py`（290 行，重点看 `run()` 方法）

### 4. Memory — 跨会话记忆

```python
memory.save("用户叫 Ethan，喜欢用 DeepSeek", target="user")
# 下次对话时，这段记忆自动注入 system prompt
```

不做成向量数据库那种重的东西。就是 SQLite 存文本，每轮对话前挑最重要的几条注入。

**对应文件：** `src/hermes_lite/memory/manager.py`（~200 行）

### 5. Skill — 固化的工作流

```python
skills = SkillManager(base_dir="skills/")
skills.load("code-review")   # 加载 SKILL.md 的内容
```

Skill 就是一个 Markdown 文件，里面写了「遇到某类任务该怎么做」。Agent 看到匹配的任务时，加载对应的 skill 作为参考。

和 Memory 的区别：Memory 存的是**事实**（用户偏好），Skill 存的是**流程**（怎么审查代码）。

**对应文件：** `src/hermes_lite/skills/manager.py`（220 行）

---

## 一条请求的完整旅程

这是理解项目最重要的图。跟着数字走：

```
用户输入：「帮我读 README.md」
          │
          ▼
   ┌──────────────────┐
   │ 1. build_system  │  组装 system prompt:
   │    _prompt()     │  角色设定 + 记忆 + skill 列表 + 工具描述
   └──────┬───────────┘
          │
          ▼
   ┌──────────────────┐
   │ 2. LLM 调用      │  DeepSeek API（通过 Pydantic AI）
   │                  │  LLM 看到 prompt，决定要调 read_file 工具
   └──────┬───────────┘
          │
          ▼
   ┌──────────────────┐
   │ 3. 判断响应类型   │
   │                  │
   │  有 tool_call? ──→ 4. 执行工具 → 结果追加到历史 → 回到 2
   │  纯文本?      ──→ 5. 返回给用户
   └──────────────────┘
```

**这个循环在代码里的位置：** `agent.py` 的 `run()` 方法，约 60 行。就这一段，是整个项目的灵魂。

---

## 阅读顺序建议

不要从头读到尾。按这个顺序，每个文件都很短：

| 顺序 | 文件 | 看什么 | 预计时间 |
|------|------|--------|---------|
| 1 | `providers/adapters.py` | ProviderConfig 类，怎么选模型 | 5 分钟 |
| 2 | `tools/registry.py` | ToolRegistry 三个方法 | 5 分钟 |
| 3 | `tools/builtin.py` | 真实工具的写法 | 5 分钟 |
| 4 | `agent.py` | **重点：`run()` 方法和循环** | 15 分钟 |
| 5 | `memory/manager.py` | SQLite 怎么存记忆 | 5 分钟 |
| 6 | `skills/manager.py` | Markdown 文件怎么变成 skill | 5 分钟 |
| 7 | `sessions/manager.py` | 会话怎么存和搜 | 5 分钟 |
| 8 | `compression.py` | token 估算 + 上下文压缩 | 5 分钟 |
| 9 | `cli.py` | REPL 怎么用上面这些 | 10 分钟 |

总共约 1 小时。

---

## 实验：改一行代码看看效果

最好的学习方式是动手改。试试：

**实验 1：换模型**

打开 `agent.py` 或者 CLI 启动代码，把 `deepseek-chat` 改成 `deepseek-reasoner`，看看推理模型的表现有什么不同。

**实验 2：加一个 tool**

在 `tools/builtin.py` 里加一个新工具，比如 `get_current_time`：

```python
def get_current_time() -> str:
    from datetime import datetime
    return datetime.now().isoformat()
```

然后在 `register_builtin_tools()` 里注册它。

**实验 3：改 system prompt**

打开 `agent.py`，找到 `build_system_prompt()`。把 persona 改成「你是一个说唱风格的助手」，看看 agent 的语气变化。

---

## 常见疑问

**Q: Pydantic AI 是什么？为什么用它？**

一个库，帮你跟 LLM 对话。你给它「用哪个模型」+「有什么工具」，它处理 API 调用的脏活。不是像 LangChain 那样的重型框架——它只管 LLM 交互这一层。

**Q: 为什么不用向量数据库做记忆？**

对于 agent 来说，记忆应该是「少量的关键事实」，不是「海量文档的语义匹配」。SQLite 存 10-20 条偏好和环境信息就够了。向量库是杀鸡用牛刀。

**Q: agent 会不会无限循环？**

`max_turns` 参数（默认 50）限制了最大轮数。如果 LLM 一直调工具不停，50 轮后自动停止。

**Q: 怎么加新的 LLM 提供商？**

在 `providers/adapters.py` 的 `ProviderConfig` 里加一个新选项，在 `_effective_api_key()` 和 `_model_string()` 里加对应的映射。Pydantic AI 原生支持 20+ 提供商。

---

## 下一步

- 看懂 `agent.py` 的 `run()` 循环后，尝试自己写一个最简版 agent（20 行就能跑）
- 给项目加一个你觉得缺的 tool
- 写一个你自己的 skill 放在 `skills/` 目录

你不需要看完所有代码才开始用。打开 CLI，跟它对话，遇到不懂的再回来看对应文件。
