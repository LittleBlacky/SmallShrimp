# PRD 索引

> 最后更新：2026-06-25

---

## 总览

| 编号 | 需求 | PRD 路径 | 涉及层 | 状态 | 优先级 |
|------|------|----------|--------|------|--------|
| 01 | Agent 聊天 | [01-agent-chat/PRD.md](01-agent-chat/PRD.md) | Agent + API + UI | 草案 | P0 |
| 02 | Agent 管理 | [02-agent-management/PRD.md](02-agent-management/PRD.md) | Agent + UI | 草案 | P0/P1 |
| 03 | 配置管理 | [03-configuration/PRD.md](03-configuration/PRD.md) | Agent + API + UI | 草案 | P0 |
| 04 | 记忆系统 | [04-memory-system/PRD.md](04-memory-system/PRD.md) | Agent + API + UI | 草案 | P2 |
| 05 | 技能系统 | [05-skill-system/PRD.md](05-skill-system/PRD.md) | Agent + API + UI | 草案 | P2 |
| 06 | 定时任务 | [06-cron-tasks/PRD.md](06-cron-tasks/PRD.md) | Agent + API | 草案 | P2 |
| 07 | 桌面壳 | [07-desktop-shell/PRD.md](07-desktop-shell/PRD.md) | Electron | 草案 | P0 |

---

## 依赖关系

```
07-desktop-shell (Electron 运行时)
    ├── 01-agent-chat (核心聊天)
    ├── 02-agent-management (Agent CRUD)
    ├── 03-configuration (配置表单)
    ├── 04-memory-system (记忆面板, P2)
    ├── 05-skill-system (技能面板, P2)
    └── 06-cron-tasks (定时任务, P2)
                │
                └── SmallShrimp Server (已有)
```

所有 UI 层需求依赖 07-desktop-shell 提供 Electron 运行时。Agent/API 层需求依赖已有 SmallShrimp Server。

---

## 独立设计文档

| 文档 | 所属 PRD | 说明 |
|------|----------|------|
| (暂无) | - | - |

---

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-06-25 | 创建索引，登记桌面端 PRD |
| 2026-06-25 | 重构为按需求组织，拆分为 01~07 号 PRD |
