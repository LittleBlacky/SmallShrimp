# SmallShrimp Desktop — 产品需求文档

> 版本: v0.4 | 日期: 2026-06-25 | 状态: 草案

---

## 1. 产品概述

### 1.1 产品定位

SmallShrimp Desktop 是 SmallShrimp AI Agent 框架的桌面客户端，让用户通过图形界面与本地 AI Agent 进行交互，无需接触命令行。

### 1.2 核心价值

| 痛点（现状） | 解决（桌面端） |
|---|---|
| 必须打开终端输入命令 | 图形界面，点击即用 |
| 配置靠手写 YAML | 可视化配置表单 |
| 会话历史难浏览 | 侧边栏会话列表，点击切换 |
| 工具调用过程不可见 | 实时展示工具调用卡片 |
| 记忆/技能管理靠文件系统 | 面板式管理界面 |

### 1.3 目标用户

- **AI 重度用户**：日常使用多个 LLM，需要一个统一的本地桌面入口
- **开发者**：需要本地 Agent 辅助编码、查资料、执行 Shell 任务
- **非技术用户**：想用 AI Agent 但不愿碰命令行

---

## 2. 功能范围总览

### 2.1 子需求清单

| 编号 | 子需求 | 优先级 | 文档 |
|------|--------|--------|------|
| F7 | 桌面壳 | P0 MVP | [features/01-desktop-shell/PRD.md](features/01-desktop-shell/PRD.md) |
| F1 | Agent 聊天 | P0 MVP | [features/02-agent-chat/PRD.md](features/02-agent-chat/PRD.md) |
| F3 | 配置管理 | P0 MVP | [features/03-configuration/PRD.md](features/03-configuration/PRD.md) |
| F2 | Agent 管理 | P0(切换) P1(编辑) | [features/04-agent-management/PRD.md](features/04-agent-management/PRD.md) |
| F8 | MCP 工具管理 | P1 | [features/05-mcp-management/PRD.md](features/05-mcp-management/PRD.md) |
| F4 | 记忆系统 | P2 | [features/06-memory-system/PRD.md](features/06-memory-system/PRD.md) |
| F5 | 技能系统 | P2 | [features/07-skill-system/PRD.md](features/07-skill-system/PRD.md) |
| F6 | 定时任务 | P2 | [features/08-cron-tasks/PRD.md](features/08-cron-tasks/PRD.md) |

### 2.2 MVP 功能一览

```
P0（必须完成才能发布）:
  01 桌面壳      → 进程管理 + 托盘 + 窗口
  02 Agent 聊天  → 聊天界面 + 流式输出 + 会话列表
  03 配置管理    → 配置表单 + Provider/API Key
  04 Agent 切换  → 下拉选择 Agent

P1（体验完善）:
  05 MCP 工具管理、消息操作、工具调用可视化、快捷键、主题、Agent 编辑

P2（高级功能）:
  06 记忆面板、07 Skill 管理、08 定时任务、自动更新、MCP 工具启停
```

---

## 3. 技术架构

### 3.1 整体架构

```
┌─────────────────────────────────────────────────┐
│                Electron Desktop                  │
│  ┌─────────────────────────────────────────────┐  │
│  │           Main Process (Node.js)             │  │
│  │  ┌───────────┐  ┌───────────┐  ┌──────────┐ │  │
│  │  │ Python 进程│  │  托盘管理  │  │ 自动更新  │ │  │
│  │  │ 生命周期   │  │  窗口管理  │  │ (electron │ │  │
│  │  │ (spawn)   │  │           │  │ -updater) │ │  │
│  │  └───────────┘  └───────────┘  └──────────┘ │  │
│  └─────────────────────────────────────────────┘  │
│                      │ IPC                        │
│  ┌──────────────────▼──────────────────────────┐  │
│  │         Renderer Process (前端 UI)           │  │
│  │  React 18 + TypeScript + Tailwind CSS        │  │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌───────────┐  │  │
│  │  │ 聊天  │ │ 会话  │ │ 配置  │ │ 记忆/技能  │  │  │
│  │  └──────┘ └──────┘ └──────┘ └───────────┘  │  │
│  └──────────────────┬──────────────────────────┘  │
│                     │ HTTP REST + WebSocket        │
│  ┌──────────────────▼──────────────────────────┐  │
│  │         SmallShrimp Server (已有)            │  │
│  │  FastAPI + EventBus + Worker + Agent         │  │
│  └─────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

### 3.2 技术选型

| 层面 | 方案 | 理由 |
|------|------|------|
| **桌面壳** | Electron 28+ | 生态丰富、Node.js 管理 Python 子进程、社区成熟 |
| **前端框架** | React 18 + TypeScript | 生态丰富、适合聊天类应用 |
| **样式** | Tailwind CSS + shadcn/ui | 开发快、组件美观 |
| **状态管理** | Zustand | 轻量、适合中小型应用 |
| **打包** | electron-builder → .exe(NSIS) / .dmg / .AppImage | 跨平台分发 |
| **进程管理** | Node.js `child_process.spawn` | 原生管理 Python 子进程 |

### 3.3 IPC 通信设计

```
Renderer (React)              Main Process (Node)          SmallShrimp (Python)
     │                               │                              │
     │── IPC: 'start-server' ───────▶│── child_process.spawn ──────▶│
     │                               │── health check (http) ──────▶│
     │                               │◀── server ready ────────────│
     │◀── IPC: 'server-status' ─────│                              │
     │                               │                              │
     │── HTTP/WS 直连 localhost ─────────────────────────────────▶│
     │  (数据通信不经过 Main Process)  │                              │
```

- **进程生命周期**：Main Process 通过 `child_process.spawn` 管理 Python 子进程
- **Main ↔ Renderer**：Electron IPC（`ipcMain` / `ipcRenderer`）
- **数据通信**：Renderer 通过 HTTP/WebSocket 直连 Server，零额外延迟

---

## 4. UI 设计总览

### 4.1 主布局

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
│  📦 Agent │  │  输入框                      📎  │  │
│  🧠 记忆  │  │  [Agent: pickle ▾]    [发送 ▶] │  │
│  📦 技能  │  └────────────────────────────────┘  │
│  ⏰ 定时  │                                      │
└──────────┴──────────────────────────────────────┘
```

### 4.2 设计原则

- **类聊天应用体验**：参考 ChatGPT / Claude Desktop 的交互模式
- **信息密度适中**：不过于稀疏也不拥挤
- **响应式**：窗口最小宽度 800px，支持拖拽调整侧边栏宽度
- **无障碍**：支持键盘导航，屏幕阅读器友好

---

## 5. API 设计（Server 端需新增）

| 端点 | 方法 | 用途 | 所属子需求 | 优先级 |
|------|------|------|-----------|--------|
| `/api/sessions` | GET | 会话列表 | F1 Agent 聊天 (02) | P0 |
| `/api/sessions/:id` | GET | 会话消息历史 | F1 Agent 聊天 (02) | P0 |
| `/api/sessions/:id` | DELETE | 删除会话 | F1 Agent 聊天 (02) | P0 |
| `/api/sessions/:id/rename` | PATCH | 重命名会话 | F1 Agent 聊天 (02) | P1 |
| `/api/config` | GET/PUT | 读写配置 | F3 配置管理 (03) | P0 |
| `/api/mcp/servers` | GET | MCP Server 列表 + 连接状态 | F8 MCP 工具管理 (05) | P1 |
| `/api/mcp/servers/:name/tools` | GET | Server 工具列表 | F8 MCP 工具管理 (05) | P1 |
| `/api/mcp/servers/:name/test` | POST | 连通性测试 | F8 MCP 工具管理 (05) | P1 |
| `/api/memories` | GET | 记忆列表/搜索 | F4 记忆系统 (06) | P2 |
| `/api/skills` | GET | Skill 列表 | F5 技能系统 (07) | P2 |
| `/api/crons` | GET | 定时任务列表 | F6 定时任务 (08) | P2 |

---

## 6. 里程碑

| 阶段 | 内容 | 涉及子需求 | 预估工期 |
|------|------|-----------|----------|
| **M0: 基础设施** | Electron 项目搭建 + React 框架 + 开发环境 | 01 桌面壳 | 2 天 |
| **M1: MVP 核心** | 进程管理 + 聊天 + 流式输出 + 会话列表 | 01 + 02 | 1 周 |
| **M2: MVP 配置** | 配置面板 + Agent 切换 | 03 + 04(P0) | 3 天 |
| **M3: MVP 收尾** | 托盘图标、打包脚本、基础测试 | 01 | 2 天 |
| **🎯 MVP 发布** | 可下载安装，基础聊天可用 | 01/02/03/04 | **~2 周** |
| **M4: V1 体验** | 工具调用可视化、快捷键、主题、消息操作、Agent 编辑、MCP 管理 | 02 + 04(P1) + 05 | 1 周 |
| **M5: V2 高级** | 记忆面板、Skill 管理、定时任务、自动更新、MCP 工具启停 | 06/07/08 + 01(P2) | 2 周 |

---

## 7. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Python 环境检测失败 | 无法启动 Server | 支持手动指定 Python 路径；内置诊断工具 |
| WebSocket 断连 | 消息丢失 | 自动重连 + 消息本地缓存 |
| 跨平台打包复杂 | 延迟发布 | 先聚焦 Windows，Mac/Linux 后续适配 |
| Server API 不满足前端需求 | 前端阻塞 | MVP 阶段通过直接读文件绕过部分 API |

---

## 8. 附录

### 8.1 参考产品

- **Claude Desktop**（Anthropic）：MCP 集成方式
- **ChatGPT Desktop**（OpenAI）：聊天体验
- **Open WebUI**：本地部署的 Web 聊天界面
- **Jan**：开源离线 AI 桌面应用

### 8.2 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始草案（旧 desktop/PRD.md） |
| 2026-06-25 | v0.2 | 技术选型从 Tauri 切换为 Electron |
| 2026-06-25 | v0.3 | V1 新增 Agent 管理模块 |
| 2026-06-25 | v0.4 | 重构为两级结构：总 PRD + features/ 子需求 |
| 2026-06-25 | v0.5 | 新增 F8 MCP 工具管理（P1） |
| 2026-06-25 | v0.6 | features 按迭代顺序重命名 01~08 |
