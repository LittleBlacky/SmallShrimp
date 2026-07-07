"""Built-in memory provider: SQLite-only with safety mechanisms."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..provider import MemoryProvider, PromptBlock, Layer
from .file_store import MemoryStore
from .hybrid_search import create_embedding_provider, EmbeddingProvider
from .common import (
    MemoryRecord,
    VALID_MEMORY_LAYERS,
    _normalize_layer,
)

_PREFETCH_LAYERS = {"facts", "projects", "reflections"}


class BuiltinProvider(MemoryProvider):
    """SQLite-only memory provider.

    All memories stored in SQLite (FTS5 + optional vector).
    Safety: soft delete, version history, audit log.
    """

    # ── Layer declarations ─────────────────────────────────
    profile = Layer("profile", "用户档案（会话缓存，自动注入 prompt）",
                    searchable=True, inject="session")
    facts = Layer("facts", "事实（按需检索）",
                  searchable=True, inject=None)
    projects = Layer("projects", "项目上下文（按需检索）",
                     searchable=True, inject=None)
    reflections = Layer("reflections", "操作经验（失败模式、成功模式、用户偏好、环境知识，每轮自动召回）",
                        searchable="auto", inject=None)
    constraints = Layer("constraints", "硬性约束（不参与压缩，每轮强制注入）",
                        searchable=True, inject="session")

    def __init__(self, memory_dir: Path, use_vector: bool = False,
                 embedding_config: str | None = None,
                 embedding_provider: EmbeddingProvider | None = None) -> None:
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Resolve embedding provider
        resolved: EmbeddingProvider | None = embedding_provider
        if resolved is None and embedding_config:
            resolved = create_embedding_provider(embedding_config)
        if resolved is None and use_vector:
            resolved = create_embedding_provider("local")

        # SQLite store (sole truth source)
        db_path = memory_dir / ".index.db"
        self._store = MemoryStore(db_path, embedding_provider=resolved)

        # Cache snapshots for prompt injection
        self._snapshot_profile: list[MemoryRecord] | None = None
        self._snapshot_constraints: list[MemoryRecord] | None = None

        # Graph store — shares the same SQLite connection
        from ..graph_store import GraphStore
        self._graph_store = GraphStore(conn=self._store._conn)

        # Pipelines (created by MemoryManager)
        self._retrieval_pipeline = None
        self._write_pipeline = None

    @property
    def name(self) -> str:
        return "builtin"

    def is_available(self) -> bool:
        return self.memory_dir.exists()

    def close(self) -> None:
        if self._graph_store:
            self._graph_store._conn = None  # Detach without closing
        self._store.close()

    @property
    def graph_store(self):
        return self._graph_store

    # ── Lifecycle ────────────────────────────────────────

    def initialize(self, session_id: str) -> None:
        self._snapshot_profile = self._store.list_all(layer="profile", limit=20)
        self._snapshot_constraints = self._store.list_all(layer="constraints", limit=50)

    def shutdown(self) -> None:
        self._snapshot_profile = None
        self._snapshot_constraints = None

    # ── System Prompt ────────────────────────────────────

    def _load_layer(self, layer: str) -> str:
        if layer == "profile":
            if not self._snapshot_profile:
                return ""
            return "\n".join(f"- {r['content']}" for r in self._snapshot_profile)
        if layer == "constraints":
            if not self._snapshot_constraints:
                return ""
            return "\n".join(f"- {r['content']}" for r in self._snapshot_constraints)
        return ""

    def get_prompt_blocks(self) -> list[PromptBlock]:
        blocks: list[PromptBlock] = []
        if self._snapshot_constraints:
            lines = ["## 硬性约束 Hard Constraints\n"]
            for r in self._snapshot_constraints:
                lines.append(f"- {r['content']}")
            blocks.append(PromptBlock("Hard Constraints", "\n".join(lines), cache_tier="session"))
        if self._snapshot_profile:
            lines = ["## User Profile\n"]
            for r in self._snapshot_profile:
                lines.append(f"- {r['content']}")
            blocks.append(PromptBlock("User Profile", "\n".join(lines), cache_tier="session"))
        return blocks

    def system_prompt_block(self) -> str:
        blocks = self.get_prompt_blocks()
        return blocks[0].content if blocks else ""

    def refresh_snapshot(self) -> None:
        self._snapshot_profile = self._store.list_all(layer="profile", limit=20)
        self._snapshot_constraints = self._store.list_all(layer="constraints", limit=50)

    # ── Prefetch ─────────────────────────────────────────

    def prefetch(self, query: str, session_id: str = "") -> list[dict]:
        results: list[dict] = []
        for layer in _PREFETCH_LAYERS:
            results.extend(self._store.search(query, layer=layer, limit=5))
        results.sort(key=lambda r: r.get("fts_rank", 0) if "fts_rank" in r else 0)

        # Graph enrichment
        if self._graph_store:
            try:
                from ..searchers import GraphSearcher
                searcher = GraphSearcher(self._graph_store, max_neighbors=2)
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    entities = self._graph_store.search_entities(query, limit=3)
                    for e in entities:
                        entry = f"[图谱] {e.name} ({e.type})"
                        if e.description:
                            entry += f": {e.description}"
                        results.append({"layer": "graph", "content": entry, "fts_rank": 0.5})
                else:
                    scored = loop.run_until_complete(searcher.search(query, limit=3))
                    for se in scored:
                        results.append({"layer": "graph", "content": se.content, "fts_rank": se.score})
            except Exception:
                pass

        results.sort(key=lambda r: r.get("fts_rank", 0) if "fts_rank" in r else 0)
        return results[:5]

    # ── Sync ─────────────────────────────────────────────

    def sync_turn(self, user_content: str, assistant_content: str,
                  session_id: str = "", messages: list[dict] | None = None) -> None:
        pass  # No daily log — SQLite-only

    # ── CRUD ─────────────────────────────────────────────

    def store(self, layer: str, content: str, **kwargs: Any) -> dict:
        return self._store.store(layer, content, **kwargs)

    def search(self, query: str, layer: str | None = None, **kwargs: Any) -> list[dict]:
        limit = kwargs.get("limit", 10)
        if layer:
            results = self._store.search(query, layer=_normalize_layer(layer), limit=limit)
        else:
            results = self._store.search(query, limit=limit)

        # Touch access_count
        top_ids = [r.get("id") for r in results[:5] if r.get("id")]
        if top_ids:
            try:
                self._store.touch_recall(top_ids)
            except Exception:
                pass
        return results[:limit]

    def list_all(self, layer: str | None = None, **kwargs: Any) -> list[dict]:
        limit = kwargs.get("limit", 50)
        return self._store.list_all(layer=layer, limit=limit)

    def delete(self, record_id: str, layer: str | None = None) -> bool:
        return self._store.delete(record_id)

    # ── Tools ────────────────────────────────────────────

    def get_tools(self) -> list:
        from ....tools.decorators import tool
        store = self._store

        @tool(description="搜索长期记忆。返回匹配的记忆条目。")
        async def recall_memory(query: str, limit: int = 5) -> str:
            records = store.search(query, limit=limit)
            if not records:
                return "未找到相关记忆。"
            lines = []
            for r in records:
                lines.append(f"[{r['id']}] [{r['layer']}] {r['content']}")
            return "\n".join(lines)

        @tool(description="保存用户画像（姓名、长期偏好、沟通语言）。")
        async def remember_profile(content: str) -> str:
            record = store.store("profile", content, importance=10)
            return f"已保存用户画像: {record['content']}"

        @tool(description="保存事实记忆。")
        async def remember_fact(content: str, importance: int = 5) -> str:
            record = store.store("facts", content, importance=importance)
            return f"已保存事实: {record['content']}"

        @tool(description="保存项目上下文。")
        async def remember_project(content: str, importance: int = 6) -> str:
            record = store.store("projects", content, importance=importance)
            return f"已保存项目记忆: {record['content']}"

        @tool(description="保存操作经验（失败模式、成功经验、用户偏好）。")
        async def remember_reflection(content: str, importance: int = 6) -> str:
            record = store.store("reflections", content, importance=importance)
            return f"已保存经验: {record['content']}"

        @tool(description="保存硬性约束（不参与压缩，每轮强制注入）。")
        async def remember_constraint(content: str) -> str:
            record = store.store("constraints", content, importance=10)
            return f"已保存约束: {record['content']}"

        @tool(description="修改已有记忆。先搜索确认目标，再更新内容。")
        async def edit_memory(record_id: str, new_content: str, reason: str = "") -> str:
            old = store.get(record_id)
            if not old:
                return f"未找到 ID={record_id} 的记忆。"
            success = store.update(record_id, new_content, reason=reason)
            if success:
                return f"已修改: '{old['content'][:50]}' → '{new_content[:50]}'"
            return "修改失败。"

        @tool(description="软删除记忆（可恢复）。先搜索确认目标。")
        async def delete_memory(record_id: str, reason: str = "") -> str:
            old = store.get(record_id)
            if not old:
                return f"未找到 ID={record_id} 的记忆。"
            store.delete(record_id, reason=reason)
            return f"已删除: [{old['layer']}] {old['content'][:50]}（软删除，可恢复）"

        @tool(description="恢复被软删除的记忆。")
        async def restore_memory(record_id: str) -> str:
            success = store.restore(record_id)
            if success:
                return f"已恢复 ID={record_id} 的记忆。"
            return "恢复失败（记录不存在或未被删除）。"

        @tool(description="查看记忆变更历史。")
        async def memory_history(record_id: str) -> str:
            history = store.get_history(record_id)
            if not history:
                return f"ID={record_id} 没有变更历史。"
            lines = [f"ID={record_id} 的变更历史："]
            for h in history:
                lines.append(f"  v{h['version']} ({h['changed_at']}) by {h['changed_by']}: {h['content'][:80]}")
            return "\n".join(lines)

        @tool(description="查看审计日志（最近的操作记录）。")
        async def memory_audit(limit: int = 10) -> str:
            entries = store.get_audit(limit=limit)
            if not entries:
                return "审计日志为空。"
            lines = ["最近操作记录："]
            for e in entries:
                lines.append(f"  [{e['action']}] {e['timestamp']} by {e['actor']}: {(e.get('content_after') or e.get('content_before') or '')[:60]}")
            return "\n".join(lines)

        @tool(description="将记忆导出为 Markdown 文本（只读，用于查看）。")
        async def export_memories(layer: str = "") -> str:
            md = store.export_markdown(layer=layer if layer else None)
            if not md:
                return "没有记忆可导出。"
            return md

        @tool(description="搜索知识图谱。返回实体及其关系。")
        async def search_graph(query: str, limit: int = 5) -> str:
            from ..searchers import GraphSearcher
            searcher = GraphSearcher(self.graph_store)
            scored = await searcher.search(query, limit=limit)
            if not scored:
                return f"图谱中未找到与 '{query}' 相关的实体。"
            lines = [f"找到 {len(scored)} 个相关实体："]
            for se in scored:
                lines.append(f"- {se.content}")
            return "\n".join(lines)

        @tool(description="将三元组写入图谱。")
        async def store_triplets(triplets_json: str) -> str:
            import json as _json
            from ..ontology import normalize_entity_type, normalize_predicate
            try:
                items = _json.loads(triplets_json)
            except _json.JSONDecodeError:
                return "JSON 解析失败。"
            if not isinstance(items, list):
                return "请传入 JSON 数组。"
            gs = self.graph_store
            stored = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                subj = item.get("subject", "").strip()
                obj = item.get("object", "").strip()
                if not subj or not obj:
                    continue
                s_type = normalize_entity_type(item.get("subject_type", "other"))
                o_type = normalize_entity_type(item.get("object_type", "other"))
                pred = normalize_predicate(item.get("predicate", "related_to"))
                gs.upsert_entity(subj, s_type)
                gs.upsert_entity(obj, o_type)
                gs.add_relation(subj, pred, obj)
                stored += 1
            return f"已存储 {stored} 条三元组。"

        return [
            recall_memory, remember_profile, remember_fact, remember_project,
            remember_reflection, remember_constraint,
            edit_memory, delete_memory, restore_memory,
            memory_history, memory_audit, export_memories,
            search_graph, store_triplets,
        ]
