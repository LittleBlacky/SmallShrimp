"""Markdown 文件存储 + SQLite FTS5 索引。

记忆以 .md 文件为真相源，SQLite 仅为检索加速。
用户可直接编辑 .md 文件，修改后自动重新索引。

检索: 使用 jieba 分词 + FTS5 OR 匹配（46% recall@5, 78ms）。
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
    _new_memory_id,
)
from .hybrid_search import (
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

# ── 文件映射 ─────────────────────────────────────────────

_LAYER_TO_FILE: dict[str, str] = {
    "profile": "profile.md",
    "facts": "facts.md",
    "projects": "projects.md",
    "reflections": "reflections.md",
    "sessions": None,  # sessions 用 daily/
}

_DAILY_DIR = "daily"


def _file_path(memory_dir: Path, layer: MemoryLayer) -> Path:
    """返回层对应的 .md 文件路径。"""
    if layer == "sessions":
        return memory_dir / _DAILY_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.md"
    filename = _LAYER_TO_FILE.get(layer, f"{layer}.md")
    return memory_dir / filename


# ── Schema ───────────────────────────────────────────────

_FTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_index (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT NOT NULL,
    layer       TEXT NOT NULL,
    content     TEXT NOT NULL,
    bullet      TEXT NOT NULL,
    mtime       INTEGER NOT NULL,
    hash        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
USING fts5(content_jieba, content_raw, tokenize='unicode61');

CREATE INDEX IF NOT EXISTS idx_index_layer ON memory_index(layer);
CREATE INDEX IF NOT EXISTS idx_index_file ON memory_index(file_path);
"""


class MarkdownStore:
    """Markdown 文件存储后端。

    写入时: 追加 bullet 到 .md 文件 + 更新 SQLite FTS5 索引
    检索时: FTS5 全文搜索，可选 HRR 向量融合
    读取时: 从 .md 文件加载
    """

    def __init__(self, memory_dir: Path, use_vector: bool = False):
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / _DAILY_DIR).mkdir(parents=True, exist_ok=True)

        # SQLite 索引
        self._db_path = memory_dir / ".index.db"
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_FTS_SCHEMA)

        # 向量表（仅当显式启用 + 依赖可用）
        self._has_vector = False
        if use_vector and _HAS_SQLITE_VEC:
            try:
                setup_vector_table(self._conn)
                self._has_vector = True
            except Exception:
                pass

        # 确保所有层对应的 .md 文件存在
        for layer in ["profile", "facts", "projects", "reflections"]:
            path = _file_path(memory_dir, layer)
            if not path.exists():
                path.write_text(f"# {_FILE_HEADERS.get(layer, layer)}\n\n", encoding="utf-8")

    def close(self) -> None:
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ── 写入 ───────────────────────────────────────────

    def store(self, layer: str, content: str, **kwargs: Any) -> MemoryRecord:
        """写入一条记忆：写 .md 文件 + 更新索引。"""
        normalized = _normalize_layer(layer)
        content = content.strip()
        if not content:
            raise ValueError("memory content must be non-empty")

        now = datetime.now()
        # 生成 bullet（带元数据）
        source = kwargs.get("source", "auto")
        importance = kwargs.get("importance", 5)
        bullet = f"- {content}  `[{source}]`\n"

        # 写入 .md 文件（追加）
        file_path = _file_path(self.memory_dir, normalized)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(bullet)

        # 更新索引
        mtime = int(now.timestamp())
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        cur = self._conn.execute(
            """INSERT INTO memory_index (file_path, layer, content, bullet, mtime, hash, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(file_path.relative_to(self.memory_dir)), normalized, content, bullet.strip(),
             mtime, content_hash, now.isoformat(), now.isoformat()),
        )
        # 同步 FTS5（jieba 分词）
        seg = _segment(content)
        self._conn.execute(
            "INSERT INTO memory_fts(rowid, content_jieba, content_raw) VALUES (?, ?, ?)",
            (cur.lastrowid, seg, content),
        )
        # 同步向量（如果可用）
        if self._has_vector:
            insert_vector(self._conn, cur.lastrowid, content)
        self._conn.commit()

        return {
            "id": str(self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]),
            "content": content,
            "layer": normalized,
            "source": source,
            "importance": importance,
            "file_path": str(file_path),
        }

    def store_daily(self, summary: str, completed: list[str] | None = None,
                    todo: list[str] | None = None) -> None:
        """写入每日日志。"""
        today = datetime.now().strftime("%Y-%m-%d")
        path = self.memory_dir / _DAILY_DIR / f"{today}.md"

        # 当日志已存在时，追加内容
        lines: list[str] = []
        if path.exists():
            content = path.read_text(encoding="utf-8").rstrip()
            # 去掉末尾的旧摘要（如果有），保留待办
            if "## 会话摘要" in content:
                content = content[:content.index("## 会话摘要")].rstrip()
            lines = [content]

        lines.append(f"\n## 会话摘要\n- {summary}")
        if completed:
            lines.append(f"\n## 完成事项")
            for item in completed:
                lines.append(f"- {item}")
        if todo:
            lines.append(f"\n## 待办")
            for item in todo:
                lines.append(f"- [ ] {item}")
        lines.append("")  # trailing newline

        path.write_text("\n".join(lines), encoding="utf-8")

    # ── 检索 ───────────────────────────────────────────

    def search(self, query: str, layer: str | None = None, limit: int = 10,
               use_hrr: bool = False) -> list[MemoryRecord]:
        """混合检索: FTS5 + 向量（可选）+ MMR + 时间衰减。"""
        if not query.strip():
            return []

        # jieba OR 查询
        fts_q = _expand_query_jieba(query)

        # 混合检索
        results = _hybrid_search(
            conn=self._conn,
            query=query,
            layer=layer,
            limit=limit,
            fts_query=fts_q,
            use_vector=self._has_vector,
        )

        # 补齐 memory_index 中的字段
        for r in results:
            info = self._conn.execute(
                "SELECT file_path, bullet, updated_at FROM memory_index WHERE id = ?",
                (r["id"],),
            ).fetchone()
            if info:
                r["file_path"] = info[0]
                r["bullet"] = info[1]
                r["updated_at"] = info[2]

        return results

        results = []
        for row in rows:
            results.append({
                "id": str(row[0]),
                "file_path": row[1],
                "layer": row[2],
                "content": row[3],
                "bullet": row[4],
                "fts_rank": row[7],
                "created_at": row[5],
                "updated_at": row[6],
            })

        # HRR 重排序（如果启用）
        if use_hrr and results:
            try:
                from ....benchmarks.unit.memory.hrr_vector_recall.hrr import encode_text, similarity
                qv = encode_text(query)
                for r in results:
                    rv = encode_text(r["content"])
                    r["hrr_score"] = (similarity(qv, rv) + 1.0) / 2.0
                # 混合排序
                for r in results:
                    r["final_score"] = r.get("fts_rank", 0) * 0.4 + r.get("hrr_score", 0) * 0.6
                results.sort(key=lambda r: r["final_score"], reverse=True)
            except ImportError:
                pass  # 无 HRR 则按 FTS5 排序

        return results[:limit]

    def list_all(self, layer: str | None = None, limit: int = 50) -> list[MemoryRecord]:
        """列出索引中的所有记录。"""
        params: list[Any] = []
        layer_clause = ""
        if layer:
            normalized = _normalize_layer(layer)
            layer_clause = "WHERE mi.layer = ?"
            params.append(normalized)

        rows = self._conn.execute(
            f"""SELECT id, file_path, layer, content, bullet, created_at, updated_at
                FROM memory_index mi
                {layer_clause}
                ORDER BY mi.id DESC
                LIMIT ?""",
            params + [limit],
        ).fetchall()

        return [{
            "id": str(r[0]),
            "file_path": r[1],
            "layer": r[2],
            "content": r[3],
            "bullet": r[4],
            "created_at": r[5],
            "updated_at": r[6],
        } for r in rows]

    def delete(self, record_id: str) -> bool:
        """从索引中删除（不删除 .md 文件内容）。"""
        cur = self._conn.execute("DELETE FROM memory_index WHERE id = ?", (record_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def reindex(self) -> int:
        """全量重建索引：扫描所有 .md 文件。"""
        self._conn.execute("DELETE FROM memory_index")
        count = 0
        for md_file in self.memory_dir.rglob("*.md"):
            if md_file.name == ".index.db":
                continue
            content = md_file.read_text(encoding="utf-8")
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("- ") and "`[" in line:
                    # 解析 bullet: "- content  `[source]`"
                    bullet_text = line[2:]
                    if "`[" in bullet_text:
                        bullet_text = bullet_text[:bullet_text.index("`[")].strip()
                    layer = _infer_layer(md_file, self.memory_dir)
                    mtime = int(md_file.stat().st_mtime)
                    text_hash = hashlib.sha256(line.encode()).hexdigest()[:16]
                    rel_path = str(md_file.relative_to(self.memory_dir))
                    now = datetime.now().isoformat()
                    self._conn.execute(
                        """INSERT INTO memory_index
                           (file_path, layer, content, bullet, mtime, hash, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (rel_path, layer, bullet_text, line, mtime, text_hash, now, now),
                    )
                    # 同步 FTS5（jieba 分词）
                    rowid = self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    seg = _segment(bullet_text)
                    self._conn.execute(
                        "INSERT INTO memory_fts(rowid, content_jieba, content_raw) VALUES (?, ?, ?)",
                        (rowid, seg, bullet_text),
                    )
                    count += 1
        self._conn.commit()
        return count


# ── Helpers ─────────────────────────────────────────────

_FILE_HEADERS = {
    "profile": "用户档案",
    "facts": "知识",
    "projects": "项目上下文",
    "reflections": "经验教训",
}


def _infer_layer(file_path: Path, memory_dir: Path) -> str:
    """从文件路径推断记忆层。"""
    name = file_path.stem
    for layer in VALID_MEMORY_LAYERS:
        if layer == name:
            return layer
    if file_path.parent.name == _DAILY_DIR:
        return "sessions"
    return "facts"


def _fts_escape(query: str) -> str:
    """FTS5 查询转义（保留以备无 jieba 时的回退）。"""
    cleaned = _re.sub(r'[^\w\s]', ' ', query)
    terms = [t for t in cleaned.split() if t]
    if not terms:
        return query
    if len(terms) == 1:
        return terms[0]
    return ' OR '.join(terms)



