"""To-do List 锚点机制 — 多步任务的进度追踪。

每轮在 System Prompt 中注入结构化任务列表，让模型每一步都能看到
全局进度和当前任务。已完成的 item 折叠为结论，减少 token 占用。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass
class TaskItem:
    """一个待办任务。"""
    id: str
    title: str
    status: TaskStatus = TaskStatus.PENDING
    conclusion: str = ""          # 完成结论（折叠用）
    created_at: str = ""
    updated_at: str = ""


class TodoTracker:
    """3.1 To-do List 锚点。

    职责:
    - 管理多步任务的状态切换
    - 每轮生成注入 System Prompt 的任务进度文本
    - 已完成 item 折叠为一行结论，节省 token
    """

    def __init__(self):
        self.tasks: list[TaskItem] = []
        self._next_id: int = 0

    # ── 任务管理 ──────────────────────────────────

    def create_task(self, title: str) -> TaskItem:
        """创建一个新任务。"""
        now = datetime.now().isoformat()
        task = TaskItem(
            id=f"task_{self._next_id}",
            title=title,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        self._next_id += 1
        self.tasks.append(task)
        return task

    def update_status(self, task_id: str, status: TaskStatus,
                      conclusion: str = "") -> bool:
        """更新任务状态。"""
        for task in self.tasks:
            if task.id == task_id:
                task.status = status
                task.updated_at = datetime.now().isoformat()
                if conclusion:
                    task.conclusion = conclusion
                return True
        return False

    def remove(self, task_id: str) -> bool:
        """移除任务。"""
        for i, t in enumerate(self.tasks):
            if t.id == task_id:
                self.tasks.pop(i)
                return True
        return False

    def find(self, title_contains: str) -> list[TaskItem]:
        """按标题关键词搜索任务。"""
        q = title_contains.lower()
        return [t for t in self.tasks if q in t.title.lower()]

    # ── Prompt 注入 ───────────────────────────────

    STATUS_ICONS = {
        TaskStatus.PENDING: "⏳",
        TaskStatus.IN_PROGRESS: "🔄",
        TaskStatus.COMPLETED: "✅",
        TaskStatus.BLOCKED: "🚫",
        TaskStatus.CANCELLED: "❌",
    }

    def build_prompt_block(self) -> str:
        """生成注入 System Prompt 的任务进度文本。

        已完成的任务折叠为一行结论。
        进行中的任务保留完整上下文。
        待处理的任务只保留简要描述。
        """
        if not self.tasks:
            return ""

        lines = ["\n## 任务进度 Task Progress\n"]
        for task in self.tasks:
            icon = self.STATUS_ICONS.get(task.status, "⏳")
            if task.status == TaskStatus.COMPLETED and task.conclusion:
                # 已完成 → 折叠为一行
                lines.append(f"{icon} {task.title} → {task.conclusion}")
            elif task.status == TaskStatus.COMPLETED:
                lines.append(f"{icon} {task.title}")
            elif task.status == TaskStatus.IN_PROGRESS:
                lines.append(f"{icon} {task.title} (进行中)")
            else:
                # pending / blocked / cancelled
                extra = f" — {task.conclusion}" if task.conclusion else ""
                lines.append(f"{icon} {task.title}{extra}")
        return "\n".join(lines)

    # ── 序列化 ──────────────────────────────────

    def to_dict(self) -> list[dict]:
        return [{
            "id": t.id, "title": t.title,
            "status": t.status.value,
            "conclusion": t.conclusion,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
        } for t in self.tasks]

    def from_dict(self, data: list[dict]) -> None:
        self.tasks = [TaskItem(
            id=d["id"], title=d["title"],
            status=TaskStatus(d.get("status", "pending")),
            conclusion=d.get("conclusion", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        ) for d in data]
        self._next_id = max(
            (int(t.id.split("_")[-1]) for t in self.tasks if "_" in t.id),
            default=0
        ) + 1
