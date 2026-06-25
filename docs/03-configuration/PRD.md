# 配置管理 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案

---

## 1. 产品概述

### 1.1 产品定位

配置管理模块将 `config.user.yaml` 映射为图形化表单，用户无需手写 YAML 即可配置 LLM Provider、API Key、MCP Server 等。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| 配置靠手写 YAML，容易格式错误 | 可视化表单，下拉选择 + 密码输入框 |
| API Key 明文存储不安全 | 密码输入框 + 本地加密存储 |
| 修改配置需重启 | 写回 config.user.yaml，Server 热重载 |

---

## 2. 功能范围

### 2.1 MVP（P0）

| 模块 | 功能 | 说明 |
|------|------|------|
| **配置面板** | 图形化编辑 Provider / API Key / 默认 Agent | 写回 config.user.yaml，热重载 |

---

## 3. 技术架构

```
┌─────────────────────────────────────────────────┐
│         Renderer (React - 配置表单)               │
│  Provider 列表 → API Key 输入 → MCP 管理         │
│                      │                          │
│          Main Process (IPC: 文件读写)            │
│                      │                          │
│           workspace/config.user.yaml              │
└─────────────────────────────────────────────────┘
```

---

## 4. 模块详细设计

### 4.1 Agent 核心层

配置文件结构（`config.user.yaml`）：

```yaml
default_provider: deepseek
default_agent: pickle
providers:
  deepseek:
    api_key: sk-xxx
    api_base: https://api.deepseek.com
mcp_servers:
  filesystem:
    command: npx
    args: [-y, @modelcontextprotocol/server-filesystem, /path]
```

### 4.2 后端 API 层

| 端点 | 方法 | 用途 | 优先级 |
|------|------|------|--------|
| `/api/config` | GET/PUT | 读写配置 | P0 |

### 4.3 桌面端 UI 层

**表单映射：**

```yaml
# 配置字段 → 表单控件
default_provider    → 下拉选择（动态读取 providers 键名）
default_agent       → 下拉选择（读取 agents 目录）
providers.*.api_key → 密码输入框
providers.*.api_base→ 文本输入框
mcp_servers         → 动态列表（添加/删除/编辑每条）
```

**交互：**
- 修改后自动保存（debounce 1s）或手动「保存」按钮
- 保存后通过 `/api/config` PUT 写回，Server 热重载
- API Key 字段默认隐藏，点击眼睛图标显示

---

## 5. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | 配置表单 + 读写 config.user.yaml | 2 天 |

---

## 6. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 从桌面端 PRD 拆分，初始版本 |
