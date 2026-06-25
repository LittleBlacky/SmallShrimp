# Agent 聊天 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案

---

## 1. 产品概述

### 1.1 产品定位

Agent 聊天是 SmallShrimp Desktop 的核心交互闭环：用户在图形界面中与 AI Agent 对话，消息实时流式渲染，历史会话可管理。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| 必须打开终端输入命令 | 图形聊天界面，点击即用 |
| 会话历史难浏览 | 侧边栏会话列表，点击切换 |
| 工具调用过程不可见 | 实时展示工具调用卡片 |
| 看不到 Agent 的思考过程 | 流式输出，逐字渲染 |

### 1.3 目标用户

- **AI 重度用户**：需要高效的多会话 AI 对话入口
- **开发者**：需要实时看到 Agent 的工具调用过程
- **非技术用户**：像聊天软件一样使用 AI

---

## 2. 功能范围

### 2.1 MVP（P0 — 必须实现）

| 模块 | 功能 | 说明 |
|------|------|------|
| **聊天界面** | 消息收发 + Markdown 渲染 + 代码高亮 | 类 ChatGPT 的对话体验 |
| **流式输出** | LLM 回复逐字显示 | 通过 WebSocket 推送 |
| **会话管理** | 新建/切换/删除会话 | 左侧会话列表 |

### 2.2 V1（P1 — 体验完善）

| 模块 | 功能 |
|------|------|
| **工具调用可视化** | 工具调用过程以卡片形式展示（读取文件、执行命令、搜索网页等） |
| **文件拖拽上传** | 拖拽文件到聊天框，自动读取内容或作为附件 |
| **消息操作** | 复制、重新生成、编辑上一条消息 |

### 2.3 V2（P2 — 高级功能）

| 模块 | 功能 |
|------|------|
| **多 Agent 路由** | 可视化查看路由规则 |

---

## 3. 技术架构总览

```
┌─────────────────────────────────────────────────┐
│         Renderer (React - 前端 UI)               │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │ 聊天界面  │  │ 会话列表  │  │ 工具调用卡片  │   │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
│       └──────────────┼──────────────┘            │
│                      │ HTTP REST + WebSocket      │
└──────────────────────┼───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│         SmallShrimp Server (Python)              │
│  /ws/chat     → WebSocket 聊天消息流              │
│  /api/sessions → 会话 CRUD                       │
│  EventBus     → Agent 消息路由                   │
└─────────────────────────────────────────────────┘
```

### 3.1 技术选型

| 层面 | 方案 | 理由 |
|------|------|------|
| **Markdown 渲染** | react-markdown + rehype-highlight | 消息内容渲染 |
| **WebSocket** | 原生 WebSocket + 自动重连 | 流式消息推送 |
| **代码高亮** | rehype-highlight + 复制按钮 | 开发者体验 |

---

## 4. UI 设计

### 4.1 聊天布局

```
┌──────────┬──────────────────────────────────────┐
│  侧边栏   │              主聊天区                 │
│          │                                      │
│  🔍 搜索  │  ┌────────────────────────────────┐  │
│  ─────── │  │  消息历史（滚动）                 │  │
│  🏠 首页  │  │  ┌──────────┐ ┌──────────┐     │  │
│  ├ 会话1  │  │  │ 用户消息   │ │ AI 回复   │     │  │
│  ├ 会话2  │  │  └──────────┘ └──────────┘     │  │
│  ├ 会话3  │  │  ┌─────────────────────────┐   │  │
│  └ ...   │  │  │ 🔧 工具调用: read_file   │   │  │
│          │  │  └─────────────────────────┘   │  │
│  ─────── │  └────────────────────────────────┘  │
│  ⚙️ 设置  │  ┌────────────────────────────────┐  │
│  🧠 记忆  │  │  输入框                      📎  │  │
│  📦 技能  │  │  [Agent: pickle ▾]    [发送 ▶] │  │
│  ⏰ 定时  │  └────────────────────────────────┘  │
└──────────┴──────────────────────────────────────┘
```

### 4.2 消息类型

| 类型 | 渲染方式 |
|------|----------|
| 普通文本 | Markdown 渲染（表格、列表、加粗等） |
| 代码块 | 语法高亮 + 复制按钮 + 语言标签 |
| 流式输出 | 逐字追加，光标闪烁动画 |
| 工具调用 | 折叠卡片（工具名 + 参数 + 结果），可展开 |
| 错误消息 | 红色边框，显示错误详情 |
| 系统消息 | 灰色居中文字（如"Agent 已切换为 pickle"） |

---

## 5. 模块详细设计

### 5.1 Agent 核心层

**消息流完整链路：**

```
用户输入 → Renderer
    │ WebSocket send
    ▼
SmallShrimp Server
    │ EventBus: InboundEvent
    ▼
Agent Worker
    ├── 1. 加载 Agent 定义 (AGENT.md)
    ├── 2. 构建上下文 (context_guard.py: Token 预算管理)
    │       ├── 系统提示词 (AGENT.md 正文 + SOUL.md + 注入的 Skill)
    │       ├── 会话历史 (conversation_buffer.py: 滑动窗口)
    │       └── 用户新消息
    ├── 3. 加载可用工具 (ToolRegistry)
    ├── 4. LLM 调用 (provider/llm/thinking.py)
    │       └── 流式响应 → WebSocket 逐帧推送
    ├── 5. 工具调用检测 (tool_use 块解析)
    │       ├── 通过 WebSocket 推送 tool_call 事件
    │       ├── 执行工具 (sandbox.py + tool_guardrails.py)
    │       └── 通过 WebSocket 推送 tool_result 事件
    └── 6. 消息持久化 (history.py → workspace/sessions/)
```

**上下文管理：**

| 组件 | 文件 | 职责 |
|------|------|------|
| Token 预算 | `context_guard.py` | 计算 Token 用量，触发压缩策略 |
| 会话缓冲 | `conversation_buffer.py` | 滑动窗口管理消息历史 |
| 话题分段 | `topic_segmenter.py` | 检测话题切换，标记压缩边界 |
| 压缩策略 | `context_guard.py` | 4 级主动压缩（摘要/截断/遗忘/重置） |

**会话隔离：**

- 每个会话独立的消息历史文件：`workspace/sessions/<session_id>.jsonl`
- 跨会话切换时，Server 端切换对应的 conversation_buffer
- 会话元数据：`workspace/sessions/.meta.json`（ID、标题、创建时间、最后活跃时间、Agent）

### 5.2 后端 API 层

#### WebSocket 协议 (`/ws/chat`)

**连接参数（Query String）：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent` | string | 是 | Agent 名称 |
| `session_id` | string | 否 | 会话 ID，不传则新建会话 |

**客户端 → 服务端（发送消息）：**

```json
{
  "type": "user_message",
  "content": "帮我读一下 README.md",
  "attachments": [
    { "type": "file", "path": "/absolute/path/to/file.txt" }
  ]
}
```

**服务端 → 客户端（推送事件）：**

| 事件类型 | 说明 | payload |
|----------|------|---------|
| `session_created` | 新会话已创建 | `{ "session_id": "abc123" }` |
| `text_delta` | 流式文本片段 | `{ "content": "你好" }` |
| `text_done` | 文本生成完毕 | `{ "content": "完整回复" }` |
| `tool_call` | 开始调用工具 | `{ "tool": "read_file", "args": {...} }` |
| `tool_result` | 工具调用结果 | `{ "tool": "read_file", "result": "...", "error": null }` |
| `error` | 错误 | `{ "code": "TOKEN_EXCEEDED", "message": "..." }` |

**流式推送时序：**

```
Client                              Server
  │── connect(agent, session_id) ───▶│
  │◀── session_created ─────────────│
  │── user_message ────────────────▶│
  │◀── text_delta("你") ───────────│
  │◀── text_delta("好") ───────────│
  │◀── tool_call(read_file) ──────│
  │◀── tool_result(read_file) ────│
  │◀── text_delta("文件") ────────│
  │◀── text_done ─────────────────│
```

#### REST API

**`GET /api/sessions`** — 会话列表

```json
// Response 200:
{
  "sessions": [
    {
      "id": "abc123",
      "title": "帮我读一下 README",
      "agent": "pickle",
      "created_at": "2026-06-25T10:00:00Z",
      "last_active_at": "2026-06-25T10:05:00Z",
      "message_count": 12
    }
  ]
}
```

**`GET /api/sessions/:id`** — 会话消息历史

Query: `?offset=0&limit=50`

```json
// Response 200:
{
  "session_id": "abc123",
  "messages": [
    { "role": "user", "content": "你好", "timestamp": "..." },
    { "role": "assistant", "content": "你好！有什么可以帮你？", "timestamp": "..." }
  ],
  "has_more": true,
  "total": 120
}
```

**`DELETE /api/sessions/:id`** — 删除会话

```json
// Response 200:
{ "deleted": true }
```

**`PATCH /api/sessions/:id/rename`** — 重命名会话

```json
// Request:
{ "title": "新标题" }

// Response 200:
{ "session_id": "abc123", "title": "新标题" }
```

#### 会话存储设计

```
workspace/sessions/
├── .meta.json              # 会话元数据索引
│   [
│     {
│       "id": "abc123",
│       "title": "帮我读 README",
│       "agent": "pickle",
│       "created_at": "...",
│       "last_active_at": "..."
│     }
│   ]
├── abc123.jsonl            # 会话消息（JSON Lines）
│   {"role":"user","content":"你好","timestamp":"..."}
│   {"role":"assistant","content":"你好！","timestamp":"..."}
├── def456.jsonl
└── ...
```

**错误码：**

| 码 | 含义 |
|------|------|
| `SESSION_NOT_FOUND` | 会话不存在 |
| `AGENT_NOT_FOUND` | Agent 不存在 |
| `TOKEN_EXCEEDED` | Token 超限 |
| `PROVIDER_ERROR` | LLM Provider 调用失败 |
| `TOOL_TIMEOUT` | 工具执行超时 |
| `WS_CONNECTION_LOST` | WebSocket 连接断开 |

### 5.3 桌面端 UI 层

**输入框：**

- `Shift+Enter` 换行，`Enter` 发送
- `/` 唤起斜杠命令（`/skill`, `/agent` 等）
- `@` 提及文件（自动补全路径）
- 粘贴图片自动存为临时文件并发送路径

**会话管理：**

- 会话列表按最后活跃时间排序
- 支持重命名、删除（确认对话框）
- 会话自动命名（取第一条消息前 30 字）
- 搜索会话（搜索消息内容）

---

## 6. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | 聊天界面 + 流式输出 + 会话列表 | 1 周 |
| P1 | 工具调用可视化 + 文件拖拽 + 消息操作 | 3 天 |

---

## 7. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| WebSocket 断连 | 消息丢失 | 自动重连 + 消息本地缓存 |
| 大消息历史渲染卡顿 | 体验差 | 虚拟滚动 + 分页加载 |

---

## 8. 附录

### 8.1 参考产品

- **ChatGPT Desktop**：聊天体验
- **Claude Desktop**：工具调用展示

### 8.2 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 从桌面端 PRD 拆分，初始版本 |
