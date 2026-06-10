"""Built-in SQLite-backed memory provider implementing MemoryProvider ABC."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..provider import MemoryProvider
from .store import SQLiteBackend
from .common import (
    MemoryLayer,
    MemoryRecord,
    VALID_MEMORY_LAYERS,
    _normalize_layer,
)

_PROFILE_LAYERS = {"profile"}
_PREFETCH_LAYERS = {"facts", "projects", "reflections"}


class _SQLiteLayerAdapter:
    """将 SQLiteBackend 包装为 per-layer 接口。"""

    def __init__(self, backend: SQLiteBackend, layer: MemoryLayer):
        self._backend = backend
        self._layer = layer

    def store(self, content: str, **kwargs: Any) -> MemoryRecord:
        return self._backend.store(self._layer, content, **kwargs)

    def search(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        return self._backend.search(query, layer=self._layer, limit=limit)

    def list_all(self) -> list[MemoryRecord]:
        return self._backend.list_all(layer=self._layer)

    def delete(self, record_id: str) -> bool:
        return self._backend.delete(record_id)

    def consolidate(self, threshold: float = 0.8) -> int:
        return self._backend.consolidate(threshold=threshold, layer=self._layer)


class BuiltinProvider(MemoryProvider):
    """内置 SQLite 存储后端。

    用 SQLite 管理 5 层记忆，支持快照缓存和按需召回。
    外部第三方 Provider（如 Mem0/Honcho）可通过 MemoryProvider ABC 接入。
    """

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._db = SQLiteBackend(memory_dir / "memory.db")
        self._stores = {
            layer: _SQLiteLayerAdapter(self._db, layer)
            for layer in VALID_MEMORY_LAYERS
        }
        self._snapshot_profile: list[MemoryRecord] | None = None

    @property
    def name(self) -> str:
        return "builtin"

    def is_available(self) -> bool:
        return self.memory_dir.exists()

    def close(self) -> None:
        self._db.close()

    # ── 生命周期 ────────────────────────────────────────

    def initialize(self, session_id: str) -> None:
        """初始化会话级缓存快照。"""
        self._snapshot_profile = self._stores["profile"].list_all()[:20]

    def shutdown(self) -> None:
        self._snapshot_profile = None

    # ── System Prompt ───────────────────────────────────

    def system_prompt_block(self) -> str:
        """返回缓存的 Profile 快照，不查库。"""
        if not self._snapshot_profile:
            return ""
        lines = ["## User Profile\n"]
        for r in self._snapshot_profile:
            lines.append(f"- {r['content']}")
        return "\n".join(lines)

    def refresh_snapshot(self) -> None:
        """重新从数据库加载快照（跨会话时调用）。"""
        self._snapshot_profile = self._stores["profile"].list_all()[:20]

    # ── 前置召回 ────────────────────────────────────────

    def prefetch(self, query: str, session_id: str = "") -> list[dict]:
        """按需召回 facts/projects/reflections 三层（当前简单实现）。"""
        results: list[dict] = []
        for layer in _PREFETCH_LAYERS:
            results.extend(self._stores[layer].search(query, limit=5))
        results.sort(key=lambda r: r.get("importance", 0), reverse=True)
        return results[:5]

    # ── 后置同步 ────────────────────────────────────────

    def sync_turn(self, user_content: str, assistant_content: str,
                  session_id: str = "", messages: list[dict] | None = None) -> None:
        """持久化本轮对话到 sessions 层。"""
        summary = f"User: {user_content[:200]}\nAssistant: {assistant_content[:200]}"
        self._stores["sessions"].store(
            summary,
            source="auto",
            importance=3,
        )

    # ── 存储接口 ────────────────────────────────────────

    def store(self, layer: str, content: str, **kwargs: Any) -> dict:
        normalized = _normalize_layer(layer)
        return self._stores[normalized].store(content, **kwargs)

    def search(self, query: str, layer: str | None = None, **kwargs: Any) -> list[dict]:
        limit = kwargs.get("limit", 10)
        if layer:
            normalized = _normalize_layer(layer)
            return self._stores[normalized].search(query, limit=limit)
        results: list[dict] = []
        for l in _PREFETCH_LAYERS:
            results.extend(self._stores[l].search(query, limit=limit))
        results.sort(key=lambda r: r.get("importance", 0), reverse=True)
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

    def consolidate(self, layers: Iterable[str] | None = None, threshold: float = 0.8) -> int:
        selected = [_normalize_layer(l) for l in layers] if layers else ["facts", "projects", "reflections", "sessions"]
        return sum(self._stores[l].consolidate(threshold=threshold) for l in selected)


# ── Re-export from common ──
from .common import (  # noqa: E402, F401
    _normalize_layer,
    _normalize_record,
    _new_memory_id,
    _clamp_int,
    _clamp_float,
    _memory_quality_boost,
    _rank_memory,
    _word_terms,
    _char_ngrams,
    _is_duplicate_memory,
    _has_conflicting_number_suffix,
)
