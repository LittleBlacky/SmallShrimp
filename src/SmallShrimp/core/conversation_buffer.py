"""滑动窗口 Buffer — 对话轮次追踪与摘要触发。

两层架构（与 ContextGuard 互补）:
- Buffer 层: 保留最近 N 轮完整对话（工作记忆）
- Summary 层: Buffer 溢出时，旧轮次压缩为结构化摘要

ContextGuard 是全局上下文窗口的兜底压缩，
ConversationBuffer 是对话历史的精细化管理。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..message import Message

logger = logging.getLogger(__name__)

# ── 默认配置 ──────────────────────────────────────

_DEFAULT_MAX_BUFFER_TURNS = 8      # Buffer 保留最近 N 轮
_DEFAULT_TOKEN_WARNING_RATIO = 0.7  # 达窗口 70% 触发压缩
_DEFAULT_SUMMARY_TRIGGER_TURNS = 12 # 轮次超限触发摘要


@dataclass
class TurnRecord:
    """一轮完整对话。"""
    user_message: str = ""
    assistant_message: str = ""
    tool_messages: list[str] = field(default_factory=list)
    timestamp: str = ""
    token_estimate: int = 0
    compressed_summary: str = ""


class ConversationBuffer:
    """2.2 对话轮次 Buffer。

    职责:
    - 按轮次组织对话（而非按 message 线性排列）
    - Buffer 满时触发摘要压缩
    - 提供结构化上下文给 ContextGuard 的 Autocompact
    """

    def __init__(self, max_turns: int = _DEFAULT_MAX_BUFFER_TURNS,
                 summary_trigger: int = _DEFAULT_SUMMARY_TRIGGER_TURNS,
                 token_warning_ratio: float = _DEFAULT_TOKEN_WARNING_RATIO):
        self.max_turns = max_turns
        self.summary_trigger = summary_trigger
        self.token_warning_ratio = token_warning_ratio
        self.turns: list[TurnRecord] = []
        self._current_turn: TurnRecord | None = None

    # ── 轮次管理 ──────────────────────────────────

    def start_turn(self, user_content: str, now: str | None = None) -> None:
        """开始新的一轮。"""
        self._current_turn = TurnRecord(
            user_message=user_content,
            timestamp=now or datetime.now().isoformat(),
        )

    def add_tool_result(self, content: str) -> None:
        """添加工具调用结果到当前轮次。"""
        if self._current_turn is not None:
            self._current_turn.tool_messages.append(content)

    def end_turn(self, assistant_content: str, token_count: int = 0) -> dict[str, Any]:
        """结束当前轮次，加入 Buffer。"""
        if self._current_turn is None:
            return {"compressed": False, "trigger": None}

        self._current_turn.assistant_message = assistant_content
        self._current_turn.token_estimate = token_count
        self.turns.append(self._current_turn)
        finalized = self._current_turn
        self._current_turn = None

        # 检查是否触发压缩
        result = self._check_triggers()
        return {
            "compressed": result["compressed"],
            "trigger": result["trigger"],
            "turn_count": len(self.turns),
            "overflow": result["overflow"],
        }

    # ── 压缩触发 ──────────────────────────────────

    def _check_triggers(self) -> dict[str, Any]:
        """检查压缩触发条件。"""
        total_turns = len(self.turns)
        overflow = max(0, total_turns - self.max_turns)
        triggers = []

        if total_turns >= self.summary_trigger:
            triggers.append("turn_limit")
        if overflow > 0:
            triggers.append("overflow")

        return {
            "compressed": len(triggers) > 0,
            "trigger": triggers[0] if triggers else None,
            "overflow": overflow,
        }

    def get_turns_for_summary(self, n: int = 3) -> list[TurnRecord]:
        """获取最旧的要进行摘要的 N 轮。"""
        if len(self.turns) <= self.max_turns:
            return []
        overflow = len(self.turns) - self.max_turns
        return self.turns[:min(overflow + n, len(self.turns) - 1)]

    def replace_with_summary(self, old_turns: list[TurnRecord],
                              summary: str) -> None:
        """将摘要替换掉旧轮次。"""
        turn_ids = {id(t) for t in old_turns}
        self.turns = [t for t in self.turns if id(t) not in turn_ids]
        # 插入摘要轮次
        summary_turn = TurnRecord(
            user_message="[会话摘要]",
            assistant_message=summary,
            timestamp=old_turns[0].timestamp if old_turns else "",
            compressed_summary=summary,
        )
        self.turns.insert(0, summary_turn)

    # ── 查询 ──────────────────────────────────────

    def recent_turns(self, n: int = 5) -> list[TurnRecord]:
        """最近 N 轮完整对话。"""
        return self.turns[-n:]

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def raw_message_count(self) -> int:
        """Buffer 中轮次对应的原始消息数。"""
        return sum(
            1 + bool(t.assistant_message) + len(t.tool_messages)
            for t in self.turns
        )

    # ── 序列化 ──────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "max_turns": self.max_turns,
            "turns": [{
                "user": t.user_message[:100],
                "assistant": t.assistant_message[:100],
                "tool_count": len(t.tool_messages),
                "timestamp": t.timestamp,
                "has_summary": bool(t.compressed_summary),
            } for t in self.turns],
        }
