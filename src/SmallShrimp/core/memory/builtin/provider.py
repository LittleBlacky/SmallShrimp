"""Built-in memory provider: Markdown 文件真相源 + SQLite FTS5 索引。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ..provider import MemoryProvider, PromptBlock, Layer
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

    # ── 声明式分层 ──────────────────────────────────────
    profile = Layer("profile", "用户档案（会话缓存，自动注入 prompt）",
                    searchable=True, inject="session")
    facts = Layer("facts", "技术事实（按需检索）",
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
        self._snapshot_constraints: list[MemoryRecord] | None = None

        # Graph store — shares MarkdownStore's SQLite connection
        from ..graph_store import GraphStore
        self._graph_store = GraphStore(conn=self._store._conn)

        # Pipelines (created lazily by MemoryManager)
        self._retrieval_pipeline = None
        self._write_pipeline = None

    @property
    def name(self) -> str:
        return "builtin"

    def is_available(self) -> bool:
        return self.memory_dir.exists()

    def close(self) -> None:
        # GraphStore shares the connection, don't double-close
        if self._graph_store:
            self._graph_store._conn = None  # Detach without closing
        self._store.close()

    @property
    def graph_store(self):
        return self._graph_store

    # ── 生命周期 ────────────────────────────────────────

    def initialize(self, session_id: str) -> None:
        """初始化缓存快照。"""
        self._snapshot_profile = self._stores["profile"].list_all()[:20]
        self._snapshot_constraints = self._stores["constraints"].list_all()

    def shutdown(self) -> None:
        self._snapshot_profile = None
        self._snapshot_constraints = None

    # ── System Prompt ───────────────────────────────────

    def _load_layer(self, layer: str) -> str:
        """读取某层的全部内容（用于 get_prompt_blocks 注入）。"""
        if layer == "profile":
            if not self._snapshot_profile:
                return ""
            lines = []
            for r in self._snapshot_profile:
                lines.append(f"- {r['content']}")
            return "\n".join(lines)
        if layer == "constraints":
            if not self._snapshot_constraints:
                return ""
            lines = []
            for r in self._snapshot_constraints:
                lines.append(f"- {r['content']}")
            return "\n".join(lines)
        return ""

    def get_prompt_blocks(self) -> list[PromptBlock]:
        """返回要注入 system prompt 的内容块。constraints 优先级最高。"""
        blocks: list[PromptBlock] = []

        # Constraints — 最高优先级，始终注入
        if self._snapshot_constraints:
            lines = [f"## 硬性约束 Hard Constraints\n"]
            for r in self._snapshot_constraints:
                lines.append(f"- {r['content']}")
            blocks.append(PromptBlock("Hard Constraints", "\n".join(lines), cache_tier="session"))

        # Profile
        if self._snapshot_profile:
            lines = [f"## User Profile\n"]
            for r in self._snapshot_profile:
                lines.append(f"- {r['content']}")
            blocks.append(PromptBlock("User Profile", "\n".join(lines), cache_tier="session"))

        return blocks

    def system_prompt_block(self) -> str:
        """（旧接口）返回缓存的 Profile 快照。"""
        blocks = self.get_prompt_blocks()
        return blocks[0].content if blocks else ""

    def refresh_snapshot(self) -> None:
        """重新从索引加载快照。"""
        self._snapshot_profile = self._stores["profile"].list_all()[:20]
        self._snapshot_constraints = self._stores["constraints"].list_all()

    # ── 前置召回 ────────────────────────────────────────

    def prefetch(self, query: str, session_id: str = "") -> list[dict]:
        """按需召回 facts/projects/reflections + 知识图谱。"""
        results: list[dict] = []
        for layer in _PREFETCH_LAYERS:
            results.extend(self._stores[layer].search(query, limit=5))
        results.sort(key=lambda r: r.get("fts_rank", 0) if "fts_rank" in r else 0)

        # Graph enrichment via GraphSearcher
        if self._graph_store:
            try:
                from ..searchers import GraphSearcher
                searcher = GraphSearcher(self._graph_store, max_neighbors=2)
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Can't await in sync context — use fallback
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
                pass  # Graph is optional

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
            results = self._stores[normalized].search(query, limit=limit)
        else:
            results: list[dict] = []
            for l in VALID_MEMORY_LAYERS:
                results.extend(self._stores[l].search(query, limit=limit))
            results.sort(key=lambda r: r.get("fts_rank", 0) if "fts_rank" in r else 0)
            results = results[:limit]

        # 回写 access_count（仅回写 top-5）
        top_ids = [r.get("id") for r in results[:5] if r.get("id")]
        if top_ids:
            try:
                self._store.touch_recall(top_ids)
            except Exception:
                pass

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

    # ── 工具注册 ────────────────────────────────────────

    def get_tools(self) -> list:
        """返回 BuiltinProvider 提供的一组 Tool 对象。"""
        from ....tools.decorators import tool
        store = self._store

        @tool(description="搜索长期记忆。默认只查 facts/projects/reflections，不查用户画像。")
        async def recall_memory(query: str, _session_state=None) -> str:
            records = store.search(query, limit=5)
            if not records:
                return "未找到相关任务记忆。"
            return "\n".join(f"- [{r['layer']}] {r['content']}" for r in records)

        @tool(description="保存稳定用户画像，例如姓名、长期偏好、沟通语言、用户明确纠正。不要保存临时任务状态。")
        async def remember_profile(content: str) -> str:
            record = store.store("profile", content)
            return f"已保存用户画像: {record['content']}"

        @tool(description="保存普通事实记忆，用于跨会话召回；不进入用户画像 prompt。")
        async def remember_fact(content: str, importance: int = 5) -> str:
            record = store.store("facts", content, importance=importance)
            return f"已保存事实记忆: {record['content']}"

        @tool(description="保存当前项目/仓库相关记忆，例如路径、命令、技术栈、约定。")
        async def remember_project(content: str, importance: int = 6) -> str:
            record = store.store("projects", content, importance=importance)
            return f"已保存项目记忆: {record['content']}"

        @tool(description="保存 agent 反思记忆，例如失败模式、用户纠正后的经验、工具使用教训。")
        async def remember_reflection(content: str, importance: int = 6) -> str:
            record = store.store("reflections", content, importance=importance)
            return f"已保存反思记忆: {record['content']}"

        @tool(description="保存硬性约束（预算、禁止项、必须条件）。约束不参与压缩，每轮强制注入上下文。用于保存'不含坚果''预算不超过500'等关键限制。")
        async def remember_constraint(content: str) -> str:
            record = store.store("constraints", content, importance=10)
            return f"已保存硬性约束: {record['content']}"

        @tool(description="扫描并合并 facts/projects/reflections 中的相似记录；不会合并用户画像。")
        async def consolidate_memories(threshold: float = 0.8) -> str:
            count = self.consolidate(threshold=threshold)
            return f"合并了 {count} 对相似记忆。" if count else "没有找到可合并的记忆。"

        @tool(description="搜索知识图谱。返回实体及其关系。用于查找人物、概念、技术之间的关联。")
        async def search_graph(query: str, limit: int = 5) -> str:
            from ..searchers import GraphSearcher
            searcher = GraphSearcher(self.graph_store)
            scored = await searcher.search(query, limit=limit)
            if not scored:
                return f"知识图谱中未找到与 '{query}' 相关的实体。"
            lines = [f"找到 {len(scored)} 个相关实体："]
            for se in scored:
                lines.append(f"- {se.content}")
            return "\n".join(lines)

        @tool(description="将知识三元组写入图谱。输入 JSON 数组，每个元素含 subject/subject_type/predicate/object/object_type。")
        async def store_triplets(triplets_json: str) -> str:
            import json as _json
            from ..ontology import normalize_entity_type, normalize_predicate
            try:
                items = _json.loads(triplets_json)
            except _json.JSONDecodeError:
                return "JSON 解析失败，请传入有效的 JSON 数组。"
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
            return f"已存储 {stored} 条三元组到知识图谱。"

        return [recall_memory, remember_profile, remember_fact, remember_project, remember_reflection, remember_constraint, consolidate_memories, search_graph, store_triplets]
