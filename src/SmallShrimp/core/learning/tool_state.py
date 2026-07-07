"""工具态记忆 — 避免重复调用工具 + 从失败中学习。

四类工具态记忆:
1. 调用历史: (tool_name, params_hash, result_summary, timestamp)
2. 执行状态: 生命周期追踪
3. 能力记忆: 工具在特定条件下的成功率
4. 失败记忆: 哪些参数组合导致过失败
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ToolCallRecord:
    """一次工具调用的完整记录。"""
    tool_name: str
    params_hash: str
    params_snapshot: dict = field(default_factory=dict)
    result_summary: str = ""
    success: bool = True
    error_message: str = ""
    duration_ms: int = 0
    timestamp: str = ""


class ToolStateMemory:
    """3.2 工具态记忆管理器。

    避免重复调用:
    - Agent 调工具前，Runtime 检查 (tool_name, params_hash) 是否已执行
    - 已执行且成功 → 返回缓存结果摘要，不发实际调用
    - 已执行但失败 → 提示 Agent 避免重复同样的失败

    从失败中学习:
    - 跟踪失败模式和错误参数组合
    - 积累能力统计数据
    """

    def __init__(self, dedup_cache_ttl_seconds: int = 300):
        self.records: list[ToolCallRecord] = []
        self._dedup_cache_ttl = dedup_cache_ttl_seconds

    @staticmethod
    def _hash_params(params: dict) -> str:
        """生成参数指纹。"""
        raw = json.dumps(params, sort_keys=True, default=str)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    # ── 记录 ──────────────────────────────────────

    def record_call(self, tool_name: str, params: dict,
                    result_summary: str, success: bool = True,
                    error_message: str = "", duration_ms: int = 0) -> ToolCallRecord:
        """记录一次工具调用。"""
        record = ToolCallRecord(
            tool_name=tool_name,
            params_hash=self._hash_params(params),
            params_snapshot=dict(params),
            result_summary=result_summary,
            success=success,
            error_message=error_message,
            duration_ms=duration_ms,
            timestamp=datetime.now().isoformat(),
        )
        self.records.append(record)
        return record

    # ── 去重检查 ──────────────────────────────────

    def find_recent(self, tool_name: str, params: dict,
                    max_age_seconds: int = 300) -> ToolCallRecord | None:
        """查找最近对相同参数的调用（避免重复）。"""
        params_h = self._hash_params(params)
        now = datetime.now()

        for r in reversed(self.records):
            if r.tool_name == tool_name and r.params_hash == params_h:
                age = (now - datetime.fromisoformat(r.timestamp)).total_seconds()
                if age <= max_age_seconds:
                    return r
                return None  # 找到但已过期
        return None

    def should_skip(self, tool_name: str, params: dict) -> tuple[bool, str]:
        """判断是否应跳过此调用。

        Returns:
            (should_skip, reason_or_summary)
        """
        recent = self.find_recent(tool_name, params)
        if recent is None:
            return False, ""

        if recent.success:
            return True, f"最近已调用{tool_name}并成功: {recent.result_summary[:100]}"

        return True, f"最近已调用{tool_name}但失败({recent.error_message[:50]}), 请检查参数后重试"

    # ── 统计数据 ──────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """工具能力统计。"""
        by_tool: dict[str, dict] = {}
        for r in self.records:
            entry = by_tool.setdefault(r.tool_name, {"calls": 0, "success": 0, "failures": 0, "total_ms": 0})
            entry["calls"] += 1
            entry["total_ms"] += r.duration_ms
            if r.success:
                entry["success"] += 1
            else:
                entry["failures"] += 1
        return {
            tool: {**v, "success_rate": round(v["success"] / max(v["calls"], 1), 3)}
            for tool, v in by_tool.items()
        }

    def recent_failures(self, n: int = 5) -> list[ToolCallRecord]:
        """最近 N 次失败记录。"""
        return [r for r in self.records if not r.success][-n:]

    def build_context_block(self) -> str:
        """生成注入上下文的工具状态摘要。"""
        if not self.records:
            return ""

        lines = ["\n## 已执行操作\n"]
        # 只显示最近 5 条
        for r in self.records[-5:]:
            icon = "✅" if r.success else "❌"
            params_preview = json.dumps(r.params_snapshot, default=str)[:60]
            lines.append(f"{icon} {r.tool_name}({params_preview}) → {r.result_summary[:50]}")
        return "\n".join(lines)

    # ── 序列化 ──────────────────────────────────

    def to_dict(self) -> list[dict]:
        return [{
            "tool_name": r.tool_name,
            "params_hash": r.params_hash,
            "result_summary": r.result_summary,
            "success": r.success,
            "error_message": r.error_message,
            "duration_ms": r.duration_ms,
            "timestamp": r.timestamp,
        } for r in self.records]

    def from_dict(self, data: list[dict]) -> None:
        self.records = [ToolCallRecord(**d) for d in data]
