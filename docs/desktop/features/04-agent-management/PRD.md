# Agent 管理 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案

---

## 1. 产品概述

### 1.1 产品定位

Agent 管理模块让用户通过图形界面创建、编辑、删除 AI Agent，无需手动编辑 AGENT.md 文件。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| 创建 Agent 靠手写 YAML | 可视化表单，下拉选择 Provider/Model/Tools |
| 修改提示词需要编辑文件 | Markdown 编辑器，实时预览 |

### 1.3 目标用户

- **所有用户**：都需要创建和管理自己的 Agent

---

## 2. 功能范围

### 2.1 MVP（P0）

| 模块 | 功能 | 说明 |
|------|------|------|
| **Agent 切换** | 下拉选择当前 Agent | 读取 workspace 中的 Agent 列表 |

### 2.2 V1（P1）

| 模块 | 功能 |
|------|------|
| **Agent 管理** | 新建/编辑/删除 Agent，表单编辑 AGENT.md |
| **Agent 查看** | 只读预览 Agent 详情（模型、工具、提示词） |

---

## 3. 技术架构总览

```
┌─────────────────────────────────────────────────┐
│         Renderer (React - Agent 管理面板)         │
│  Agent 列表 → 新建表单 → YAML 生成 → 文件写入     │
│                      │                          │
│          Main Process (IPC: 文件读写)            │
│                      │                          │
│              workspace/agents/<name>/AGENT.md     │
└─────────────────────────────────────────────────┘
```

---

## 4. 模块详细设计

### 4.1 Agent 核心层

AGENT.md 结构：

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
# 系统提示词（Markdown）
```

### 4.2 后端 API 层

| 端点 | 方法 | 用途 | 优先级 |
|------|------|------|--------|
| `/api/agents` | GET | Agent 列表（已有） | P0 |

Agent 管理（V1）通过 Main Process 直接读写 `workspace/agents/` 目录下的 AGENT.md 文件，无需额外 API。

### 4.3 桌面端 UI 层

**表单映射：**

```yaml
# AGENT.md 字段 → 表单控件
name              → 文本输入
description       → 文本输入
llm.provider      → 下拉选择（从配置中读取 providers）
llm.model         → 文本输入（含常用模型快捷选项）
llm.temperature   → 滑块 (0~2, 步长 0.1)
llm.context_window→ 数字输入
tools             → 多选复选框（read/write/shell/websearch/subagent...）
正文              → Markdown 编辑器（带预览）
```

**操作流程：**

| 操作 | 行为 |
|------|------|
| 新建 | 填写表单 → 生成 `workspace/agents/<name>/AGENT.md`，自动创建目录 |
| 编辑 | 解析已有 AGENT.md → 回填表单 → 修改后写回 |
| 删除 | 确认对话框 → 删除 `agents/<name>/` 整个目录 |
| 查看 | 只读预览模式，展示元数据 + 渲染后的提示词 |

**入口：** 侧边栏「📦 Agent」→ 列表页（含搜索）→ 点击进入详情/编辑

---

## 5. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | Agent 下拉切换 | 0.5 天 |
| P1 | Agent 新建/编辑/删除面板 | 2 天 |

---

## 6. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 从桌面端 PRD 拆分，初始版本 |
