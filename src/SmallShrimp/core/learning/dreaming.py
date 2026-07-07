"""Dreaming 离线记忆整合 — Agent 空闲时主动整理记忆。

四项核心工作（类比人类睡眠时的记忆巩固）:
1. 记忆重放与巩固: 高频访问→标记长期保存，低频→衰减
2. 冲突检测与消解: 扫描记忆库，发现矛盾条目
3. 跨会话关联发现: 不同会话中看似无关的记忆通过推理发现关联
4. 记忆压缩与抽象层级提升: 多条具体记忆合并为更抽象的条目

触发方式: CronJob 或会话间隙调用。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ConflictPair:
    """一对冲突的记忆。"""
    record_a: dict
    record_b: dict
    reason: str = ""
    resolved: bool = False


@dataclass
class DreamResult:
    """一次 Dreaming 运行的产出。"""
    conflicts_found: int = 0
    conflicts_resolved: int = 0
    memories_consolidated: int = 0
    memories_decayed: int = 0
    associations_found: int = 0
    details: list[str] = field(default_factory=list)


class DreamingEngine:
    """4.2 Dreaming 离线记忆整合。

    使用方式: 注册为 CronJob，每小时或每次会话结束后运行。

    简易实现（不依赖 LLM）:
    - 冲突检测: 同 layer 内语义相似的记忆但内容矛盾
    - 衰减: 低 importance + 长时间未 recall 的记忆降权
    - 关联: 跨层关键词重叠检测
    """

    # ── 衰减参数 ──────────────────────────────────

    DECAY_DAYS = 30            # 多少天未访问开始衰减
    DECAY_IMPORTANCE_MAX = 5   # importance <= 此值可衰减
    DECAY_CONFIDENCE_REDUCTION = 0.2
    ARCHIVE_AFTER_DECAYS = 3   # 衰减 3 次后归档

    def __init__(self):
        self.last_run: str = ""

    # ── 冲突检测（简易版：关键词+意图矛盾） ───────────

    def detect_conflicts(self, records: list[dict]) -> list[ConflictPair]:
        """检测同 layer 内的矛盾记忆。

        检测规则:
        - 同 layer
        - 包含对立词: "喜欢" vs "讨厌", "会" vs "不会" 等
        - 同一实体的值不同
        """
        conflicts: list[ConflictPair] = []
        by_layer: dict[str, list[dict]] = {}
        for r in records:
            by_layer.setdefault(r.get("layer", ""), []).append(r)

        # 对立词对
        antonym_pairs = [
            ("喜欢", "讨厌"), ("爱", "恨"), ("要", "不要"),
            ("会", "不会"), ("能", "不能"), ("可以", "不可以"),
            ("必须", "不必"), ("包括", "不包括"), ("含", "不含"),
            ("是", "不是"), ("有", "没有"),
        ]

        for layer, recs in by_layer.items():
            for i in range(len(recs)):
                for j in range(i + 1, len(recs)):
                    a, b = recs[i], recs[j]
                    ca = (a.get("content") or "").lower()
                    cb = (b.get("content") or "").lower()
                    for a1, a2 in antonym_pairs:
                        if a1 in ca and a2 in cb:
                            conflicts.append(ConflictPair(
                                record_a=a, record_b=b,
                                reason=f"矛盾: '{a1}' vs '{a2}'",
                            ))
                            break
        return conflicts

    # ── 衰减 ──────────────────────────────────────

    def compute_decay(self, record: dict, now: datetime) -> tuple[bool, float]:
        """判断记忆是否应衰减。

        Returns:
            (should_decay, decayed_confidence)
        """
        importance = record.get("importance", 5)
        if importance > self.DECAY_IMPORTANCE_MAX:
            return False, record.get("confidence", 1.0)

        updated = record.get("updated_at", "")
        if not updated:
            return False, record.get("confidence", 1.0)

        try:
            age = (now - datetime.fromisoformat(updated)).days
        except (ValueError, TypeError):
            return False, record.get("confidence", 1.0)

        if age < self.DECAY_DAYS:
            return False, record.get("confidence", 1.0)

        decayed = max(0.0, record.get("confidence", 1.0) - self.DECAY_CONFIDENCE_REDUCTION * (age // self.DECAY_DAYS))
        return decayed < record.get("confidence", 1.0), decayed

    # ── 跨会话关联 ────────────────────────────────

    def find_associations(self, records: list[dict]) -> list[tuple[dict, dict, str]]:
        """发现不同会话中的隐含关联。

        规则: 跨 layer 或跨 session 的关键词重叠。
        """
        associations: list[tuple[dict, dict, str]] = []
        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                a, b = records[i], records[j]
                a_layer = a.get("layer", "")
                b_layer = b.get("layer", "")
                if a_layer == b_layer:
                    continue  # 只跨层
                ca = (a.get("content") or "").lower()
                cb = (b.get("content") or "").lower()
                # 找共同的多字词
                shared = set()
                for word_a in ca.split():
                    for word_b in cb.split():
                        if len(word_a) >= 2 and len(word_b) >= 2 and word_a == word_b:
                            shared.add(word_a)
                if len(shared) >= 2:
                    associations.append((a, b, f"共享关键词: {', '.join(list(shared)[:3])}"))
        return associations

    # ── 运行 ──────────────────────────────────────

    def run(self, records: list[dict],
            conflict_resolver: Callable | None = None,
            decay_applier: Callable | None = None) -> DreamResult:
        """执行一轮 Dreaming。"""
        now = datetime.now()
        result = DreamResult()

        # 1. 冲突检测
        conflicts = self.detect_conflicts(records)
        result.conflicts_found = len(conflicts)
        if conflict_resolver:
            for c in conflicts:
                resolved = conflict_resolver(c.record_a, c.record_b)
                c.resolved = resolved
                if resolved:
                    result.conflicts_resolved += 1
                    result.details.append(f"解决冲突: {c.reason}")

        # 2. 衰减
        for r in records:
            should, new_conf = self.compute_decay(r, now)
            if should and decay_applier:
                decay_applier(r, new_conf)
                result.memories_decayed += 1

        # 3. 关联发现
        associations = self.find_associations(records)
        result.associations_found = len(associations)
        for a, b, reason in associations[:5]:
            result.details.append(f"发现关联: {reason}")

        self.last_run = now.isoformat()
        return result
