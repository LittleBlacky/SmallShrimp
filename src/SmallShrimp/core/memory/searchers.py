"""Searcher implementations — pluggable retrieval strategies.

Each Searcher returns list[ScoredEntry] and can be composed
in a RetrievalPipeline with any Ranker.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .pipeline import ScoredEntry

if TYPE_CHECKING:
    import sqlite3
    from .graph_store import GraphStore
    from .builtin.file_store import MarkdownStore
    from .builtin.hybrid_search import EmbeddingProvider


class FTS5Searcher:
    """Memory record search via MarkdownStore's FTS5 + vector hybrid.

    Wraps the existing hybrid_search() from builtin/hybrid_search.py.
    Results carry memory records (content, layer, score).
    """

    def __init__(
        self,
        store: "MarkdownStore",
        embedding_provider: "EmbeddingProvider | None" = None,
    ):
        self._store = store
        self._embedding_provider = embedding_provider

    @property
    def name(self) -> str:
        return "fts5"

    async def search(self, query: str, limit: int = 10) -> list[ScoredEntry]:
        records = self._store.search(query, limit=limit)
        entries = []
        for r in records:
            score = r.get("final_score", 0.0)
            entries.append(ScoredEntry(
                content=r.get("content", ""),
                layer=r.get("layer", ""),
                score=score,
                source="fts",
                metadata={
                    "id": r.get("id"),
                    "file_path": r.get("file_path", ""),
                    "created_at": r.get("created_at", ""),
                    "access_count": r.get("access_count", 0),
                },
            ))
        return entries


class GraphSearcher:
    """Knowledge graph entity search with neighbor expansion.

    Searches graph entities via FTS5, then expands with 1-hop neighbors
    and 4-signal relevance scoring.
    """

    def __init__(
        self,
        graph: "GraphStore",
        max_hops: int = 1,
        max_neighbors: int = 3,
    ):
        self._graph = graph
        self._max_hops = max_hops
        self._max_neighbors = max_neighbors

    @property
    def name(self) -> str:
        return "graph"

    async def search(self, query: str, limit: int = 10) -> list[ScoredEntry]:
        # FTS search on entities
        entities = self._graph.search_entities(query, limit=limit)
        if not entities:
            return []

        # Bump access_count for hit entities
        for entity in entities:
            self._graph.bump_access(entity.name)

        entries = []
        for i, entity in enumerate(entities):
            # Base score from search rank (inverse rank)
            base_score = 1.0 / (60 + i + 1)

            # Build content with neighbor context
            content_parts = [f"[{entity.type}] {entity.name}"]
            if entity.description:
                content_parts.append(entity.description)

            # 1-hop neighbor context
            neighbors = self._graph.get_neighbors(entity.name, depth=self._max_hops)
            rel_lines = []
            neighbor_count = 0
            for rel in neighbors.relations:
                if neighbor_count >= self._max_neighbors:
                    break
                src = next((e for e in neighbors.entities if e.id == rel.source_id), None)
                tgt = next((e for e in neighbors.entities if e.id == rel.target_id), None)
                if src and tgt:
                    other = tgt if src.id == entity.id else src
                    rel_lines.append(f"  → [{rel.predicate}] {other.name} ({other.type})")
                    neighbor_count += 1

            if rel_lines:
                content_parts.append("关系:\n" + "\n".join(rel_lines))

            entries.append(ScoredEntry(
                content="\n".join(content_parts),
                layer="graph",
                score=base_score,
                source="graph",
                entity=entity,
                metadata={"entity_id": entity.id, "entity_type": entity.type},
            ))

        return entries
