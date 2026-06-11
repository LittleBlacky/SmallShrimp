"""Built-in memory provider: Markdown 文件真相源 + SQLite FTS5 索引。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ..provider import MemoryProvider
from .file_store import MarkdownStore
from .hybrid_search import create_embedding_provider, EmbeddingProvider
from .common import (
    MemoryLayer,
    MemoryRecord,
    VALID_MEMORY_LAYERS,
    _normalize_layer,
)

_PROFILE_LAYERS = {"profile"}
_PREFETCH_LAYERS = {"facts", "projects", "reflections"}


class _MarkerLayerAdapter:
    """将 MarkdownStore 包装为 per-layer 接口。"""

    def __init__(self, store: MarkdownStore, layer: MemoryLayer):
        self._store = store
        self._layer = layer

    def store(self, content: str, **kwargs: Any) -> MemoryRecord:
        return self._store.store(self._layer, content, **kwargs)

    def search(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        return self._store.search(query, layer=self._layer, limit=limit)

    def list_all(self) -> list[MemoryRecord]:
        return self._store.list_all(layer=self._layer)

    def delete(self, record_id: str) -> bool:
        return self._store.delete(record_id)


class BuiltinProvider(MemoryProvider):
    """内置存储后端：Markdown 文件真相源 + SQLite FTS5 索引。

    所有记忆以 .md 文件存储在 memory_dir 中，用户可直接编辑。
    SQLite 仅为检索加速，索引丢失不影响记忆。
    """

    def __init__(self, memory_dir: Path, use_vector: bool = False,
                 embedding_config: str | None = None,
                 embedding_provider: EmbeddingProvider | None = None) -> None:
        """初始化内置记忆提供者。

        Args:
            memory_dir: 记忆存储目录
            use_vector: 是否启用向量检索（True 时自动使用本地 embedding）
            embedding_config: 嵌入配置字符串
                - None / ""   → 不启用
                - "local"     → 本地 sentence-transformers
                - "local:模型名"
                - "api://模型名"
            embedding_provider: 直接传入 EmbeddingProvider 实例（优先级最高）
        """
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # 决定 embedding provider
        resolved: EmbeddingProvider | None = embedding_provider
        if resolved is None and embedding_config:
            resolved = create_embedding_provider(embedding_config)
        if resolved is None and use_vector:
            resolved = create_embedding_provider("local")

        self._store = MarkdownStore(memory_dir, embedding_provider=resolved)
        self._stores = {
            layer: _MarkerLayerAdapter(self._store, layer)
            for layer in VALID_MEMORY_LAYERS
        }
        self._snapshot_profile: list[MemoryRecord] | None = None

    @property
    def name(self) -> str:
        return "builtin"

    def is_available(self) -> bool:
        return self.memory_dir.exists()

    def close(self) -> None:
        self._store.close()

    # ── 生命周期 ────────────────────────────────────────

    def initialize(self, session_id: str) -> None:
        """初始化缓存快照。"""
        self._snapshot_profile = self._stores["profile"].list_all()[:20]

    def shutdown(self) -> None:
        self._snapshot_profile = None

    # ── System Prompt ───────────────────────────────────

    def system_prompt_block(self) -> str:
        """返回缓存的 Profile 快照。"""
        if not self._snapshot_profile:
            return ""
        lines = ["## User Profile\n"]
        for r in self._snapshot_profile:
            lines.append(f"- {r['content']}")
        return "\n".join(lines)

    def refresh_snapshot(self) -> None:
        """重新从索引加载快照。"""
        self._snapshot_profile = self._stores["profile"].list_all()[:20]

    # ── 前置召回 ────────────────────────────────────────

    def prefetch(self, query: str, session_id: str = "") -> list[dict]:
        """按需召回 facts/projects/reflections。"""
        results: list[dict] = []
        for layer in _PREFETCH_LAYERS:
            results.extend(self._stores[layer].search(query, limit=5))
        results.sort(key=lambda r: r.get("fts_rank", 0) if "fts_rank" in r else 0)
        return results[:5]

    # ── 后置同步 ────────────────────────────────────────

    def sync_turn(self, user_content: str, assistant_content: str,
                  session_id: str = "", messages: list[dict] | None = None) -> None:
        """写入每日日志。"""
        summary = f"User: {user_content[:200]}\nAssistant: {assistant_content[:200]}"
        self._store.store_daily(summary=summary)

    # ── 存储接口 ────────────────────────────────────────

    def store(self, layer: str, content: str, **kwargs: Any) -> dict:
        normalized = _normalize_layer(layer)
        return self._stores[normalized].store(content, **kwargs)

    def search(self, query: str, layer: str | None = None, **kwargs: Any) -> list[dict]:
        limit = kwargs.get("limit", 10)
        use_hrr = kwargs.get("use_hrr", False)
        if layer:
            normalized = _normalize_layer(layer)
            return self._stores[normalized].search(query, limit=limit)
        results: list[dict] = []
        for l in VALID_MEMORY_LAYERS:
            results.extend(self._stores[l].search(query, limit=limit))
        results.sort(key=lambda r: r.get("fts_rank", 0) if "fts_rank" in r else 0)
        return results[:limit]

    def list_all(self, layer: str | None = None, **kwargs: Any) -> list[dict]:
        limit = kwargs.get("limit", 50)
        if layer:
            normalized = _normalize_layer(layer)
            return self._stores[normalized].list_all()[:limit]
        records: list[dict] = []
        for l in VALID_MEMORY_LAYERS:
            records.extend(self._stores[l].list_all())
        records.sort(key=lambda r: (r.get("layer", ""), r.get("updated_at", "")), reverse=True)
        return records[:limit]

    def delete(self, record_id: str, layer: str | None = None) -> bool:
        layers = [layer] if layer else list(VALID_MEMORY_LAYERS)
        for l in layers:
            if self._stores[l].delete(record_id):
                return True
        return False

    def reindex(self) -> int:
        """全量重建索引。"""
        return self._store.reindex()
