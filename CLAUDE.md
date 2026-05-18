# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

SmallShrimp 是一个 AI Agent 框架，用于构建智能体应用。支持多 Provider（DeepSeek/Claude/Gemini 等）和思考模式。

## 运行方式

```bash
# 使用 smallshrimp conda 环境运行
conda run -n smallshrimp python -m src.SmallShrimp.cli.chat

# 或激活环境后运行
conda activate smallshrimp
smallshrimp chat
```

## 核心架构

### Agent 系统
- `Agent` - 智能体定义（agent_def + config + llm + tool_registry）
- `AgentSession` - 会话实例（包含 SessionState）
- `SessionState` - 会话状态管理（messages + pending_reasoning_content）
- `AgentLoader` - 从 AGENT.md YAML frontmatter 加载 AgentDef

### 思考模式（Thinking Mode）
- `ThinkingStrategy` 基类定义了 prepare_request/extract_reasoning_content/should_store_response
- 支持 DeepSeek、Claude（Anthropic）、Gemini
- **重要**：DeepSeek 的 reasoning_content 需要在下一轮请求中传回对应 assistant 消息
  - 存储在 `SessionState.pending_reasoning_content`
  - `build_messages()` 会自动构建带 reasoning_content 的 assistant 消息

### 消息类型
- `HumanMessage` / `AssistantMessage` / `ToolMessage` / `SystemMessage`
- `AssistantMessage` 可包含 `tool_calls` 和 `reasoning_content`（dataclass 字段通过赋值设置）

### 工具系统
- `ToolRegistry` - 工具注册与执行
- `@tool` 装饰器 - 将异步函数注册为工具
- 内置工具：`read`, `write`, `glob`, `grep`（文件操作）
- Web 工具：`websearch`, `webread`（网页搜索/读取）
- `SkillLoader` - 从 SKILL.md 加载技能

### 命令系统
- `/skill <name>` - 加载技能内容
- `/clear` - 清空会话
- `/help` - 显示帮助

## Workspace 目录结构

```
workspace/
├── config.user.yaml      # 用户配置（API keys、模型选择）
├── agents/               # Agent 定义
│   └── {name}/
│       ├── AGENT.md      # Agent 配置（YAML frontmatter + 指令）
│       └── SOUL.md       # Agent 个性描述
├── skills/               # 技能定义
│   └── {name}/
│       └── SKILL.md
├── crons/                # 定时任务
├── sessions/             # 会话历史（JSON）
└── memories/             # 持久化记忆
    ├── topics/           # 永久事实
    ├── projects/         # 项目上下文
    └── daily-notes/      # 日常记录
```

## 文件格式

### AGENT.md（YAML frontmatter）
```markdown
---
name: Pickle
description: A friendly cat assistant
llm:
  provider: deepseek
  model: deepseek/deepseek-v4-flash
  temperature: 0.7
  context_window: 1000000
---

# About Pickle
You are Pickle, a friendly cat assistant.
```

### SKILL.md（YAML frontmatter）
```markdown
---
id: skill-creator
name: skill-creator
description: Guide for creating effective skills
---

# Skill Creator Guide
...
```

## 多 Agent 调度

使用 `subagent_dispatch` 委托任务给其他 Agent：
```python
subagent_dispatch(agent_id="cookie", task="Remember that user prefers Python")
```

- `cookie` agent - 记忆管理器，用于存储/检索记忆
- `pickle` agent - 默认助手，处理日常任务

## Provider 配置

`config.user.yaml` 示例：
```yaml
default_provider: deepseek
providers:
  deepseek:
    api_key: xxx
    api_base: https://api.deepseek.com
```

## 配置热重载

`Config` 类支持配置文件热重载，监听 `config.user.yaml` 和 `config.runtime.yaml` 变更自动重载：

```python
from src.SmallShrimp.utils.config import Config

config = Config.from_yaml("workspace/config.user.yaml")
config.on_change(lambda data: print("配置已更新"))
config.start_auto_reload()  # 启动文件监听
config.stop_auto_reload()    # 停止监听
config.reload()              # 手动重载
```

多配置文件按优先级深度合并（后面覆盖前面）：
1. `config.user.yaml` - 用户配置
2. `config.runtime.yaml` - 运行时配置

## Web 搜索配置

支持多 Provider 按优先级自动降级：
```yaml
websearch:
  # Priority 1: 自定义 API（最高优先级）
  custom:
    enabled: true
    api_url: "https://your-search-api.com/search"
    method: GET
    params:
      q: "{query}"
    field_mapping:
      title: "title"
      url: "link"
      snippet: "description"

  # Priority 2: 预置 Provider
  provider:
    name: serpapi  # 或 brave, duckduckgo
    api_key: your-api-key

  # Priority 3: 默认兜底（duckduckgo 免费）
  default: duckduckgo
```

