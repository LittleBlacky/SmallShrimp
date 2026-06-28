"""Lightweight graph store — SQLite-backed entities and relations.

No Neo4j dependency. Uses FTS5 for full-text search.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Entity:
    id: int
    name: str
    type: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    importance: float = 1.0
    access_count: float = 0.0
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "type": self.type,
            "description": self.description, "aliases": self.aliases,
            "importance": self.importance, "access_count": self.access_count,
            "importance": self.importance,
        }


@dataclass
class Relation:
    source_id: int
    predicate: str
    target_id: int
    source_text: str = ""
    weight: float = 1.0
    created_at: float = 0.0


@dataclass
class GraphContext:
    entities: list[Entity]
    relations: list[Relation]


class GraphStore:
    """SQLite-backed knowledge graph with FTS5 search.

    Can share a connection with MarkdownStore by passing conn= at init.
    Table names (entities/relations/entities_fts) don't conflict with
    memory tables (memory_index/memory_fts/memory_vec).
    """

    def __init__(
        self,
        db_path: str | Path = "",
        conn: sqlite3.Connection | None = None,
    ):
        self._external_conn = conn is not None
        self.db_path = str(db_path) if not conn else ""
        self._conn: sqlite3.Connection | None = conn
        if self._conn is not None:
            self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL DEFAULT 'other',
                description TEXT DEFAULT '',
                aliases TEXT DEFAULT '[]',
                importance REAL DEFAULT 1.0,
                access_count REAL DEFAULT 0.0,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL REFERENCES entities(id),
                predicate TEXT NOT NULL,
                target_id INTEGER NOT NULL REFERENCES entities(id),
                source_text TEXT DEFAULT '',
                weight REAL DEFAULT 1.0,
                created_at REAL NOT NULL,
                UNIQUE(source_id, predicate, target_id)
            );

            CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
        """)

        # FTS5 index for entity search
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts
                USING fts5(name, description, aliases, content=entities, content_rowid=id)
            """)
        except sqlite3.OperationalError:
            pass  # FTS5 not available

        # Triggers to keep FTS in sync
        for trigger_sql in [
            """CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
                INSERT INTO entities_fts(rowid, name, description, aliases)
                VALUES (new.id, new.name, new.description, new.aliases);
            END""",
            """CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
                INSERT INTO entities_fts(entities_fts, rowid, name, description, aliases)
                VALUES ('delete', old.id, old.name, old.description, old.aliases);
            END""",
            """CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
                INSERT INTO entities_fts(entities_fts, rowid, name, description, aliases)
                VALUES ('delete', old.id, old.name, old.description, old.aliases);
                INSERT INTO entities_fts(rowid, name, description, aliases)
                VALUES (new.id, new.name, new.description, new.aliases);
            END""",
        ]:
            try:
                conn.execute(trigger_sql)
            except sqlite3.OperationalError:
                pass

        conn.commit()

    def close(self) -> None:
        if self._conn and not self._external_conn:
            self._conn.close()
        self._conn = None

    @staticmethod
    def _row_to_entity(row) -> Entity:
        """Convert a SQLite Row to Entity."""
        return Entity(
            id=row["id"], name=row["name"], type=row["type"],
            description=row["description"],
            aliases=json.loads(row["aliases"]) if row["aliases"] else [],
            importance=row["importance"],
            access_count=row["access_count"] if "access_count" in row.keys() else 0.0,
            created_at=row["created_at"],
        )

    def bump_access(self, name: str, amount: float = 1.0) -> None:
        """Increment access_count for an entity."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE entities SET access_count = access_count + ? WHERE name = ?",
            (amount, name),
        )
        conn.commit()

    # ── Entity CRUD ──────────────────────────────────────

    def upsert_entity(
        self,
        name: str,
        entity_type: str = "other",
        description: str = "",
        aliases: list[str] | None = None,
        importance: float = 1.0,
    ) -> Entity:
        """Insert or update an entity. Returns the Entity."""
        conn = self._get_conn()
        now = time.time()
        aliases_json = json.dumps(aliases or [], ensure_ascii=False)

        existing = conn.execute(
            "SELECT id FROM entities WHERE name = ?", (name,)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE entities SET type=?, description=?, aliases=?, importance=?
                WHERE id=?
            """, (entity_type, description, aliases_json, importance, existing["id"]))
            entity_id = existing["id"]
        else:
            cur = conn.execute("""
                INSERT INTO entities (name, type, description, aliases, importance, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, entity_type, description, aliases_json, importance, now))
            entity_id = cur.lastrowid

        conn.commit()
        return Entity(
            id=entity_id, name=name, type=entity_type,
            description=description, aliases=aliases or [],
            importance=importance, created_at=now,
        )

    def get_entity(self, name: str) -> Entity | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM entities WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_entity(row)

    def get_entity_by_id(self, entity_id: int) -> Entity | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_entity(row)

    def search_entities(self, query: str, limit: int = 10) -> list[Entity]:
        """FTS5 search on entities."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT e.* FROM entities_fts fts
                JOIN entities e ON e.id = fts.rowid
                WHERE entities_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit)).fetchall()
        except sqlite3.OperationalError:
            # Fallback to LIKE search
            like = f"%{query}%"
            rows = conn.execute("""
                SELECT * FROM entities
                WHERE name LIKE ? OR description LIKE ?
                ORDER BY importance DESC
                LIMIT ?
            """, (like, like, limit)).fetchall()

        return [self._row_to_entity(r) for r in rows]

    # ── Relation CRUD ────────────────────────────────────

    def add_relation(
        self,
        source_name: str,
        predicate: str,
        target_name: str,
        source_text: str = "",
        weight: float = 1.0,
    ) -> bool:
        """Add a relation between two entities (by name). Returns True if new."""
        conn = self._get_conn()
        now = time.time()

        source = self.get_entity(source_name)
        target = self.get_entity(target_name)
        if not source or not target:
            return False

        try:
            conn.execute("""
                INSERT OR IGNORE INTO relations
                (source_id, predicate, target_id, source_text, weight, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source.id, predicate, target.id, source_text, weight, now))
            conn.commit()
            return conn.total_changes > 0
        except sqlite3.IntegrityError:
            return False

    def get_neighbors(self, entity_name: str, depth: int = 1) -> GraphContext:
        """Get neighboring entities and relations (1-hop by default)."""
        conn = self._get_conn()
        entity = self.get_entity(entity_name)
        if not entity:
            return GraphContext(entities=[], relations=[])

        visited_ids: set[int] = {entity.id}
        frontier: set[int] = {entity.id}
        all_entities: list[Entity] = [entity]
        all_relations: list[Relation] = []

        for _ in range(depth):
            next_frontier: set[int] = set()
            for eid in frontier:
                # Outgoing
                rows = conn.execute("""
                    SELECT r.*, e.name as target_name, e.type as target_type,
                           e.description as target_desc, e.aliases as target_aliases,
                           e.importance as target_imp
                    FROM relations r JOIN entities e ON e.id = r.target_id
                    WHERE r.source_id = ?
                """, (eid,)).fetchall()
                for r in rows:
                    all_relations.append(Relation(
                        source_id=r["source_id"], predicate=r["predicate"],
                        target_id=r["target_id"], source_text=r["source_text"],
                        weight=r["weight"],
                    ))
                    if r["target_id"] not in visited_ids:
                        visited_ids.add(r["target_id"])
                        next_frontier.add(r["target_id"])
                        all_entities.append(Entity(
                            id=r["target_id"], name=r["target_name"],
                            type=r["target_type"], description=r["target_desc"],
                            aliases=json.loads(r["target_aliases"]) if r["target_aliases"] else [],
                            importance=r["target_imp"],
                            access_count=r.get("target_access", 0.0),
                        ))

                # Incoming
                rows = conn.execute("""
                    SELECT r.*, e.name as source_name, e.type as source_type,
                           e.description as source_desc, e.aliases as source_aliases,
                           e.importance as source_imp
                    FROM relations r JOIN entities e ON e.id = r.source_id
                    WHERE r.target_id = ?
                """, (eid,)).fetchall()
                for r in rows:
                    all_relations.append(Relation(
                        source_id=r["source_id"], predicate=r["predicate"],
                        target_id=r["target_id"], source_text=r["source_text"],
                        weight=r["weight"],
                    ))
                    if r["source_id"] not in visited_ids:
                        visited_ids.add(r["source_id"])
                        next_frontier.add(r["source_id"])
                        all_entities.append(Entity(
                            id=r["source_id"], name=r["source_name"],
                            type=r["source_type"], description=r["source_desc"],
                            aliases=json.loads(r["source_aliases"]) if r["source_aliases"] else [],
                            importance=r["source_imp"],
                            access_count=r.get("source_access", 0.0),
                        ))

            frontier = next_frontier

        return GraphContext(entities=all_entities, relations=all_relations)

    def get_all_entities(self, limit: int = 100) -> list[Entity]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM entities ORDER BY importance DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def get_entity_count(self) -> int:
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]

    def get_relation_count(self) -> int:
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
