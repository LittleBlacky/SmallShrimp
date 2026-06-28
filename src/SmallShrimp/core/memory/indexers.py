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
    2. Creates entities and relations in the graph (with semantic dedup)
    3. Resolves [[wikilinks]] and creates bidirectional edges

    Semantic dedup: before creating a new entity, searches for similar
    existing entities by name. If found, merges into the existing one
    instead of creating a duplicate.
    """

    DEDUP_SIMILARITY_THRESHOLD = 0.85

    def __init__(
        self,
        graph: "GraphStore",
        llm_caller: Any = None,
        embedding_provider: Any = None,
    ):
        self._graph = graph
        self._llm = llm_caller
        self._embedding = embedding_provider

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
        """Extract triplets via LLM and store in graph with semantic dedup."""
        from .extraction import extract_triplets
        from .ontology import normalize_entity_type, normalize_predicate

        result = await extract_triplets(content, self._llm)
        if not result.triplets:
            return

        for triplet in result.triplets:
            subject = self._resolve_or_create(triplet.subject, triplet.subject_type, content)
            obj = self._resolve_or_create(triplet.object, triplet.object_type, content)
            self._graph.add_relation(
                subject, triplet.predicate, obj,
                source_text=triplet.source_text or content[:200],
            )
            # Incremental community assignment (after relation is created)
            self._graph.assign_community(subject)
            self._graph.assign_community(obj)

    def _resolve_or_create(self, name: str, entity_type: str, context: str) -> str:
        """Find existing entity or create new one. Returns the canonical name.

        Semantic dedup: if an embedding provider is available, searches for
        similar entities and merges if cosine > threshold.
        """
        # Exact match first
        existing = self._graph.get_entity(name)
        if existing:
            return name

        # Semantic dedup via embedding
        if self._embedding is not None:
            similar = self._find_similar_entity(name)
            if similar:
                # Merge: update description with new info
                self._merge_entity(similar, name, entity_type, context)
                return similar

        # No match found, create new
        self._graph.upsert_entity(name, entity_type)
        return name

    def _find_similar_entity(self, name: str) -> str | None:
        """Search for an entity with similar name via embedding cosine similarity."""
        try:
            import math
            name_vec = self._embedding.encode(name)
            if not name_vec:
                return None

            # Search existing entities of similar types
            candidates = self._graph.search_entities(name, limit=5)
            for candidate in candidates:
                cand_vec = self._embedding.encode(candidate.name)
                if not cand_vec:
                    continue
                cosine = self._cosine_similarity(name_vec, cand_vec)
                if cosine >= self.DEDUP_SIMILARITY_THRESHOLD:
                    return candidate.name
        except Exception:
            pass  # Embedding failure is non-fatal
        return None

    def _merge_entity(self, existing_name: str, new_name: str, entity_type: str, context: str) -> None:
        """Merge new entity info into existing entity."""
        existing = self._graph.get_entity(existing_name)
        if not existing:
            return

        # Add new name as alias
        aliases = list(existing.aliases)
        if new_name not in aliases and new_name != existing_name:
            aliases.append(new_name)

        # Enrich description if empty
        description = existing.description
        if not description and context:
            description = context[:200]

        self._graph.upsert_entity(
            existing_name, entity_type or existing.type,
            description=description,
            aliases=aliases,
            importance=existing.importance,
        )

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import math
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
