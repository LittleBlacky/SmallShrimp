"""置信度管线 — 写入把关。

在 MemoryManager.store() 前拦截所有写入请求，
用信号强度决定该不该写、写到哪一层。

组件:
    SignalDetector  — 从输入上下文提取多个独立置信度信号
    ConfidenceGate  — 综合信号做裁决（write / stage / discard）
    StagingArea     — 暂存低置信度记录，证据累积后提升到正式层
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


# ── 常量 ──────────────────────────────────────────────────────

THRESHOLD_DIRECT = 0.7    # 直接写入正式层
THRESHOLD_STAGING = 0.4   # 暂存待强化
THRESHOLD_DISCARD = 0.0   # 丢弃

PROMOTION_COUNT = 2        # staging 中同内容出现几次后提升

# 关键词触发信号
SIGNAL_KEYWORDS = {
    "我是", "我叫", "我的名字", "记住", "请记住",
    "我在", "我住在", "我来自",
    "不要", "千万别", "禁止",
    "我喜欢", "我不喜欢", "我偏爱",
    "我习惯", "我经常", "我从不",
}

# 用户纠正信号
CORRECTION_KEYWORDS = {
    "不对", "不是", "错了", "应该说", "更正",
    "纠正", "你错了", "不对的", "不是这样",
    "我说的不是这个", "你理解错了",
}

# 重复/强化信号 — 用户再次提到同一信息的关键词
REPETITION_KEYWORDS = {
    "还是", "再说一次", "重复", "强调",
    "我之前说过", "跟上次一样",
}

_STAGING_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_staging (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash    TEXT NOT NULL,
    content         TEXT NOT NULL,
    layer           TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 0.5,
    count           INTEGER NOT NULL DEFAULT 1,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT '',
    importance      INTEGER NOT NULL DEFAULT 5,
    entity_type     TEXT NOT NULL DEFAULT '',
    source_turn_id  TEXT NOT NULL DEFAULT '',
    source_text     TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_staging_hash ON memory_staging(content_hash);
CREATE INDEX IF NOT EXISTS idx_staging_layer ON memory_staging(layer);
"""


# ── 数据类 ─────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    """置信度裁决结果。"""
    action: str           # "write" | "stage" | "discard"
    confidence: float     # 综合置信度
    target_layer: str     # 目标层名
    signals: dict[str, float] = field(default_factory=dict)  # 各信号分数


# ── 信号检测 ───────────────────────────────────────────────────

class SignalDetector:
    """从 store() 的输入上下文中提取多个置信度信号。

    每个信号独立打分，互不影响。ConfidenceGate 取最高分做裁决。
    """

    @classmethod
    def detect_all(cls, content: str, **kwargs: Any) -> dict[str, float]:
        """运行所有检测器，返回 {信号名: 置信度} 字典。"""
        signals: dict[str, float] = {}

        # 空内容不触发任何信号
        if not content or not content.strip():
            return signals

        # 1. 用户纠正信号（高置信度）
        user_msg = kwargs.get("user_msg", "")
        if user_msg and cls._is_correction(user_msg):
            signals["correction"] = 0.9

        # 2. 工具失败信号（高置信度）
        source = kwargs.get("source", "")
        has_failure = kwargs.get("has_failure", False)
        if source == "failure_learner" or has_failure:
            signals["failure"] = 0.8

        # 3. 重复/强化信号（中高置信度）
        existing = kwargs.get("existing_records", None)
        if existing is not None:
            if cls._is_repetition(content, existing):
                signals["repetition"] = 0.7

        # 4. 关键词触发信号（中等置信度）
        if cls._has_trigger_keyword(content):
            signals["keyword"] = 0.5

        # 5. LLM 自觉调用信号（低置信度 — 兜底）
        if source in ("remember_tool", "llm_tool", "llm"):
            signals["llm"] = 0.3

        return signals

    @classmethod
    def _is_correction(cls, user_msg: str) -> bool:
        """检测用户是否在纠正 Agent。"""
        lower = user_msg.lower()
        for kw in CORRECTION_KEYWORDS:
            if kw in lower:
                return True
        return False

    @classmethod
    def _is_repetition(cls, content: str, existing: list[dict]) -> bool:
        """检测内容是否与已有记录高度相似。"""
        from difflib import SequenceMatcher
        content_lower = content.lower()
        for record in existing:
            existing_content = record.get("content", "").lower()
            if not existing_content:
                continue
            # 精确子串匹配 → 高度重复
            if content_lower in existing_content or existing_content in content_lower:
                return True
            # 模糊匹配
            ratio = SequenceMatcher(None, content_lower, existing_content).ratio()
            if ratio >= 0.8:
                return True
        return False

    @classmethod
    def _has_trigger_keyword(cls, content: str) -> bool:
        """检测内容是否包含触发关键词。"""
        lower = content.lower()
        for kw in SIGNAL_KEYWORDS:
            if kw in lower:
                return True
        return False


# ── 置信度裁决 ─────────────────────────────────────────────────

class ConfidenceGate:
    """综合多个信号做写入裁决。"""

    def judge(self, layer: str, content: str,
              signals: dict[str, float]) -> RoutingDecision:
        """裁决写入行为。

        Args:
            layer: 请求写入的目标层
            content: 记忆内容
            signals: SignalDetector 输出的信号字典

        Returns:
            RoutingDecision
        """
        confidence = max(signals.values()) if signals else 0.0

        if confidence >= THRESHOLD_DIRECT:
            return RoutingDecision(
                action="write",
                confidence=confidence,
                target_layer=layer,
                signals=signals,
            )
        elif confidence >= THRESHOLD_STAGING:
            return RoutingDecision(
                action="stage",
                confidence=confidence,
                target_layer=layer,
                signals=signals,
            )
        else:
            return RoutingDecision(
                action="discard",
                confidence=confidence,
                target_layer=layer,
                signals=signals,
            )


# ── 暂存与提升 ─────────────────────────────────────────────────

class StagingArea:
    """暂存低置信度记忆，证据累积后提升到正式层。

    同一条内容出现 PROMOTION_COUNT 次后，通过回调写入正式记忆层。
    """

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        *,
        promote_callback: Callable[[str, str, str, Any], None] | None = None,
    ):
        """初始化暂存区。

        Args:
            db_path: SQLite 文件路径，默认为 ":memory:"（不持久化）
            promote_callback: 提升回调，签名 (content_hash, content, layer, **kwargs)
                              kwargs 包含 source, importance 等原始参数
        """
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_STAGING_SCHEMA)
        self._promote_callback = promote_callback

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def stage(self, content: str, layer: str, confidence: float,
              **kwargs: Any) -> dict:
        """暂存一条记录。

        如果同内容已存在，递增计数；达到 PROMOTION_COUNT 则提升到正式层。

        Returns:
            {"action": "staged" | "bumped" | "promoted",
             "layer": str | None,   # 提升时返回目标层
             "count": int}
        """
        content = content.strip()
        if not content:
            return {"action": "discard", "reason": "empty_content"}

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        now = datetime.now().isoformat()

        # 查找是否已有相同内容
        existing = self._conn.execute(
            "SELECT id, count FROM memory_staging WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()

        if existing:
            row_id, count = existing
            new_count = count + 1
            self._conn.execute(
                """UPDATE memory_staging
                   SET count = ?, last_seen = ?, confidence = MAX(confidence, ?)
                   WHERE id = ?""",
                (new_count, now, confidence, row_id),
            )
            self._conn.commit()

            # 检查是否达到提升阈值
            if new_count >= PROMOTION_COUNT:
                if self._promote_callback:
                    self._promote_callback(
                        content_hash, content, layer,
                        confidence=min(confidence + 0.2, 1.0),
                        **{k: v for k, v in kwargs.items()
                           if k in ("source", "importance", "entity_type",
                                    "source_turn_id", "source_text")},
                    )
                # 从 staging 移除
                self._conn.execute("DELETE FROM memory_staging WHERE id = ?", (row_id,))
                self._conn.commit()
                return {"action": "promoted", "layer": layer, "count": new_count}

            return {"action": "bumped", "count": new_count}

        # 首次出现，插入暂存
        self._conn.execute(
            """INSERT INTO memory_staging
               (content_hash, content, layer, confidence, count,
                first_seen, last_seen, source, importance,
                entity_type, source_turn_id, source_text)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
            (
                content_hash, content, layer, confidence,
                now, now,
                kwargs.get("source", ""),
                kwargs.get("importance", 5),
                kwargs.get("entity_type", ""),
                kwargs.get("source_turn_id", ""),
                kwargs.get("source_text", ""),
            ),
        )
        self._conn.commit()
        return {"action": "staged", "count": 1}

    # ── 查询与管理 ─────────────────────────────────────

    def list_staged(self, layer: str | None = None) -> list[dict]:
        """列出暂存区中所有记录。"""
        if layer:
            cur = self._conn.execute(
                "SELECT * FROM memory_staging WHERE layer = ? ORDER BY last_seen DESC",
                (layer,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM memory_staging ORDER BY last_seen DESC",
            )

        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def count(self) -> int:
        """暂存区记录总数。"""
        return self._conn.execute("SELECT COUNT(*) FROM memory_staging").fetchone()[0]

    def flush(self, layer: str | None = None) -> int:
        """强制提升暂存区中所有记录到正式层（用于关闭前清理）。"""
        staged = self.list_staged(layer=layer)
        promoted = 0
        for record in staged:
            if self._promote_callback:
                self._promote_callback(
                    record["content_hash"],
                    record["content"],
                    record["layer"],
                    confidence=record["confidence"],
                    source=record["source"],
                    importance=record["importance"],
                )
            self._conn.execute(
                "DELETE FROM memory_staging WHERE id = ?",
                (record["id"],),
            )
            promoted += 1
        self._conn.commit()
        return promoted


__all__ = [
    "RoutingDecision", "SignalDetector", "ConfidenceGate", "StagingArea",
    "THRESHOLD_DIRECT", "THRESHOLD_STAGING", "THRESHOLD_DISCARD",
    "PROMOTION_COUNT",
]
