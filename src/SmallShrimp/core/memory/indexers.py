"""Indexer implementations — pluggable post-store hooks.

Each Indexer runs after a memory entry is stored, enriching
the knowledge graph with extracted entities and relations.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .graph_store import GraphStore


class GraphIndexer:
    """Post-store graph indexing: triplet extraction + wikilink resolution.

    After a memory entry is stored, this indexer:
    1. Extracts triplets from the content (via LLM)
    2. Creates entities and relations in the graph
    3. Resolves [[wikilinks]] and creates bidirectional edges

    The LLM caller is optional — if not provided, only wikilinks are processed.
    """

    def __init__(
        self,
        graph: "GraphStore",
        llm_caller: Any = None,
    ):
        self._graph = graph
        self._llm = llm_caller

    @property
    def name(self) -> str:
        return "graph"

    async def index(self, layer: str, content: str, record_id: str = "") -> None:
        """Index a memory entry into the knowledge graph."""
        if not content or not content.strip():
            return

        # Step 1: Wikilink resolution (always, no LLM needed)
        from .wikilinks import inject_wikilink_relations
        inject_wikilink_relations(content, entity_name=record_id or layer, graph=self._graph)

        # Step 2: Triplet extraction (requires LLM)
        if self._llm is not None:
            await self._extract_and_store(content)

    async def _extract_and_store(self, content: str) -> None:
        """Extract triplets via LLM and store in graph."""
        from .extraction import extract_triplets
        from .ontology import normalize_entity_type, normalize_predicate

        result = await extract_triplets(content, self._llm)
        if not result.triplets:
            return

        for triplet in result.triplets:
            self._graph.upsert_entity(
                triplet.subject, triplet.subject_type,
            )
            self._graph.upsert_entity(
                triplet.object, triplet.object_type,
            )
            self._graph.add_relation(
                triplet.subject, triplet.predicate, triplet.object,
                source_text=triplet.source_text or content[:200],
            )
