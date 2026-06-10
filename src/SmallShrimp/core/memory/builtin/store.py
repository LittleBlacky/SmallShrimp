"""SQLite-backed memory store implementing the same interface as _JSONLStore."""
from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .common import (
    MemoryLayer,
    MemoryRecord,
    VALID_MEMORY_LAYERS,
    _normalize_layer,
    _new_memory_id,
    _clamp_int,
    _clamp_float,
    _is_duplicate_memory,
    _rank_memory,
    _memory_quality_boost,
)

# ── Schema ───────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_records (
    id              TEXT PRIMARY KEY,
    content         TEXT NOT NULL,
    layer           TEXT NOT NULL CHECK(layer IN ('profile','facts','projects','reflections','sessions')),
    source          TEXT NOT NULL DEFAULT 'auto',
    importance      INTEGER NOT NULL DEFAULT 5 CHECK(importance BETWEEN 0 AND 10),
    confidence      REAL NOT NULL DEFAULT 1.0 CHECK(confidence BETWEEN 0.0 AND 1.0),
    recall_count    INTEGER NOT NULL DEFAULT 0,
    archived        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_recalled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_layer ON memory_records(layer);
CREATE INDEX IF NOT EXISTS idx_memory_importance ON memory_records(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memory_recall ON memory_records(recall_count DESC);
"""


class SQLiteBackend:
    """SQLite 存储后端，管理所有层在一个数据库中。

    用法与 _JSONLStore 兼容，但 layer 作为方法参数而非构造参数。
    """

    def __init__(self, db_path: Path, max_entries_per_layer: int = 2000):
        self.db_path = db_path
        self.max_entries = max_entries_per_layer
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ── 存储接口（与 _JSONLStore 兼容） ──────────────────

    def store(self, layer: str, content: str, *, source: str = "auto",
              importance: int | None = None, confidence: float = 1.0,
              dedup_threshold: float = 7.0) -> MemoryRecord:
        """写入一条记忆记录，含去重。"""
        normalized_layer = _normalize_layer(layer)
        content = content.strip()
        if not content:
            raise ValueError("memory content must be non-empty")

        now = datetime.now().isoformat()
        importance = _clamp_int(importance if importance is not None else _LAYER_DEFAULT_IMP.get(normalized_layer, 5), 0, 10)
        confidence = _clamp_float(confidence, 0.0, 1.0)

        # 去重检查
        for existing in self.list_all(layer=normalized_layer):
            if _is_duplicate_memory(content, existing.get("content", ""), dedup_threshold):
                self._update(existing["id"], content=content, source=source,
                             importance=max(existing.get("importance", 0), importance),
                             confidence=confidence, updated_at=now)
                return {**existing, "content": content, "source": source,
                        "importance": importance, "confidence": confidence, "updated_at": now}

        record: MemoryRecord = {
            "id": _new_memory_id(),
            "content": content,
            "layer": normalized_layer,
            "source": source,
            "importance": importance,
            "confidence": confidence,
            "recall_count": 0,
            "created_at": now,
            "updated_at": now,
            "archived": False,
        }
        self._conn.execute(
            """INSERT INTO memory_records (id, content, layer, source, importance, confidence,
               recall_count, created_at, updated_at, archived)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record["id"], record["content"], record["layer"], record["source"],
             record["importance"], record["confidence"], record["recall_count"],
             record["created_at"], record["updated_at"], 0),
        )
        self._conn.commit()
        self._evict_layer(normalized_layer)
        return record

    def search(self, query: str, layer: str | None = None, limit: int = 10) -> list[MemoryRecord]:
        """检索记忆记录。"""
        records = self.list_all(layer=layer)
        scored: list[tuple[float, MemoryRecord]] = []
        for record in records:
            score = _rank_memory(query, record.get("content", ""))
            if score >= 1.0 or not query:
                scored.append((score + _memory_quality_boost(record), record))
        scored.sort(key=lambda item: item[0], reverse=True)
        result = [record for _, record in scored[:limit]]

        if result and query:
            now = datetime.now().isoformat()
            recalled_ids = {record["id"] for record in result}
            for record_id in recalled_ids:
                self._conn.execute(
                    "UPDATE memory_records SET recall_count = recall_count + 1, last_recalled_at = ? WHERE id = ?",
                    (now, record_id),
                )
            self._conn.commit()
        return result

    def list_all(self, layer: str | None = None, limit: int = 0) -> list[MemoryRecord]:
        """列出记录，按 importance 降序。"""
        if layer:
            normalized = _normalize_layer(layer)
            rows = self._conn.execute(
                "SELECT * FROM memory_records WHERE layer = ? AND archived = 0 ORDER BY importance DESC, updated_at DESC",
                (normalized,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memory_records WHERE archived = 0 ORDER BY importance DESC, updated_at DESC"
            ).fetchall()
        records = [_row_to_record(r) for r in rows]
        if limit:
            return records[:limit]
        return records

    def delete(self, record_id: str) -> bool:
        """删除一条记录。"""
        cur = self._conn.execute("DELETE FROM memory_records WHERE id = ?", (record_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def consolidate(self, threshold: float = 0.8, layer: str | None = None) -> int:
        """合并相似记录。"""
        records = self.list_all(layer=layer)
        records.sort(key=lambda r: (r.get("importance", 0), r.get("recall_count", 0)), reverse=True)

        removed: set[str] = set()
        merged = 0
        for i, left in enumerate(records):
            if left["id"] in removed:
                continue
            for right in records[i + 1:]:
                if right["id"] in removed:
                    continue
                similarity = SequenceMatcher(None, left.get("content", ""), right.get("content", "")).ratio()
                if similarity >= threshold:
                    left["importance"] = max(left.get("importance", 0), right.get("importance", 0))
                    left["recall_count"] = left.get("recall_count", 0) + right.get("recall_count", 0)
                    left["updated_at"] = datetime.now().isoformat()
                    self._update(left["id"], importance=left["importance"],
                                 recall_count=left["recall_count"], updated_at=left["updated_at"])
                    self._conn.execute("DELETE FROM memory_records WHERE id = ?", (right["id"],))
                    removed.add(right["id"])
                    merged += 1
        if merged:
            self._conn.commit()
        return merged

    # ── 内部方法 ────────────────────────────────────────

    def _update(self, record_id: str, **kwargs: Any) -> None:
        """更新记录的指定字段。"""
        sets = []
        values = []
        for key, val in kwargs.items():
            sets.append(f"{key} = ?")
            values.append(val)
        values.append(record_id)
        self._conn.execute(
            f"UPDATE memory_records SET {', '.join(sets)} WHERE id = ?", values
        )

    def _evict_layer(self, layer: str) -> None:
        """LRU 淘汰：超过上限时删除 importance 最低的。"""
        count = self._conn.execute(
            "SELECT COUNT(*) FROM memory_records WHERE layer = ? AND archived = 0", (layer,)
        ).fetchone()[0]
        over = count - self.max_entries
        if over <= 0:
            return
        self._conn.execute(
            """DELETE FROM memory_records WHERE id IN (
                SELECT id FROM memory_records WHERE layer = ? AND archived = 0
                ORDER BY importance ASC, recall_count ASC, created_at ASC
                LIMIT ?
            )""",
            (layer, over),
        )
        self._conn.commit()


# ── Per-layer default importance ────────────────────────

_LAYER_DEFAULT_IMP = {
    "profile": 10,
    "facts": 5,
    "projects": 6,
    "reflections": 6,
    "sessions": 3,
}


# ── Helpers ──────────────────────────────────────────────

def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    return {
        "id": row["id"],
        "content": row["content"],
        "layer": row["layer"],
        "source": row["source"],
        "importance": row["importance"],
        "confidence": row["confidence"],
        "recall_count": row["recall_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "archived": bool(row["archived"]),
        **({"last_recalled_at": row["last_recalled_at"]} if row["last_recalled_at"] else {}),
    }
