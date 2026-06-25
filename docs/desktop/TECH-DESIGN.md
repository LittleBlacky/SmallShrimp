# SmallShrimp Desktop — 技术架构设计

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 关联: @ref: PRD.md

---

## 1. 项目结构

```
smallshrimp-desktop/
├── package.json
├── electron-builder.yml          # electron-builder 打包配置
├── vite.config.ts                # Vite (Renderer 构建)
├── tsconfig.json
├── tailwind.config.js
│
├── src/
│   ├── main/                     # Electron Main Process
│   │   ├── index.ts              #   入口：创建窗口、注册 IPC
│   │   ├── python.ts             #   Python 子进程生命周期
│   │   ├── tray.ts               #   托盘图标 + 右键菜单
│   │   ├── ipc-handlers.ts       #   IPC 处理注册
│   │   └── updater.ts            #   自动更新 (P2)
│   │
│   ├── renderer/                 # React 前端
│   │   ├── index.html
│   │   ├── main.tsx              #   React 入口
│   │   ├── App.tsx               #   根组件：路由 + 布局
│   │   │
│   │   ├── pages/                #   页面级组件
│   │   │   ├── ChatPage.tsx      #     聊天主页面（F1）
│   │   │   ├── SettingsPage.tsx  #     设置页面（F3）
│   │   │   ├── AgentPage.tsx     #     Agent 管理页面（F2, P1）
│   │   │   ├── McpPage.tsx       #     MCP 管理页面（F8, P1）
│   │   │   ├── MemoryPage.tsx    #     记忆管理页面（F4, P2）
│   │   │   ├── SkillPage.tsx     #     技能管理页面（F5, P2）
│   │   │   └── CronPage.tsx      #     定时任务页面（F6, P2）
│   │   │
│   │   ├── components/           #   可复用组件
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.tsx   #       侧边栏（导航 + 会话列表）
│   │   │   │   ├── TitleBar.tsx  #       自定义标题栏
│   │   │   │   └── MainLayout.tsx#       整体布局容器
│   │   │   ├── chat/
│   │   │   │   ├── ChatView.tsx  #       消息列表（虚拟滚动）
│   │   │   │   ├── MessageItem.tsx#      单条消息（支持 Markdown）
│   │   │   │   ├── InputBox.tsx  #       输入框（Shift+Enter, /, @）
│   │   │   │   ├── ToolCallCard.tsx#     工具调用卡片
│   │   │   │   └── StreamingText.tsx#    流式文本渲染
│   │   │   ├── session/
│   │   │   │   ├── SessionList.tsx#      会话列表
│   │   │   │   └── SessionItem.tsx#      单个会话项
│   │   │   └── common/
│   │   │       ├── AgentSwitcher.tsx#     Agent 下拉选择器
│   │   │       ├── ServerStatus.tsx#      服务状态指示器
│   │   │       └── ConfirmDialog.tsx#     确认对话框
│   │   │
│   │   ├── stores/               #   Zustand 状态管理
│   │   │   ├── chatStore.ts      #     聊天状态（消息、流式）
│   │   │   ├── sessionStore.ts   #     会话列表 + 当前会话
│   │   │   ├── configStore.ts    #     用户配置
│   │   │   ├── agentStore.ts     #     Agent 列表
│   │   │   └── serverStore.ts    #     Server 进程状态
│   │   │
│   │   ├── hooks/                #   自定义 Hooks
│   │   │   ├── useWebSocket.ts   #     WebSocket 连接 + 自动重连
│   │   │   ├── useStreaming.ts   #     流式消息处理
│   │   │   ├── useServerStatus.ts#     Server 状态轮询
│   │   │   └── useIpc.ts         #     IPC 通信封装
│   │   │
│   │   ├── services/             #   API 调用层
│   │   │   ├── api.ts            #     HTTP 客户端（fetch 封装）
│   │   │   ├── ws.ts             #     WebSocket 客户端
│   │   │   └── ipc.ts            #     IPC 通道常量定义
│   │   │
│   │   └── styles/
│   │       └── globals.css       #   Tailwind + 全局样式
│   │
│   └── shared/                   #   Main ↔ Renderer 共享类型
│       ├── ipc-channels.ts       #     IPC 通道名常量
│       └── types.ts              #     共享类型定义
│
├── resources/                    #   静态资源
│   ├── icon.ico                  #   Windows 图标
│   ├── icon.icns                 #   macOS 图标
│   └── tray/                     #   托盘图标（各状态）
│       ├── stopped.png
│       ├── starting.png
│       ├── running.png
│       └── error.png
│
└── tests/
    └── ...
```

---

## 2. 组件树

```
App
├── ServerStatusIndicator          # 全局：服务状态灯
├── AgentSwitcher                  # 全局：Agent 下拉（顶部/底部）
│
└── MainLayout (路由容器)
    ├── Sidebar
    │   ├── NavMenu                # 导航：🏠聊天 ⚙️设置 📦Agent ...
    │   ├── SessionList            # (ChatPage 时显示)
    │   │   └── SessionItem[]
    │   └── ServerActions          # 启动/停止按钮
    │
    └── <Page>                     # 右侧内容区（路由切换）
        ├── ChatPage
        │   ├── ChatView           # 消息列表
        │   │   └── MessageItem[]  # 每条消息
        │   │       ├── MarkdownRenderer
        │   │       ├── CodeBlock (语法高亮 + 复制)
        │   │       ├── ToolCallCard[] (折叠)
        │   │       └── StreamingText (打字动画)
        │   └── InputBox
        │       ├── TextArea (Shift+Enter)
        │       └── SendButton
        │
        ├── SettingsPage           # 配置表单（F3）
        ├── AgentPage              # Agent 列表 + 编辑（F2）
        ├── McpPage                # MCP 管理（F8）
        ├── MemoryPage             # 记忆管理（F4）
        ├── SkillPage              # 技能管理（F5）
        └── CronPage               # 定时任务（F6）
```

---

## 3. 数据流

### 3.1 聊天消息流

```
用户输入
  │
  ▼
InputBox ──▶ chatStore.addUserMessage()
  │
  ├──▶ ws.send({ type: "user_message", content: "..." })
  │
  ▼
WebSocket ──▶ SmallShrimp Server ──▶ LLM
  │
  ▼ (逐帧推送)
useStreaming hook
  ├── text_delta  → chatStore.appendStreamingText()
  │                  └──▶ MessageItem (StreamingText 组件实时渲染)
  ├── tool_call   → chatStore.addToolCall()
  │                  └──▶ MessageItem (ToolCallCard 展开)
  ├── tool_result → chatStore.updateToolResult()
  └── text_done   → chatStore.finishStreaming()
                     └──▶ sessionStore.refresh() (更新标题)
```

### 3.2 状态管理架构

```
┌─────────────────────────────────────────────────┐
│                  Zustand Stores                   │
│                                                   │
│  serverStore     chatStore      sessionStore      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │ status   │  │ messages │  │ sessions[]   │   │
│  │ port     │  │ streaming│  │ currentId    │   │
│  │ error    │  │ toolCalls│  │ isLoading    │   │
│  └──────────┘  └──────────┘  └──────────────┘   │
│                                                   │
│  configStore     agentStore                       │
│  ┌──────────┐  ┌──────────┐                      │
│  │ providers│  │ agents[] │                      │
│  │ defaults │  │ current  │                      │
│  │ mcpConf  │  └──────────┘                      │
│  └──────────┘                                     │
└─────────────────────────────────────────────────┘
```

### 3.3 Server 启动流程

```
用户点击「启动」
  │
  ▼
Renderer: IPC 'start-server'
  │
  ▼
Main: python.spawnServer()
  ├── 1. 查找 Python 环境 (.venv > PATH > 默认)
  ├── 2. child_process.spawn("python", ["-m", "SmallShrimp.server.server"])
  ├── 3. 轮询 GET http://localhost:PORT/health (间隔 500ms, 超时 30s)
  ├── 4. 就绪 → IPC 'server-status' → Renderer 更新 serverStore
  └── 5. 监听子进程 exit/error → 自动重启 / 通知用户
```

---

## 4. IPC 通道定义

```typescript
// src/shared/ipc-channels.ts

// Main → Renderer
'SERVER_STATUS'      // { status: 'stopped'|'starting'|'running'|'error', port?: number, error?: string }
'UPDATE_AVAILABLE'   // P2: 新版本可用

// Renderer → Main
'START_SERVER'       // 请求启动 Python Server
'STOP_SERVER'        // 请求停止 Python Server
'GET_SERVER_PORT'    // 获取当前 Server 端口
'READ_FILE'          // 读取本地文件（绕过 Server 直接读）
'WRITE_FILE'         // 写入本地文件
'GET_APP_VERSION'    // 获取应用版本
'MINIMIZE_TO_TRAY'   // 最小化到托盘
'QUIT_APP'           // 退出应用
```

---

## 5. 关键设计决策

### 5.1 为什么数据通信直连 Server 而不经过 Main Process

Renderer 通过 `fetch` / `WebSocket` 直连 `localhost:PORT`，**不**走 IPC 中转。

- 优点：零额外延迟，LLM 流式输出延迟敏感
- Main Process 只管控制指令（启停 Server、文件读写、窗口管理）

### 5.2 虚拟滚动

聊天消息历史可能很长（> 1000 条），使用 `@tanstack/react-virtual` 实现虚拟滚动，只渲染可视区域内的消息。

### 5.3 流式渲染

不使用防抖。每个 `text_delta` 事件直接追加到 Zustand store，React 自动重渲染。用 `requestAnimationFrame` 批量更新 DOM 避免掉帧。

### 5.4 自动保存

输入框内容存入 `localStorage`，切换会话/崩溃恢复时不丢失草稿。

### 5.5 主题

使用 Tailwind 的 `dark:` 前缀 + CSS 变量，Zustand `themeStore` 存 `'light'|'dark'|'system'`。`<html class="dark">` 切换。

---

## 6. 技术栈清单

| 类别 | 选型 | 版本 |
|------|------|------|
| 桌面框架 | Electron | 28+ |
| 前端框架 | React | 18 |
| 语言 | TypeScript | 5.x |
| 样式 | Tailwind CSS | 3.x |
| 组件库 | shadcn/ui | latest |
| 状态管理 | Zustand | 4.x |
| Markdown | react-markdown + remark-gfm | latest |
| 代码高亮 | rehype-highlight | latest |
| 虚拟滚动 | @tanstack/react-virtual | 3.x |
| 打包 | electron-builder | 24.x |
| 构建 | Vite (electron-vite) | 5.x |

---

## 9. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始版本：项目结构、组件树、数据流、IPC 设计 |
