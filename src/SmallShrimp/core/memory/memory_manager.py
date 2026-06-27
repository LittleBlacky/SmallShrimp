from __future__ import annotations
"""Layered memory manager for persistent profile, facts, reflections, and sessions.

MemoryManager orchestrates MemoryProviders. 工具层通过 MemoryManager 的公开 API 读写记忆，
不直接调 Provider。
"""
from pathlib import Path
from typing import Any, Iterable

from .provider import MemoryProvider, PromptBlock
from .confidence import (
    SignalDetector,
    ConfidenceGate,
    StagingArea,
    THRESHOLD_DIRECT,
    THRESHOLD_STAGING,
)


class MemoryManager:
    """记忆管理器 — MemoryProvider 的纯代理层 + 置信度管线。

    工具层通过此类的公开方法操作记忆，不直接调 Provider。
    store() 走置信度管线：SignalDetector → ConfidenceGate → StagingArea/Provider。
    """

    def __init__(self, provider_or_dir: MemoryProvider | str | Path):
        """初始化记忆管理器。

        Args:
            provider_or_dir: MemoryProvider 实例，或路径字符串（向后兼容，自动创建 BuiltinProvider）
        """
        if isinstance(provider_or_dir, (str, Path)):
            from .builtin.provider import BuiltinProvider
            self._provider: MemoryProvider = BuiltinProvider(memory_dir=Path(provider_or_dir))
        else:
            self._provider = provider_or_dir

        # 置信度管线
        memory_dir = self._resolve_memory_dir()
        self._signal_detector = SignalDetector()
        self._confidence_gate = ConfidenceGate()
        db_path = (memory_dir / ".staging.db") if memory_dir else ":memory:"
        self._staging = StagingArea(
            db_path=db_path,
            promote_callback=self._promote_from_staging,
        )

        # 统一管线
        self._retrieval_pipeline = None
        self._write_pipeline = None
        self._init_pipelines()

    def _resolve_memory_dir(self) -> Path | None:
        """尝试解析记忆目录路径。"""
        if hasattr(self._provider, "memory_dir"):
            return self._provider.memory_dir
        return None

    def _init_pipelines(self) -> None:
        """Initialize retrieval and write pipelines if provider supports them."""
        from .builtin.provider import BuiltinProvider
        if not isinstance(self._provider, BuiltinProvider):
            return

        from .pipeline import RetrievalPipeline, WritePipeline, RRFRanker, BudgetController
        from .searchers import FTS5Searcher, GraphSearcher
        from .indexers import GraphIndexer

        # RetrievalPipeline: FTS5 + Graph
        searchers = [FTS5Searcher(self._provider._store)]
        if self._provider._graph_store:
            searchers.append(GraphSearcher(self._provider._graph_store))
        self._retrieval_pipeline = RetrievalPipeline(
            searchers=searchers,
            ranker=RRFRanker(),
            budget=BudgetController(),
        )

        # WritePipeline: Graph indexing (LLM caller injected later)
        if self._provider._graph_store:
            self._write_pipeline = WritePipeline(
                indexers=[GraphIndexer(self._provider._graph_store)]
            )

    def set_llm_caller(self, llm_caller) -> None:
        """Inject LLM caller for graph indexing (triplet extraction)."""
        if self._write_pipeline:
            from .indexers import GraphIndexer
            graph = self._provider._graph_store if hasattr(self._provider, '_graph_store') else None
            if graph:
                self._write_pipeline = WritePipeline(
                    indexers=[GraphIndexer(graph, llm_caller=llm_caller)]
                )

    @property
    def retrieval_pipeline(self):
        """Get the retrieval pipeline (for advanced usage)."""
        return self._retrieval_pipeline

    @property
    def write_pipeline(self):
        """Get the write pipeline (for advanced usage)."""
        return self._write_pipeline

    def _promote_from_staging(self, content_hash: str, content: str,
                              layer: str, **kwargs: Any) -> None:
        """Staging 提升回调：写入正式 Provider。"""
        # 提升时置信度至少提升到 staging 上限
        kwargs.setdefault("confidence", THRESHOLD_DIRECT)
        try:
            self._provider.store(layer, content, **kwargs)
        except Exception:
            pass  # 提升失败不影响后续

    @property
    def provider(self) -> MemoryProvider:
        """获取底层 Provider（供高级用法和工具注册）。"""
        return self._provider

    def close(self) -> None:
        """关闭 Provider 后端连接。"""
        self._staging.close()
        self._provider.close()

    def __del__(self) -> None:
        try:
            self._provider.close()
        except Exception:
            pass

    def initialize(self, session_id: str) -> None:
        self._provider.initialize(session_id)

    def system_prompt_block(self) -> str:
        return self._provider.system_prompt_block()

    def get_prompt_blocks(self) -> list[PromptBlock]:
        return self._provider.get_prompt_blocks()

    def prefetch(self, query: str, session_id: str = "") -> list[dict]:
        return self._provider.prefetch(query, session_id=session_id)

    def sync_turn(self, user_content: str, assistant_content: str,
                  session_id: str = "", messages: list | None = None) -> None:
        self._provider.sync_turn(user_content, assistant_content, session_id, messages)

    # ── 通用读写 API ────────────────────────────────────

    def store(self, layer: str, content: str, **kwargs: Any) -> dict:
        """写入记忆 — 走置信度管线。

        流程：
        1. SignalDetector 提取信号
        2. ConfidenceGate 裁决（write / stage / discard）
        3. 按裁决路由

        Args:
            layer: 目标记忆层
            content: 记忆内容
            **kwargs: 额外参数，支持:
                source: 来源标记（"failure_learner"、"remember_tool" 等）
                user_msg: 用户上一条消息（用于纠正检测）
                has_failure: 本轮是否有工具失败
                existing_records: 已有记录列表（用于重复检测）
                importance, entity_type, source_turn_id, source_text 等存储参数

        Returns:
            {"action": "write"|"staged"|"discard",
             "layer": str, "content": str, "confidence": float,
             "detail": ...}  # write 时包含 provider.store() 返回值
        """
        # 跳过空内容
        content = content.strip()
        if not content:
            return {"action": "discard", "reason": "empty_content", "layer": layer}

        # 1. 检测信号
        signals = self._signal_detector.detect_all(content, **kwargs)

        # 2. 裁决
        decision = self._confidence_gate.judge(layer, content, signals)

        # 3. 路由
        if decision.action == "discard":
            return {
                "action": "discard",
                "layer": layer,
                "content": content,
                "confidence": decision.confidence,
                "signals": decision.signals,
            }

        if decision.action == "stage":
            result = self._staging.stage(
                content, decision.target_layer, decision.confidence, **kwargs
            )
            return {
                "action": result["action"],  # "staged" | "bumped" | "promoted"
                "layer": decision.target_layer,
                "content": content,
                "confidence": decision.confidence,
                "signals": decision.signals,
                "staging_count": result.get("count", 1),
            }

        # action == "write" — 直接写入 Provider
        kwargs.setdefault("confidence", decision.confidence)
        record = self._provider.store(decision.target_layer, content, **kwargs)

        # Trigger graph indexing (background, non-blocking)
        if self._write_pipeline and record:
            record_id = record.get("id", "") if isinstance(record, dict) else ""
            self._write_pipeline.post_store_bg(decision.target_layer, content, str(record_id))

        return {
            "action": "write",
            "layer": decision.target_layer,
            "content": content,
            "confidence": decision.confidence,
            "signals": decision.signals,
            "detail": record,
        }

    def recall(self, query: str, limit: int = 5, **kwargs) -> list[dict]:
        return self._provider.search(query, limit=limit, **kwargs)

    async def recall_unified(self, query: str, limit: int = 10) -> str:
        """Unified retrieval via RetrievalPipeline (FTS5 + Graph + RRF).

        Returns formatted context string ready for LLM consumption.
        Falls back to basic recall() if pipeline not available.
        """
        if self._retrieval_pipeline:
            return await self._retrieval_pipeline.retrieve(query, limit=limit)
        # Fallback: basic FTS5 recall
        records = self.recall(query, limit=limit)
        if not records:
            return ""
        return "\n".join(f"- [{r.get('layer', '')}] {r.get('content', '')}" for r in records)

    async def ingest(
        self,
        source_text: str,
        llm_caller=None,
        store_entries: bool = True,
    ) -> dict:
        """Ingest a document: two-step CoT analysis → store entries + graph.

        Args:
            source_text: Document to ingest
            llm_caller: Object with async .chat(messages) -> dict
            store_entries: Whether to auto-store generated memory entries

        Returns:
            {"entries_stored": int, "entities_created": int, "relations_created": int}
        """
        from .ingest import ingest_document

        graph = self._provider._graph_store if hasattr(self._provider, '_graph_store') else None
        result = await ingest_document(
            source_text, llm_caller, graph=graph,
        )

        entries_stored = 0
        if store_entries and result.memory_entries:
            for entry in result.memory_entries:
                store_result = self.store("facts", entry, source="ingest")
                if store_result.get("action") == "write":
                    entries_stored += 1

        return {
            "entries_stored": entries_stored,
            "entities_created": result.entities_created,
            "relations_created": result.relations_created,
        }

    def list_all(self, **kwargs) -> list[dict]:
        return self._provider.list_all(**kwargs)

    def delete(self, record_id: str) -> bool:
        return self._provider.delete(record_id)

    def consolidate(self, **kwargs) -> int:
        return self._provider.consolidate(**kwargs)

    # ── 置信度管线查询 ──────────────────────────────────

    @property
    def staging(self) -> StagingArea:
        """获取 StagingArea 实例（用于查询暂存区状态）。"""
        return self._staging
