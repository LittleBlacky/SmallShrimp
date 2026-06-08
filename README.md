<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/version-0.2.0-blueviolet" alt="Version 0.2.0">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

<h1 align="center">🦐 SmallShrimp</h1>

<p align="center">
  SmallShrimp 是一个模块化、事件驱动的 AI 智能体框架，提供从单 Agent 聊天到多 Agent 协作、从 CLI 到多平台渠道、从内存持久化到生产级安全防护的全链路能力。
</p>

---

## ✨ 特性一览

| 领域 | 能力 |
|------|------|
| **🤖 多 Agent 管理** | 基于 `AGENT.md` 的 Agent 定义、动态加载、多 Agent 路由分发 |
| **🧠 多模型支持** | 通过 litellm 对接 100+ LLM（OpenAI / Anthropic / DeepSeek / 本地 Ollama 等） |
| **🔧 工具系统** | 文件读写、Shell 执行、Web 搜索/阅读、内存操作、子 Agent 派发 |
| **📦 Skill 系统** | 通过 `SKILL.md` 为 Agent 注入领域知识，动态加载 |
| **💾 持久化记忆** | 5 层记忆体系（用户画像、事实、项目、反思、会话）+ 去重/排名/合并 |
| **🔐 七层安全防护** | 信任对话框 → 权限模式 → Shell AST 分析 → 沙箱隔离 → 用户确认 |
| **🌐 多平台渠道** | Discord / Telegram / 企业微信（群机器人 + 应用） |
| **📅 定时任务** | 基于 croniter 的定时调度，自动唤醒 Agent 执行任务 |
| **🔄 事件驱动架构** | 异步事件总线，Worker 编排，自动崩溃恢复 |
| **⚡ 配置热重载** | 修改配置无需重启，Watchdog 实时监听 |
| **🧩 MCP 协议支持** | 集成 Model Context Protocol，通过 stdio/SSE 连接外部工具服务 |
| **🔀 子 Agent 派发** | Agent 可以派发子任务给其他 Agent，支持多 Agent 协作 |
| **📝 上下文压缩** | 4 级主动压缩策略，智能管理 Token 预算 |
| **📊 失败学习** | 跨轮次错误模式检测，自动生成改进提示 |
| **📡 WebSocket 服务** | FastAPI + WebSocket，支持程序化交互 |

---

## 🚀 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/LittleBlacky/SmallShrimp.git
cd SmallShrimp

# 创建虚拟环境（推荐）
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .\.venv\Scripts\Activate.ps1  # Windows

# 安装
pip install -e .
```

### 初始化工作区

```bash
smallshrimp init
```

该命令会创建以下目录结构：

```
workspace/
├── config.user.yaml         # 用户配置（设置 API Key 等）
├── agents/
│   └── pickle/              # 默认 Agent
│       ├── AGENT.md         # Agent 定义（名称、模型、提示词）
│       └── SOUL.md          # (可选) 人格设定
├── skills/                   # 技能目录
│   └── <skill-name>/
│       └── SKILL.md
├── crons/                    # 定时任务目录
│   └── <job-id>/
│       └── CRON.md
├── memories/                 # 持久化记忆
│   ├── profile/
│   ├── facts/
│   ├── projects/
│   ├── reflections/
│   └── sessions/
├── sessions/                 # 会话历史
└── .cache/                   # 缓存（信任状态、失败学习等）
```

### 配置 API Key

编辑 `workspace/config.user.yaml`，设置你的 LLM 提供方 API Key：

```yaml
default_provider: deepseek
default_agent: pickle

providers:
  deepseek:
    api_key: sk-your-api-key-here
    api_base: https://api.deepseek.com
```

> 支持任意 litellm 兼容的 provider，详见 [litellm 文档](https://docs.litellm.ai/docs/providers)。

### 启动聊天

```bash
smallshrimp chat
```

---

## 📖 核心概念

### Agent 定义

每个 Agent 由一个目录和一个 `AGENT.md` 文件定义：

```yaml
---
name: Pickle
description: 默认助手
llm:
  provider: deepseek
  model: deepseek/deepseek-chat
  temperature: 0.7
  context_window: 200000
tools:
  - read
  - write
  - shell
  - websearch
---

# Pickle

你是一个友好的 AI 助手。用中文回复。
```

`AGENT.md` 的 YAML 头部定义了 Agent 的元数据（名称、使用的模型、可用的工具等），正文定义了系统提示词。

### 技能（Skills）

技能是通过 `SKILL.md` 为 Agent 注入的领域知识包，可动态加载：

```bash
# 在聊天中加载技能
/skill my-skill
```

或在配置中配置自动注入。

### 定时任务（Crons）

通过 `CRON.md` 定义定时任务，支持标准的 cron 表达式：

```yaml
---
name: Daily Digest
description: 每日总结
agent: pickle
schedule: "0 9 * * *"
---
请总结今天的事件。
```

### MCP 集成

在配置中声明 MCP 服务器，Agent 会自动发现并使用其工具：

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: [-y, @modelcontextprotocol/server-filesystem, /path/to/repo]
  remote_db:
    transport: sse
    url: https://db-mcp.example.com/sse
```

---

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────┐
│                      Server                          │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Agent     │  │ Delivery │  │ Channel           │  │
│  │ Worker(s) │  │ Worker   │  │ Worker(s)          │  │
│  └─────┬────┘  └────┬─────┘  └────────┬──────────┘  │
│        │             │                 │              │
│  ┌─────▼─────────────▼─────────────────▼──────────┐  │
│  │                  EventBus                       │  │
│  │  InboundEvent → Agent → OutboundEvent → Delivery│  │
│  └────────────────────────────────────────────────┘  │
│  ┌──────────┐  ┌──────────┐                         │
│  │  Cron    │  │WebSocket │                         │
│  │  Worker  │  │  Worker  │                         │
│  └──────────┘  └──────────┘                         │
└─────────────────────────────────────────────────────┘
```

### 工作流

1. **CLI 输入** → `InboundEvent` 发布到 EventBus
2. **AgentWorker** 消费事件，调用 `Agent.chat()` 处理
3. Agent 执行工具调用（文件读写、Shell、Web搜索等）
4. 结果收集后提交给 LLM 生成回复
5. **OutboundEvent** 发布回 EventBus
6. **DeliveryWorker** 消费并路由到对应渠道输出

### 模块结构

```
src/SmallShrimp/
├── core/              # 核心逻辑
│   ├── agent.py           # Agent 会话管理、工具调用循环
│   ├── agent_loader.py    # Agent 定义加载
│   ├── context.py         # 运行时上下文
│   ├── context_guard.py   # 4 级上下文压缩
│   ├── eventbus.py        # 异步事件总线
│   ├── events.py          # 事件类型定义
│   ├── history.py         # 会话历史持久化
│   ├── message.py         # 消息类型
│   ├── prompt_builder.py  # 7 层提示词组装
│   ├── routing.py         # 多 Agent 路由
│   ├── mcp.py             # MCP 协议集成
│   ├── skill_loader.py    # 技能发现与加载
│   ├── skill_def.py       # SKILL.md 解析
│   ├── cron_loader.py     # 定时任务发现
│   ├── shell_guard.py     # Shell AST 安全分析
│   ├── sandbox.py         # 沙箱隔离
│   ├── trust.py           # 信任对话框
│   ├── permissions.py     # 权限模式
│   ├── tool_guardrails.py # 工具级安全护栏
│   ├── correction.py      # 用户纠错检测
│   ├── failure_learning.py# 失败模式学习
│   ├── session_state.py   # 会话状态管理
│   ├── worker.py          # 基础 Worker
│   ├── commands/          # 斜杠命令
│   └── memory/            # 持久化记忆系统
├── tools/              # 工具系统
│   ├── registry.py        # 工具注册中心
│   ├── base.py            # 工具基类
│   ├── decorators.py      # @tool 装饰器
│   ├── builtin_tools.py   # 内置工具（read/write/glob/grep）
│   ├── shell_tool.py      # Shell 执行工具
│   ├── skill_tool.py      # 技能加载工具
│   ├── web_tools.py       # Web 搜索/阅读工具
│   ├── memory_tool.py     # 记忆操作工具
│   ├── subagent_tool.py   # 子 Agent 派发工具
│   ├── post_message_tool.py # 渠道消息发送
│   └── cron_tool.py       # 定时任务管理工具
├── provider/           # 外部服务集成
│   └── llm/               # LLM 多模型支持
│       ├── base.py            # 统一 LLM 接口
│       └── thinking.py        # 思考模型策略
│   ├── web_search/        # Web 搜索引擎
│   └── web_read/          # 网页内容读取
├── channels/           # 多平台渠道
│   ├── base.py            # 渠道抽象接口
│   ├── discord_channel.py # Discord
│   ├── telegram_channel.py# Telegram
│   ├── wecom_channel.py   # 企业微信群机器人
│   └── wecom_app_channel.py# 企业微信应用
├── server/             # 服务端
│   ├── server.py          # 协调器
│   ├── agent_worker.py    # Agent 事件处理
│   ├── delivery_worker.py # 消息投递
│   ├── channel_worker.py  # 渠道监听
│   ├── cron_worker.py     # 定时调度
│   ├── websocket_worker.py# WebSocket
│   └── app.py             # FastAPI 应用
├── cli/                # 命令行界面
│   ├── main.py            # CLI 入口
│   └── chat.py            # 交互式聊天
└── utils/              # 工具
    ├── config.py          # 配置管理
    ├── config_reloader.py # 热重载
    └── def_loader.py      # 定义文件加载器
```

---

## 🔐 安全体系

SmallShrimp 设计了 **7 层安全防御** 来保护你的环境：

| 层级 | 组件 | 作用 |
|------|------|------|
| 1️⃣ | **Trust Dialog** (`trust.py`) | 首次访问项目时检测危险模式，询问用户是否信任 |
| 2️⃣ | **Permission Mode** (`permissions.py`) | 5 种权限模式控制写操作 |
| 3️⃣ | **Workspace Boundary** | 写操作限定在工作区内，保护系统路径 |
| 4️⃣ | **Shell AST Analysis** (`shell_guard.py`) | Tree-sitter 解析 Shell 命令语义，识别高危操作 |
| 5️⃣ | **Tool Guardrails** (`tool_guardrails.py`) | 工具级调用限制和结果大小预算 |
| 6️⃣ | **Sandbox** (`sandbox.py`) | OS 级隔离（Windows Job Object / Linux unshare / Docker） |
| 7️⃣ | **User Confirmation** | 敏感操作前请求用户确认 |

### 权限模式

| 模式 | 行为 |
|------|------|
| `default` | 写操作前询问 |
| `acceptEdits` | 自动批准文件编辑 |
| `bypassPermissions` | 绕过所有权限检查 |
| `plan` | 展示计划，请求批准 |
| `dontAsk` | 静默执行（不推荐） |

---

## 💾 记忆系统

5 层记忆架构，支持长期学习和个性化：

```
📋 用户画像 (profile)    → 用户的偏好、身份信息
📌 事实 (facts)          → 从对话中提取的关键事实
📁 项目 (projects)       → 项目级别上下文快照
💡 反思 (reflections)    → Agent 自我改进笔记
💬 会话 (sessions)       → 近期对话摘要
```

特性：

- **去重**：基于 SequenceMatcher 的近重复检测
- **重要性排序**：按重要性(1-10)、置信度(0-1)、召回次数、时效性排名
- **语义召回**：根据当前上下文自动召回相关记忆
- **记忆合并**：定期合并相似记录，减少冗余
- **每日笔记**：基于日期的结构化笔记系统

---

## 🔧 聊天命令

在聊天会话中，可以使用以下斜杠命令：

| 命令 | 说明 |
|------|------|
| `/skill <name>` | 动态加载技能 |
| `/clear` | 清除当前会话历史 |
| `/compact` | 手动触发上下文压缩 |
| `/help` | 显示可用命令列表 |
| `/context` | 查看当前上下文使用情况 |
| `/cron add <schedule> <name> <agent> <prompt>` | 添加定时任务 |
| `/route <pattern> <agent>` | 添加路由规则 |
| `/bindings` | 查看当前路由绑定 |
| `/agents` | 列出所有可用 Agent |

---

## 🌐 多渠道部署

### 配置文件示例

```yaml
channels:
  enabled: true
  telegram:
    bot_token: your-bot-token
    allowed_user_ids:
      - "your_user_id"
  discord:
    bot_token: your-bot-token
    channel_id: "1234567890"
  wecom:
    webhook_url: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
  wecom_app:
    corpid: your-corpid
    corpsecret: your-corpsecret
    agent_id: 1000001
```

### 多 Agent 路由

```yaml
routing:
  bindings:
    - agent: cookie          # Telegram 来的消息路由给 cookie
      value: platform-telegram:.*
    - agent: pickle          # 其他渠道走默认 pickle
      value: ".*"
```

路由优先级：**精确匹配 > 正则匹配 > 通配符**。

---

## 📡 启动服务模式

除了 CLI 聊天，还可以启动完整的服务端，同时运行 CLI、多渠道、定时任务和 WebSocket：

```bash
# 启动完整服务
smallshrimp chat --port 8000
```

服务模式下会自动：

- 启动 CLI 交互界面
- 监听各渠道的消息
- 调度定时任务
- 在指定端口提供 WebSocket 服务和 REST API

---

## 🧪 测试

```bash
# 运行全部测试
pytest

# 运行特定测试文件
pytest tests/test_memory.py
pytest tests/test_tool_registry.py
```

---

## 📚 学习资源

项目附带了一份完整的 **18 步教程** `build-your-own-openclaw/`，从零开始逐步构建 AI Agent：

| 阶段 | 步骤 | 主题 |
|------|------|------|
| **Phase 1** | 00-06 | 单 Agent 基础（聊天循环、工具、技能、持久化、命令、压缩、Web） |
| **Phase 2** | 07-10 | 事件驱动架构（EventBus、热重载、多渠道、WebSocket） |
| **Phase 3** | 11-15 | 自主与多 Agent（路由、定时任务、多层提示、消息回传、Agent 派发） |
| **Phase 4** | 16-17 | 生产级能力（并发控制、长期记忆） |

---

## 🛠️ 开发

```bash
# 安装开发依赖
pip install -e .

# 运行测试
pytest

# 构建分发包
python -m build
```

### 环境要求

- Python 3.11+
- 支持的操作系统：Windows / macOS / Linux

---

## 🔗 相关项目

- [pickle-bot](https://github.com/czl9707/pickle-bot) — 参考实现
- [OpenClaw](https://github.com/openclaw/openclaw) — 灵感来源
- [litellm](https://github.com/BerryLand/litellm) — LLM 多模型抽象层

---

## 📄 许可证

[MIT License](LICENSE)
