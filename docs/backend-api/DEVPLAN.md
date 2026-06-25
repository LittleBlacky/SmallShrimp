# 后端 API 开发计划

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案

---

## 1. 概述

SmallShrimp Desktop 需要 Server 侧提供一组 REST API。本文档是后端实现的技术执行计划，偏代码细节，不重复 PRD 中的产品描述。

关联 PRD：`@ref: desktop/PRD.md`

---

## 2. API 总览

| 端点 | 方法 | 用途 | 来源 | 优先级 |
|------|------|------|------|--------|
| `/api/sessions` | GET | 会话列表 | F1 Agent 聊天 | P0 |
| `/api/sessions` | POST | 新建会话 | F1 Agent 聊天 | P0 |
| `/api/sessions/:id` | GET | 会话消息历史（分页） | F1 Agent 聊天 | P0 |
| `/api/sessions/:id` | DELETE | 删除会话 | F1 Agent 聊天 | P0 |
| `/api/sessions/:id/rename` | PATCH | 重命名会话 | F1 Agent 聊天 | P1 |
| `/api/config` | GET | 读取用户配置 | F3 配置管理 | P0 |
| `/api/config` | PUT | 写入用户配置 | F3 配置管理 | P0 |
| `/api/mcp/servers` | GET | MCP Server 列表 + 连接状态 | F8 MCP 管理 | P1 |
| `/api/mcp/servers/:name/tools` | GET | 获取 Server 工具列表 | F8 MCP 管理 | P1 |
| `/api/mcp/servers/:name/test` | POST | 连通性测试 | F8 MCP 管理 | P1 |
| `/api/memories` | GET | 记忆列表/搜索 | F4 记忆系统 | P2 |
| `/api/memories/:id` | PUT | 编辑记忆 | F4 记忆系统 | P2 |
| `/api/memories/:id` | DELETE | 删除记忆 | F4 记忆系统 | P2 |
| `/api/skills` | GET | Skill 列表 | F5 技能系统 | P2 |
| `/api/crons` | GET | 定时任务列表 | F6 定时任务 | P2 |

---

## 3. 存储设计

### 3.1 会话存储（P0）

**目录：** `workspace/sessions/`

```
workspace/sessions/
├── .meta.json              # 会话元数据索引
├── <session_id>.jsonl      # 每条消息一行 JSON
```

**`.meta.json` 结构：**

```json
[
  {
    "id": "abc123",
    "title": "帮我读 README",
    "agent": "pickle",
    "created_at": "2026-06-25T10:00:00Z",
    "last_active_at": "2026-06-25T10:05:00Z"
  }
]
```

**`<id>.jsonl` 每条消息：**

```json
{"role": "user", "content": "你好", "timestamp": "2026-06-25T10:00:00Z"}
{"role": "assistant", "content": "你好！...", "timestamp": "..."}
```

**读写策略：**
- `.meta.json`：启动加载到内存，写操作先落盘再更新内存
- `.jsonl`：追加写（O(1)），读取时按 `?offset=N&limit=M` 分页从文件尾倒序读
- 并发安全：单进程 Server，无需锁

### 3.2 配置存储（P0）

**文件：** `workspace/config.user.yaml`（已有）

**实现：** 复用现有 `utils/config.py` 的 YAML 读写能力，新增 `write_config()` 方法，写入后触发热重载（已有 `config_reloader.py`）。

### 3.3 其他存储（P1/P2）

- MCP：复用现有 `core/mcp.py`，新增状态查询方法
- 记忆：复用现有 `core/memory/memory_manager.py`
- Skill：读取 `workspace/skills/` 目录
- Cron：读取 `workspace/crons/` 目录

---

## 4. 路由注册方案

**文件：** `src/SmallShrimp/server/app.py`

当前 `app.py` 使用 FastAPI。新增 API 路由有两种方式：

| 方案 | 做法 | 推荐 |
|------|------|------|
| A | 直接在 `app.py` 中添加路由 | ❌ 文件会膨胀 |
| B | 新建 `server/api/` 模块，按功能拆文件 | ✅ 清晰 |

**推荐方案 B 的结构：**

```
src/SmallShrimp/server/
├── app.py                    # FastAPI app 创建 + include_router
├── api/                      # 新增
│   ├── __init__.py
│   ├── sessions.py           # /api/sessions/*
│   ├── config.py             # /api/config
│   ├── mcp.py               # /api/mcp/*        (P1)
│   └── memories.py          # /api/memories/*    (P2)
├── agent_worker.py
├── channel_worker.py
├── cron_worker.py
├── delivery_worker.py
├── websocket_worker.py
├── worker.py
├── server.py
└── context.py
```

**`app.py` 新增路由注册：**

```python
from .api import sessions, config

app.include_router(sessions.router, prefix="/api")
app.include_router(config.router, prefix="/api")
```

---

## 5. P0 实现步骤

### Step 1: `server/api/sessions.py`（~2h）

```python
# GET    /api/sessions         → 读取 .meta.json，返回列表
# POST   /api/sessions         → 生成 UUID → 写入 .meta.json → 创建空 .jsonl
# GET    /api/sessions/:id     → 读取 .jsonl，分页返回 (?offset=0&limit=50)
# DELETE /api/sessions/:id     → 删除 .meta.json 条目 + 删除 .jsonl 文件
# PATCH  /api/sessions/:id/rename → 更新 .meta.json 中 title
```

### Step 2: `server/api/config.py`（~1h）

```python
# GET  /api/config  → 读取 config.user.yaml，返回 JSON（过滤 api_key 为 ****）
# PUT  /api/config  → 合并写入 config.user.yaml，触发 config_reloader
```

### Step 3: 注册路由到 `app.py`（~15min）

---

## 6. 需要修改的现有文件

| 文件 | 改动 |
|------|------|
| `server/app.py` | 新增 `include_router`（+2 行） |
| `utils/config.py` | 新增 `write_config()` 方法（约 20 行） |
| `utils/config.py` | `get_config()` 的 `api_key` 字段脱敏（可选） |

**新建文件：**

| 文件 | 说明 |
|------|------|
| `server/api/__init__.py` | 空文件 |
| `server/api/sessions.py` | 会话 CRUD（约 80 行） |
| `server/api/config.py` | 配置读写（约 40 行） |

---

## 7. 测试策略

| 测试 | 内容 |
|------|------|
| 单元测试 | `tests/test_api_sessions.py`：CRUD 逻辑 + 分页 + 错误码 |
| 单元测试 | `tests/test_api_config.py`：读写 + 热重载 |
| 集成测试 | 启动 Server → curl 验证各端点 → 检查文件落盘 |

---

## 8. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始版本 |
