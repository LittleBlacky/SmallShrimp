"""信息源冲突优先级引擎 — 多源信息矛盾时的决策逻辑。

优先级链（高→低）:
1. 系统安全/合规约束（不可违反）
2. 系统实时状态（当前事实）
3. 当前轮用户显式声明（当前意愿）
4. 历史记忆/行为模式（参考但可被覆盖）

Prompt 组装时按槽位分离，让模型清楚看到每段信息的角色和权重。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class SourcePriority:
    """信息源优先级常量。"""
    SYSTEM_SAFETY = 100   # 安全/合规（最高）
    SYSTEM_STATE = 80     # 系统实时状态
    USER_CURRENT = 60     # 当前用户声明
    HISTORY = 40          # 历史记忆/行为模式
    INFERENCE = 20        # 模型推断


@dataclass
class InfoSlot:
    """一个信息槽位。"""
    content: str
    source_type: str
    priority: int = SourcePriority.HISTORY
    label: str = ""


class PriorityResolver:
    """5.1 信息源冲突优先级引擎。

    职责:
    - 按优先级排序多个信息源
    - 检测与高优先级信息冲突的低优先级信息
    - 生成槽位分离的 Prompt 文本
    """

    def __init__(self):
        self.slots: list[InfoSlot] = []

    # ── 信息注册 ──────────────────────────────────

    def add_system_rule(self, content: str) -> None:
        """添加系统规则（最高优先级）。"""
        self.slots.append(InfoSlot(
            content=content,
            source_type="system_rule",
            priority=SourcePriority.SYSTEM_SAFETY,
            label="系统规则",
        ))

    def add_system_state(self, content: str) -> None:
        """添加系统实时状态。"""
        self.slots.append(InfoSlot(
            content=content,
            source_type="system_state",
            priority=SourcePriority.SYSTEM_STATE,
            label="实时状态",
        ))

    def add_user_input(self, content: str) -> None:
        """添加当前用户输入。"""
        self.slots.append(InfoSlot(
            content=content,
            source_type="user_input",
            priority=SourcePriority.USER_CURRENT,
            label="当前需求",
        ))

    def add_history(self, content: str, label: str = "历史画像") -> None:
        """添加历史记忆/行为模式。"""
        self.slots.append(InfoSlot(
            content=content,
            source_type="history",
            priority=SourcePriority.HISTORY,
            label=label,
        ))

    def add_knowledge(self, content: str, label: str = "检索结果") -> None:
        """添加知识库/检索结果。"""
        self.slots.append(InfoSlot(
            content=content,
            source_type="knowledge",
            priority=SourcePriority.HISTORY,
            label=label,
        ))

    # ── 冲突检测 ──────────────────────────────────

    def detect_conflicts(self) -> list[str]:
        """检测高优先级和低优先级信息之间的冲突。

        简化规则: 如果安全规则和用户输入都包含同一个关键词但语义相反。
        """
        conflicts: list[str] = []
        # 简单冲突检测：安全规则 vs 用户输入
        for slot_a in self.slots:
            for slot_b in self.slots:
                if slot_a.priority < slot_b.priority:
                    a, b = slot_a, slot_b
                else:
                    continue
                # 如果优先级高的信息与低的有矛盾关键词
                ca = (a.content or "").lower()
                cb = (b.content or "").lower()
                negation_triggers = ["不要", "禁止", "不能", "不可以", "不允许"]
                for neg in negation_triggers:
                    if neg in ca and any(t in cb for t in ["要", "能", "可以", "允许"]):
                        conflicts.append(f"{a.label}({a.content}) 与 {b.label}({b.content}) 可能存在矛盾")
        return conflicts

    # ── Prompt 组装 ───────────────────────────────

    def build_prompt(self) -> str:
        """按优先级排序并生成槽位分离的 Prompt 文本。"""
        sorted_slots = sorted(self.slots, key=lambda s: s.priority, reverse=True)

        lines = []
        for slot in sorted_slots:
            header = f"【{slot.label}】"
            lines.append(f"{header}\n{slot.content}\n")

        return "\n".join(lines)

    # ── 序列化 ──────────────────────────────────

    def to_dict(self) -> list[dict]:
        return [{
            "content": s.content,
            "source_type": s.source_type,
            "priority": s.priority,
            "label": s.label,
        } for s in self.slots]

    def from_dict(self, data: list[dict]) -> None:
        self.slots = [InfoSlot(**d) for d in data]
