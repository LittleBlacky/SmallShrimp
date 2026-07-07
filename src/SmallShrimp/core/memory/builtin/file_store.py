"""Memory store — SQLite as sole truth source.

No Markdown file dependency. All memories stored in SQLite with FTS5
and optional vector search. Safety mechanisms include soft delete,
version history, and audit log.
"""
from __future__ import annotations

import hashlib
import re as _re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import (
    MemoryLayer,
    MemoryRecord,
    VALID_MEMORY_LAYERS,
    _normalize_layer,
    normalize_entity_type,
)
from .hybrid_search import (
    EmbeddingProvider,
    create_embedding_provider,
    setup_vector_table,
    insert_vector,
    hybrid_search as _hybrid_search,
    _HAS_SQLITE_VEC,
)

# ── jieba 分词（可选依赖） ────────────────────────────────

_HAS_JIEBA = False
try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    pass


def _segment(text: str) -> str:
    """jieba 分词，返回空格分隔的词序列。"""
    if not _HAS_JIEBA:
        return text
    return " ".join(t for t in jieba.lcut(text) if t.strip())


def _expand_query_jieba(query: str) -> str:
    """jieba 分词后用 OR 连接，适合 FTS5 MATCH。"""
    if not _HAS_JIEBA or not query.strip():
        return query
    terms = [t for t in jieba.lcut(query) if t.strip()]
    if not terms:
        return query
    return " OR ".join(f'"{t}"' for t in terms)


# ── Schema ───────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_index (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    layer       TEXT NOT NULL,
    content     TEXT NOT NULL,
    file_path   TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL DEFAULT '',
    access_count INTEGER NOT NULL DEFAULT 0,
    source_turn_id TEXT NOT NULL DEFAULT '',
    source_text  TEXT NOT NULL DEFAULT '',
    importance  INTEGER NOT NULL DEFAULT 5,
    deleted     INTEGER NOT NULL DEFAULT 0,
    version     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
USING fts5(content_jieba, content_raw, tokenize='unicode61');

CREATE INDEX IF NOT EXISTS idx_index_layer ON memory_index(layer);
CREATE INDEX IF NOT EXISTS idx_index_deleted ON memory_index(deleted);

CREATE TABLE IF NOT EXISTS memory_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id   INTEGER NOT NULL,
    content     TEXT NOT NULL,
    layer       TEXT NOT NULL,
    version     INTEGER NOT NULL,
    changed_at  TEXT NOT NULL,
    changed_by  TEXT DEFAULT 'agent',
    reason      TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS memory_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id       INTEGER,
    action          TEXT NOT NULL,
    content_before  TEXT,
    content_after   TEXT,
    layer           TEXT,
    timestamp       TEXT NOT NULL,
    actor           TEXT DEFAULT 'agent',
    reason          TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_record ON memory_audit(record_id);
CREATE INDEX IF NOT EXISTS idx_history_record ON memory_history(record_id);
"""


class MemoryStore:
    """SQLite-only memory store with safety mechanisms.

    Features:
    - FTS5 full-text search (jieba segmentation)
    - Optional vector search (sqlite-vec)
    - Soft delete (recoverable)
    - Version history (every edit tracked)
    - Audit log (all operations logged)
    """

    def __init__(self, db_path: Path, use_vector: bool = False,
                 embedding_provider: EmbeddingProvider | None = None):
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.row_factory = sqlite3.Row
            self._migrate_legacy_schema()
            self._conn.executescript(_SCHEMA)
        except Exception:
            self._conn.close()
            raise

        # Embedding provider
        self._embedding_provider = embedding_provider
        if self._embedding_provider is None and use_vector:
            self._embedding_provider = create_embedding_provider("local")

        # Vector table (optional)
        self._has_vector = bool(
            self._embedding_provider is not None and _HAS_SQLITE_VEC
        )
        if self._has_vector:
            try:
                setup_vector_table(self._conn, self._embedding_provider)
            except Exception:
                self._has_vector = False

    def _migrate_legacy_schema(self) -> None:
        """Add missing columns for pre-safety-memory SQLite databases."""
        exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memory_index'"
        ).fetchone()
        if not exists:
            return

        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(memory_index)").fetchall()
        }
        columns = {
            "file_path": "TEXT NOT NULL DEFAULT ''",
            "bullet": "TEXT NOT NULL DEFAULT ''",
            "entity_type": "TEXT NOT NULL DEFAULT ''",
            "access_count": "INTEGER NOT NULL DEFAULT 0",
            "source_turn_id": "TEXT NOT NULL DEFAULT ''",
            "source_text": "TEXT NOT NULL DEFAULT ''",
            "importance": "INTEGER NOT NULL DEFAULT 5",
            "deleted": "INTEGER NOT NULL DEFAULT 0",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in columns.items():
            if name not in existing:
                self._conn.execute(
                    f"ALTER TABLE memory_index ADD COLUMN {name} {definition}"
                )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ── Write ────────────────────────────────────────────

    def store(self, layer: str, content: str, **kwargs: Any) -> MemoryRecord:
        """Store a memory entry. Returns the created record."""
        normalized = _normalize_layer(layer)
        content = content.strip()
        if not content:
            raise ValueError("memory content must be non-empty")

        now = datetime.now()
        source = kwargs.get("source", "auto")
        importance = kwargs.get("importance", 5)
        entity_type = normalize_entity_type(kwargs.get("entity_type"))
        source_turn_id = str(kwargs.get("source_turn_id", ""))
        source_text = str(kwargs.get("source_text", ""))

        insert_values = {
            "layer": normalized,
            "content": content,
            "file_path": str(kwargs.get("file_path", "")),
            "bullet": "",
            "mtime": now.isoformat(),
            "entity_type": entity_type,
            "access_count": 0,
            "source_turn_id": source_turn_id,
            "source_text": source_text,
            "importance": importance,
            "deleted": 0,
            "version": 1,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        table_columns = self._conn.execute("PRAGMA table_info(memory_index)").fetchall()
        columns: list[str] = []
        values: list[Any] = []
        for column in table_columns:
            name = column["name"]
            if name == "id":
                continue
            if name in insert_values:
                columns.append(name)
                values.append(insert_values[name])
            elif column["notnull"] and column["dflt_value"] is None:
                columns.append(name)
                values.append("")

        placeholders = ", ".join("?" for _ in columns)
        column_names = ", ".join(columns)
        cur = self._conn.execute(
            f"INSERT INTO memory_index ({column_names}) VALUES ({placeholders})",
            values,
        )
        record_id = cur.lastrowid

        # FTS5 index
        seg = _segment(content)
        self._conn.execute(
            "INSERT INTO memory_fts(rowid, content_jieba, content_raw) VALUES (?, ?, ?)",
            (record_id, seg, content),
        )

        # Vector index (optional)
        if self._has_vector:
            insert_vector(self._conn, record_id, content, self._embedding_provider)

        # Audit log
        self._audit(record_id, "create", None, content, normalized, "agent", source)

        self._conn.commit()

        return {
            "id": str(record_id),
            "content": content,
            "layer": normalized,
            "source": source,
            "importance": importance,
        }

    # ── Update ───────────────────────────────────────────

    def update(self, record_id: str, new_content: str, *,
               reason: str = "", actor: str = "agent") -> bool:
        """Update a memory entry. Saves version history and audit log."""
        record = self._get_record(record_id)
        if not record or record["deleted"]:
            return False

        old_content = record["content"]
        old_version = record["version"]
        new_version = old_version + 1
        now = datetime.now().isoformat()

        # Save to history before updating
        self._conn.execute(
            """INSERT INTO memory_history
               (record_id, content, layer, version, changed_at, changed_by, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (record_id, old_content, record["layer"], old_version, now, actor, reason),
        )

        # Update the record
        self._conn.execute(
            """UPDATE memory_index
               SET content = ?, version = ?, updated_at = ?
               WHERE id = ?""",
            (new_content, new_version, now, int(record_id)),
        )

        # Update FTS5
        self._conn.execute(
            "DELETE FROM memory_fts WHERE rowid = ?", (int(record_id),)
        )
        seg = _segment(new_content)
        self._conn.execute(
            "INSERT INTO memory_fts(rowid, content_jieba, content_raw) VALUES (?, ?, ?)",
            (int(record_id), seg, new_content),
        )

        # Audit log
        self._audit(int(record_id), "update", old_content, new_content,
                    record["layer"], actor, reason)

        self._conn.commit()
        return True

    # ── Soft Delete ──────────────────────────────────────

    def delete(self, record_id: str, *,
               reason: str = "", actor: str = "agent") -> bool:
        """Soft delete — marks as deleted, keeps data for recovery."""
        record = self._get_record(record_id)
        if not record:
            return False

        now = datetime.now().isoformat()
        self._conn.execute(
            "UPDATE memory_index SET deleted = 1, updated_at = ? WHERE id = ?",
            (now, int(record_id)),
        )
        self._conn.execute(
            "DELETE FROM memory_fts WHERE rowid = ?", (int(record_id),)
        )

        # Audit log
        self._audit(int(record_id), "delete", record["content"], None,
                    record["layer"], actor, reason)

        self._conn.commit()
        return True

    def restore(self, record_id: str, *,
                reason: str = "", actor: str = "agent") -> bool:
        """Restore a soft-deleted record."""
        record = self._get_record(record_id, include_deleted=True)
        if not record or not record["deleted"]:
            return False

        now = datetime.now().isoformat()
        self._conn.execute(
            "UPDATE memory_index SET deleted = 0, updated_at = ? WHERE id = ?",
            (now, int(record_id)),
        )
        seg = _segment(record["content"])
        self._conn.execute(
            "INSERT INTO memory_fts(rowid, content_jieba, content_raw) VALUES (?, ?, ?)",
            (int(record_id), seg, record["content"]),
        )

        # Audit log
        self._audit(int(record_id), "restore", None, record["content"],
                    record["layer"], actor, reason)

        self._conn.commit()
        return True

    # ── Search ───────────────────────────────────────────

    def search(self, query: str, layer: str | None = None, limit: int = 10,
               include_deleted: bool = False) -> list[MemoryRecord]:
        """FTS5 + optional vector hybrid search."""
        if not query.strip():
            return []

        fts_q = _expand_query_jieba(query)

        results = _hybrid_search(
            conn=self._conn,
            query=query,
            layer=layer,
            limit=limit,
            fts_query=fts_q,
            use_vector=self._has_vector,
            embedding_provider=self._embedding_provider,
        )

        # Filter deleted
        if not include_deleted:
            results = [r for r in results if not r.get("deleted")]

        return results

    # ── List / Get ───────────────────────────────────────

    def list_all(self, layer: str | None = None, limit: int = 50,
                 include_deleted: bool = False) -> list[MemoryRecord]:
        """List all records."""
        conditions = []
        params: list[Any] = []

        if not include_deleted:
            conditions.append("deleted = 0")
        if layer:
            conditions.append("layer = ?")
            params.append(_normalize_layer(layer))

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        rows = self._conn.execute(
            f"""SELECT id, layer, content, entity_type, access_count,
                       importance, version, created_at, updated_at, deleted
                FROM memory_index {where}
                ORDER BY id DESC LIMIT ?""",
            params + [limit],
        ).fetchall()

        return [self._row_to_record(r) for r in rows]

    def get(self, record_id: str) -> MemoryRecord | None:
        """Get a single record by ID."""
        return self._get_record(record_id)

    def _get_record(self, record_id: str, *,
                    include_deleted: bool = False) -> MemoryRecord | None:
        """Internal: get a record by ID."""
        condition = "" if include_deleted else "AND deleted = 0"
        row = self._conn.execute(
            f"""SELECT id, layer, content, entity_type, access_count,
                       importance, version, created_at, updated_at, deleted
                FROM memory_index WHERE id = ? {condition}""",
            (int(record_id),),
        ).fetchone()
        return self._row_to_record(row) if row else None

    @staticmethod
    def _row_to_record(row) -> MemoryRecord:
        """Convert a SQLite row to MemoryRecord dict."""
        return {
            "id": str(row["id"]),
            "layer": row["layer"],
            "content": row["content"],
            "entity_type": row["entity_type"],
            "access_count": row["access_count"],
            "importance": row["importance"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted": bool(row["deleted"]),
        }

    # ── Access Count ─────────────────────────────────────

    def touch_recall(self, record_ids: list[int | str]) -> None:
        """Increment access_count on retrieval hit."""
        if not record_ids:
            return
        now = datetime.now().isoformat()
        ids = [int(i) if isinstance(i, str) and i.isdigit() else i for i in record_ids]
        placeholders = ",".join("?" for _ in ids)
        self._conn.execute(
            f"""UPDATE memory_index
                SET access_count = access_count + 1, updated_at = ?
                WHERE id IN ({placeholders})""",
            [now] + ids,
        )
        self._conn.commit()

    # ── History ──────────────────────────────────────────

    def get_history(self, record_id: str) -> list[dict]:
        """Get version history for a record."""
        rows = self._conn.execute(
            """SELECT content, layer, version, changed_at, changed_by, reason
               FROM memory_history WHERE record_id = ?
               ORDER BY version DESC""",
            (int(record_id),),
        ).fetchall()
        return [
            {
                "content": r["content"],
                "layer": r["layer"],
                "version": r["version"],
                "changed_at": r["changed_at"],
                "changed_by": r["changed_by"],
                "reason": r["reason"],
            }
            for r in rows
        ]

    # ── Audit ────────────────────────────────────────────

    def get_audit(self, limit: int = 50, record_id: str | None = None) -> list[dict]:
        """Get audit log entries."""
        if record_id:
            rows = self._conn.execute(
                """SELECT id, record_id, action, content_before, content_after,
                          layer, timestamp, actor, reason
                   FROM memory_audit WHERE record_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (int(record_id), limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT id, record_id, action, content_before, content_after,
                          layer, timestamp, actor, reason
                   FROM memory_audit ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "record_id": r["record_id"],
                "action": r["action"],
                "content_before": r["content_before"],
                "content_after": r["content_after"],
                "layer": r["layer"],
                "timestamp": r["timestamp"],
                "actor": r["actor"],
                "reason": r["reason"],
            }
            for r in rows
        ]

    def _audit(self, record_id: int, action: str,
               content_before: str | None, content_after: str | None,
               layer: str, actor: str = "agent", reason: str = "") -> None:
        """Write an audit log entry."""
        self._conn.execute(
            """INSERT INTO memory_audit
               (record_id, action, content_before, content_after, layer,
                timestamp, actor, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, action, content_before, content_after, layer,
             datetime.now().isoformat(), actor, reason),
        )

    # ── Export ───────────────────────────────────────────

    def export_markdown(self, layer: str | None = None) -> str:
        """Export memories as Markdown (read-only, for user viewing)."""
        records = self.list_all(layer=layer, limit=1000)
        if not records:
            return ""

        lines: list[str] = []
        current_layer = None

        for r in records:
            if r["layer"] != current_layer:
                current_layer = r["layer"]
                lines.append(f"\n## {current_layer}\n")
            lines.append(f"- {r['content']}")

        return "\n".join(lines)
