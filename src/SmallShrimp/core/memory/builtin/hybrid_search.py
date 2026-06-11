"""FTS5 + 向量混合检索，带 MMR 重排序和时间衰减。

Embedding 支持多种后端：
  - "local"    → sentence-transformers (all-MiniLM-L6-v2), 384d
  - "api://模型名" → OpenAI 兼容 API (如 api://text-embedding-3-small)
  - None       → 不启用向量检索
"""
from __future__ import annotations

import math
import os
import sqlite3
import struct
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from .common import _normalize_layer

_HAS_SQLITE_VEC = False
try:
    import sqlite_vec
    _HAS_SQLITE_VEC = True
except ImportError:
    pass


# ── Embedding Provider ──────────────────────────────────

class EmbeddingProvider(ABC):
    """Embedding 计算接口。"""

    @abstractmethod
    def get_dimension(self) -> int: ...

    @abstractmethod
    def encode(self, text: str) -> list[float]: ...

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]


class _LocalEmbeddingProvider(EmbeddingProvider):
    """本地 sentence-transformers 模型。"""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self._dim = self._model.get_sentence_embedding_dimension()

    def get_dimension(self) -> int:
        return self._dim

    def encode(self, text: str) -> list[float]:
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()


class _ApiEmbeddingProvider(EmbeddingProvider):
    """OpenAI 兼容 API。"""

    def __init__(self, model: str = "text-embedding-3-small"):
        self._model = model
        self._dim = 1536 if "3-small" in model else (3072 if "3-large" in model else 768)
        # 从环境变量读取配置
        self._api_key = os.environ.get("OPENAI_API_KEY", "")
        self._base_url = os.environ.get("OPENAI_BASE_URL", "")

    def get_dimension(self) -> int:
        return self._dim

    def encode(self, text: str) -> list[float]:
        from openai import OpenAI
        client = OpenAI(api_key=self._api_key, base_url=self._base_url or None)
        resp = client.embeddings.create(model=self._model, input=text)
        return resp.data[0].embedding

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI
        client = OpenAI(api_key=self._api_key, base_url=self._base_url or None)
        resp = client.embeddings.create(model=self._model, input=texts)
        return [r.embedding for r in resp.data]


def create_embedding_provider(config: str | None = None) -> EmbeddingProvider | None:
    """创建 embedding provider。

    Args:
        config: None → 不启用
                "local" → 本地 sentence-transformers
                "local:模型名" → 指定本地模型
                "api://模型名" → OpenAI 兼容 API
    """
    if config is None or config == "":
        return None

    if config == "local" or config.startswith("local:"):
        model = config.split(":", 1)[1] if ":" in config else "all-MiniLM-L6-v2"
        try:
            return _LocalEmbeddingProvider(model)
        except ImportError:
            print("[memory] sentence-transformers 未安装，无法使用本地 embedding")
            return None

    if config.startswith("api://"):
        model = config[len("api://"):] or "text-embedding-3-small"
        try:
            return _ApiEmbeddingProvider(model)
        except ImportError:
            print("[memory] openai 未安装，无法使用 API embedding")
            return None

    return None


# ── 配置 ────────────────────────────────────────────────

FTS_WEIGHT = 0.3          # FTS5 分数权重
VEC_WEIGHT = 0.5          # 向量分数权重
TIME_WEIGHT = 0.2         # 时间衰减权重
TIME_HALF_LIFE_DAYS = 30  # 半衰期（天）
MMR_LAMBDA = 0.7          # MMR 相关性 vs 多样性
TOP_K_CANDIDATES = 20     # 候选集大小


# ── vec0 表 ─────────────────────────────────────────────

def _vec_schema(dim: int) -> str:
    return f"""
CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec
USING vec0(
    embedding float[{dim}] distance_metric=cosine
);
"""


def setup_vector_table(conn: sqlite3.Connection, embedding_provider: EmbeddingProvider | None = None,
                       dim: int = 384) -> None:
    """创建 vec0 虚拟表。"""
    if not _HAS_SQLITE_VEC:
        return
    actual_dim = embedding_provider.get_dimension() if embedding_provider else dim
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.execute(_vec_schema(actual_dim))


def insert_vector(conn: sqlite3.Connection, rowid: int, text: str,
                  embedding_provider: EmbeddingProvider | None = None) -> bool:
    """计算 embedding 并插入 vec0 表。"""
    if embedding_provider is None:
        return False
    vec = embedding_provider.encode(text)
    # sqlite-vec 需要 bytes（float32 序列化）
    vec_bytes = struct.pack(f"{len(vec)}f", *vec)
    conn.execute(
        "INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)",
        (rowid, vec_bytes),
    )
    return True


# ── 时间衰减 ──────────────────────────────────────────

def _time_decay(created_at: str, half_life_days: int = TIME_HALF_LIFE_DAYS) -> float:
    """时间衰减分数：新内容得分高。"""
    try:
        created = datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        return 0.5
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days_elapsed = (now - created).days
    return 0.5 ** (days_elapsed / half_life_days)


# ── MMR 重排序 ─────────────────────────────────────────

def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-10)


def mmr_rerank(candidates: list[dict], query_vec: list[float] | None,
               lambda_: float = MMR_LAMBDA) -> list[dict]:
    """MMR 重排序，平衡相关性与多样性。"""
    if not candidates:
        return candidates
    selected: list[dict] = []
    remaining = list(candidates)

    while remaining and len(selected) < len(candidates):
        best_score = -float("inf")
        best_idx = 0
        for i, cand in enumerate(remaining):
            rel = cand.get("final_score", 0)
            if query_vec and cand.get("embedding"):
                sim = _cosine_sim(query_vec, cand["embedding"])
                mmr = lambda_ * rel - (1 - lambda_) * max(
                    (_cosine_sim(cand["embedding"], s.get("embedding", [])) for s in selected),
                    default=0,
                )
            else:
                mmr = rel
            if mmr > best_score:
                best_score = mmr
                best_idx = i
        selected.append(remaining.pop(best_idx))
    return selected


# ── 混合检索 ───────────────────────────────────────────

def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    layer: str | None = None,
    limit: int = 5,
    fts_query: str = "",
    use_vector: bool = True,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[dict]:
    """FTS5 + 向量混合检索，带 MMR 和时间衰减。

    Args:
        conn: SQLite 连接（已加载 sqlite-vec 扩展）
        query: 原始查询（用于 embedding）
        layer: 记忆层过滤
        limit: 返回条数
        fts_query: FTS5 查询字符串（jieba OR 格式）
        use_vector: 是否启用向量检索
        embedding_provider: Embedding 计算器（为 None 时跳过向量检索）

    Returns:
        排序后的记忆记录列表，含 final_score 字段
    """
    all_results: dict[int, dict] = {}
    query_vec = embedding_provider.encode(query) if (use_vector and embedding_provider) else None

    # ── FTS5 检索 ──
    if fts_query:
        params: list[Any] = [fts_query]
        layer_clause = ""
        if layer:
            layer_clause = "AND mi.layer = ?"
            params.append(_normalize_layer(layer))
        params.append(TOP_K_CANDIDATES)

        rows = conn.execute(
            f"""SELECT mi.id, mi.file_path, mi.layer, mi.content, mi.created_at
                FROM memory_fts fts
                JOIN memory_index mi ON mi.id = fts.rowid
                WHERE memory_fts MATCH ?
                  {layer_clause}
                ORDER BY fts.rank
                LIMIT ?""",
            params,
        ).fetchall()

        for r in rows:
            all_results[r[0]] = {
                "id": r[0], "file_path": r[1], "layer": r[2],
                "content": r[3], "created_at": r[4],
                "fts_score": r.rank if hasattr(r, "rank") else 0,
            }

    # ── 向量检索 ──
    if use_vector and query_vec and _HAS_SQLITE_VEC:
        try:
            vec_bytes = struct.pack(f"{len(query_vec)}f", *query_vec)
            vec_rows = conn.execute(
                "SELECT rowid, distance FROM memory_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (vec_bytes, TOP_K_CANDIDATES),
            ).fetchall()

            for rowid, distance in vec_rows:
                if rowid not in all_results:
                    # 从 memory_index 获取详情
                    info = conn.execute(
                        "SELECT id, file_path, layer, content, created_at FROM memory_index WHERE id = ?",
                        (rowid,),
                    ).fetchone()
                    if info:
                        all_results[rowid] = {
                            "id": info[0], "file_path": info[1], "layer": info[2],
                            "content": info[3], "created_at": info[4],
                            "fts_score": 0,
                        }
                if rowid in all_results:
                    all_results[rowid]["vec_score"] = 1.0 - distance  # cosine → similarity
                    all_results[rowid]["embedding"] = query_vec  # 用于 MMR 简化
        except Exception:
            pass  # vec0 可能无数据

    # ── 分数融合 ──
    for record in all_results.values():
        fts = record.get("fts_score", 0)
        # FTS5 rank 是负值（越小越好），转成正分
        fts_norm = 1.0 / (1.0 + abs(fts)) if fts != 0 else 0
        vec = record.get("vec_score", 0)
        time_decay = _time_decay(record.get("created_at", ""))
        record["final_score"] = (
            fts_norm * FTS_WEIGHT +
            vec * VEC_WEIGHT +
            time_decay * TIME_WEIGHT
        )

    # ── MMR 重排序 ──
    candidates = list(all_results.values())
    reranked = mmr_rerank(candidates, query_vec)
    reranked.sort(key=lambda r: r.get("final_score", 0), reverse=True)

    return reranked[:limit]
