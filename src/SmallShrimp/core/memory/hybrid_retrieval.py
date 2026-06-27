"""Hybrid retrieval — fusion of vector, fulltext, and importance scores.

.. deprecated::
    Merged into searchers.GraphSearcher and pipeline.RetrievalPipeline.
    This module is kept for backward compatibility only.

Fusion formula: 0.55 * vector + 0.30 * fulltext + 0.15 * importance
Plus 1-hop neighbor context enrichment from graph store.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph_store import GraphStore, Entity


@dataclass
class ScoredEntity:
    entity: "Entity"
    vector_score: float = 0.0
    fulltext_score: float = 0.0
    importance_score: float = 0.0
    final_score: float = 0.0
    neighbor_context: str = ""


# Fusion weights
W_VECTOR = 0.55
W_FULLTEXT = 0.30
W_IMPORTANCE = 0.15


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    k: int = 60,
) -> dict[str, float]:
    """RRF fusion: score = sum(1 / (k + rank)) across rankings."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


def hybrid_search(
    query: str,
    graph: "GraphStore",
    vector_scores: dict[str, float] | None = None,
    limit: int = 10,
) -> list[ScoredEntity]:
    """Search entities using hybrid retrieval (fulltext + vector + importance).

    Args:
        query: Search query
        graph: GraphStore instance
        vector_scores: Optional pre-computed vector similarity scores {entity_name: score}
        limit: Max results
    """
    # Fulltext search
    fts_results = graph.search_entities(query, limit=limit * 2)
    fts_ranking = [e.name for e in fts_results]
    fts_scores = {name: 1.0 / (60 + rank) for rank, name in enumerate(fts_ranking, 1)}

    # Vector scores (if provided)
    vec_scores = vector_scores or {}

    # Normalize scores to [0, 1]
    max_fts = max(fts_scores.values()) if fts_scores else 1.0
    max_vec = max(vec_scores.values()) if vec_scores else 1.0

    # Merge all candidate entity names
    candidates = set(fts_ranking) | set(vec_scores.keys())

    scored: list[ScoredEntity] = []
    for name in candidates:
        entity = graph.get_entity(name)
        if not entity:
            continue

        # Normalize
        norm_fts = (fts_scores.get(name, 0.0) / max_fts) if max_fts > 0 else 0.0
        norm_vec = (vec_scores.get(name, 0.0) / max_vec) if max_vec > 0 else 0.0
        norm_imp = min(entity.importance / 10.0, 1.0)  # importance typically 1-10

        final = W_VECTOR * norm_vec + W_FULLTEXT * norm_fts + W_IMPORTANCE * norm_imp

        scored.append(ScoredEntity(
            entity=entity,
            vector_score=norm_vec,
            fulltext_score=norm_fts,
            importance_score=norm_imp,
            final_score=final,
        ))

    # Sort by final score descending
    scored.sort(key=lambda s: s.final_score, reverse=True)
    return scored[:limit]


def enrich_with_neighbors(
    scored_entities: list[ScoredEntity],
    graph: "GraphStore",
    max_neighbors: int = 3,
) -> list[ScoredEntity]:
    """Add 1-hop neighbor context to scored entities."""
    for se in scored_entities:
        neighbors = graph.get_neighbors(se.entity.name, depth=1)
        if not neighbors.entities:
            continue

        # Format neighbor context
        lines = []
        neighbor_count = 0
        for rel in neighbors.relations:
            if neighbor_count >= max_neighbors:
                break
            src = next((e for e in neighbors.entities if e.id == rel.source_id), None)
            tgt = next((e for e in neighbors.entities if e.id == rel.target_id), None)
            if src and tgt and (src.id == se.entity.id or tgt.id == se.entity.id):
                other = tgt if src.id == se.entity.id else src
                direction = "→" if src.id == se.entity.id else "←"
                lines.append(f"  {se.entity.name} {direction} [{rel.predicate}] {other.name} ({other.type})")
                neighbor_count += 1

        if lines:
            se.neighbor_context = "\n".join(lines)

    return scored_entities


def format_retrieval_context(
    scored_entities: list[ScoredEntity],
    max_chars: int = 3000,
) -> str:
    """Format scored entities into a context string for LLM consumption."""
    lines = ["## Knowledge Graph Context\n"]
    total = 0

    for se in scored_entities:
        entry = f"### {se.entity.name} ({se.entity.type})"
        if se.entity.description:
            entry += f"\n{se.entity.description}"
        if se.neighbor_context:
            entry += f"\n**关系:**\n{se.neighbor_context}"
        entry += f"\n*relevance: {se.final_score:.3f}*\n"

        if total + len(entry) > max_chars:
            break
        lines.append(entry)
        total += len(entry)

    return "\n".join(lines)
