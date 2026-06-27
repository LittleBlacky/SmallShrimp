"""Unified memory pipeline — Protocol-based extensible retrieval and indexing.

Design:
  - Searcher: pluggable retrieval strategy (FTS5, vector, graph)
  - Indexer: pluggable post-store hook (graph, wikilinks, etc.)
  - Ranker: pluggable fusion strategy (RRF, weighted, etc.)
  - RetrievalPipeline: orchestrates searchers → ranker → budget
  - WritePipeline: orchestrates indexers after store
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .graph_store import Entity


# ── Data types ───────────────────────────────────────────


@dataclass
class ScoredEntry:
    """Unified result from any searcher."""
    content: str
    layer: str = ""
    score: float = 0.0
    source: str = ""          # "fts" | "vector" | "graph"
    metadata: dict = field(default_factory=dict)
    entity: "Entity | None" = None  # graph results carry entity


# ── Protocols ────────────────────────────────────────────


@runtime_checkable
class Searcher(Protocol):
    """Pluggable retrieval strategy."""

    @property
    def name(self) -> str: ...

    async def search(self, query: str, limit: int = 10) -> list[ScoredEntry]: ...


@runtime_checkable
class Indexer(Protocol):
    """Pluggable post-store indexing hook."""

    @property
    def name(self) -> str: ...

    async def index(self, layer: str, content: str, record_id: str = "") -> None: ...


@runtime_checkable
class Ranker(Protocol):
    """Pluggable fusion strategy."""

    def fuse(self, *result_groups: list[ScoredEntry]) -> list[ScoredEntry]: ...


# ── RRF Ranker ───────────────────────────────────────────


class RRFRanker:
    """Reciprocal Rank Fusion — merges multiple ranked lists.

    score(item) = sum(1 / (k + rank_i)) for each ranking where item appears.
    Deduplicates by content hash, keeping the best score.
    """

    def __init__(self, k: int = 60):
        self.k = k

    def fuse(self, *result_groups: list[ScoredEntry]) -> list[ScoredEntry]:
        # Build per-source rankings
        best: dict[str, ScoredEntry] = {}
        scores: dict[str, float] = {}

        for group in result_groups:
            sorted_group = sorted(group, key=lambda e: e.score, reverse=True)
            for rank, entry in enumerate(sorted_group, start=1):
                key = self._dedup_key(entry)
                rrf_score = 1.0 / (self.k + rank)
                scores[key] = scores.get(key, 0.0) + rrf_score
                if key not in best or entry.score > best[key].score:
                    best[key] = entry

        # Apply fused scores
        result = []
        for key, entry in best.items():
            entry.score = scores[key]
            result.append(entry)

        result.sort(key=lambda e: e.score, reverse=True)
        return result

    @staticmethod
    def _dedup_key(entry: ScoredEntry) -> str:
        """Content-based dedup key."""
        if entry.entity:
            return f"entity:{entry.entity.name}"
        return f"content:{hash(entry.content[:200])}"


# ── Budget Controller ────────────────────────────────────


class BudgetController:
    """Truncates retrieval results to fit a token budget."""

    def __init__(
        self,
        context_window: int = 200000,
        knowledge_ratio: float = 0.50,
        chars_per_token: float = 4.0,
    ):
        self.budget_chars = int(context_window * knowledge_ratio * chars_per_token)

    def apply(self, entries: list[ScoredEntry], max_chars: int | None = None) -> str:
        """Format entries into a context string within budget."""
        budget = max_chars or self.budget_chars
        lines: list[str] = []
        total = 0

        for entry in entries:
            text = entry.content
            if not text:
                continue
            if total + len(text) > budget:
                break
            lines.append(text)
            total += len(text)

        return "\n\n".join(lines)


# ── Retrieval Pipeline ───────────────────────────────────


class RetrievalPipeline:
    """Orchestrates searchers → ranker → budget control.

    Usage:
        pipeline = RetrievalPipeline([fts, vector, graph], RRFRanker(), BudgetController())
        context = await pipeline.retrieve("query")
    """

    def __init__(
        self,
        searchers: list[Searcher],
        ranker: Ranker | None = None,
        budget: BudgetController | None = None,
    ):
        self._searchers = list(searchers)
        self._ranker = ranker or RRFRanker()
        self._budget = budget or BudgetController()

    @property
    def searchers(self) -> list[Searcher]:
        return list(self._searchers)

    def add_searcher(self, searcher: Searcher) -> None:
        self._searchers.append(searcher)

    def remove_searcher(self, name: str) -> None:
        self._searchers = [s for s in self._searchers if s.name != name]

    async def retrieve(
        self,
        query: str,
        limit: int = 10,
        max_chars: int | None = None,
    ) -> str:
        """Fan-out search, fuse, format within budget."""
        if not self._searchers or not query.strip():
            return ""

        # Fan-out: run all searchers in parallel
        tasks = [
            self._safe_search(searcher, query, limit)
            for searcher in self._searchers
        ]
        result_groups = await asyncio.gather(*tasks)

        # Fuse
        fused = self._ranker.fuse(*result_groups)

        # Budget
        return self._budget.apply(fused, max_chars)

    async def retrieve_scored(
        self,
        query: str,
        limit: int = 10,
    ) -> list[ScoredEntry]:
        """Like retrieve() but returns scored entries instead of formatted string."""
        if not self._searchers or not query.strip():
            return []

        tasks = [
            self._safe_search(searcher, query, limit)
            for searcher in self._searchers
        ]
        result_groups = await asyncio.gather(*tasks)
        return self._ranker.fuse(*result_groups)

    @staticmethod
    async def _safe_search(
        searcher: Searcher, query: str, limit: int,
    ) -> list[ScoredEntry]:
        try:
            return await searcher.search(query, limit)
        except Exception:
            return []


# ── Write Pipeline ───────────────────────────────────────


class WritePipeline:
    """Orchestrates post-store indexers.

    Usage:
        pipeline = WritePipeline([graph_indexer])
        await pipeline.post_store("facts", "Alice uses Python", "rec_123")
    """

    def __init__(self, indexers: list[Indexer] | None = None):
        self._indexers = list(indexers or [])

    @property
    def indexers(self) -> list[Indexer]:
        return list(self._indexers)

    def add_indexer(self, indexer: Indexer) -> None:
        self._indexers.append(indexer)

    def remove_indexer(self, name: str) -> None:
        self._indexers = [i for i in self._indexers if i.name != name]

    async def post_store(
        self,
        layer: str,
        content: str,
        record_id: str = "",
    ) -> None:
        """Run all indexers after a store. Fire-and-forget via create_task."""
        for indexer in self._indexers:
            try:
                await indexer.index(layer, content, record_id)
            except Exception:
                pass  # Indexing failures must not break the store path

    def post_store_bg(
        self,
        layer: str,
        content: str,
        record_id: str = "",
    ) -> None:
        """Schedule indexing as background tasks (non-blocking)."""
        try:
            loop = asyncio.get_running_loop()
            for indexer in self._indexers:
                loop.create_task(self._safe_index(indexer, layer, content, record_id))
        except RuntimeError:
            pass  # No event loop — skip background indexing

    @staticmethod
    async def _safe_index(
        indexer: Indexer, layer: str, content: str, record_id: str,
    ) -> None:
        try:
            await indexer.index(layer, content, record_id)
        except Exception:
            pass
