"""Reflection 引擎 — 从低级记忆归纳高级认知。

区别于 Summarization（压缩信息量），Reflection 做三件事：
1. 归纳：从多条记忆中提取共性
2. 抽象：从具体事件上升到模式识别
3. 策略推导：基于认知产出行动建议

参考 Stanford Generative Agents 的重要性累计阈值触发机制。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Reflection Prompt（供 LLM 调用） ─────────────

REFLECTION_PROMPT = """从以下多条记忆中提炼更高层次的认知。

原始记忆:
{records}

请输出以下 JSON 格式的反思结果:
{{
  "归纳": "从多条记忆中提取的共同模式或重复出现的主题",
  "抽象": "对用户行为/偏好/能力的更高层次推断",
  "策略建议": "基于上述认知的行动建议或交互策略调整",
  "confidence": 0.0-1.0
}}

注意：
- 归纳必须基于原始记忆中的信息，不要凭空臆测
- 抽象可以超出原始记忆（如"用户可能正在学习新技能"）
- 如果记忆不足 3 条，只做归纳不做抽象
- confidence 低于 0.5 的反思不持久化"""


@dataclass
class ReflectionResult:
    """一次 Reflection 的产出。"""
    summary: str = ""
    abstraction: str = ""
    strategy: str = ""
    confidence: float = 0.0
    source_records: list[str] = field(default_factory=list)
    created_at: str = ""


class ReflectionEngine:
    """4.1 Reflection 引擎。

    触发条件: 最近记忆的 importance 累计 > 阈值时触发。
    输出: 写入 insights 层（与 reflections 分离，inject="session"）。
    """

    IMPORTANCE_THRESHOLD = 15  # 累计 importance 阈值
    MIN_RECORDS = 3           # 最少需要几条记忆才触发

    def __init__(self, threshold: int = IMPORTANCE_THRESHOLD,
                 min_records: int = MIN_RECORDS):
        self.threshold = threshold
        self.min_records = min_records
        self.insights: list[ReflectionResult] = []

    # ── 重要性累计 ────────────────────────────────

    def should_reflect(self, records: list[dict]) -> bool:
        """判断是否触发 Reflection。"""
        if len(records) < self.min_records:
            return False
        total = sum(r.get("importance", 5) for r in records[-10:])
        return total >= self.threshold

    # ── Reflection 产出 ─────────────────────────────

    def build_reflect_prompt(self, records: list[dict]) -> str:
        """构造 Reflection prompt。"""
        lines = []
        for r in records[-self.min_records * 2:]:
            lines.append(f"- [{r.get('layer', '?')}] {r['content']}")
        return REFLECTION_PROMPT.format(records="\n".join(lines))

    def record_reflection(self, result: ReflectionResult) -> None:
        """记录一次 Reflection 结果。"""
        self.insights.append(result)

    # ── Prompt 注入 ───────────────────────────────

    def build_prompt_block(self) -> str:
        """生成注入 System Prompt 的 Insight 文本。"""
        if not self.insights:
            return ""
        recent = self.insights[-3:]
        lines = ["\n## 认知洞察 Insights\n"]
        for r in recent:
            if r.abstraction:
                lines.append(f"- {r.abstraction}")
            elif r.summary:
                lines.append(f"- {r.summary}")
            if r.strategy and r.confidence >= 0.6:
                lines.append(f"  ↳ {r.strategy}")
        return "\n".join(lines)

    # ── 序列化 ──────────────────────────────────

    def to_dict(self) -> list[dict]:
        return [{
            "summary": r.summary,
            "abstraction": r.abstraction,
            "strategy": r.strategy,
            "confidence": r.confidence,
            "created_at": r.created_at,
        } for r in self.insights]

    def from_dict(self, data: list[dict]) -> None:
        self.insights = [ReflectionResult(**d) for d in data]
