"""4-signal relevance model for entity relationships.

Signals:
  1. Direct links ([[wikilink]] references) — weight 3.0
  2. Source overlap (shared source documents) — weight 4.0
  3. Adamic-Adar (shared neighbors, inverse log degree) — weight 1.5
  4. Type affinity (same entity type bonus) — weight 1.0
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph_store import GraphStore, Entity

W_LINK = 3.0
W_SOURCE = 4.0
W_ADAMIC = 1.5
W_TYPE = 1.0


def _direct_link_score(entity_a: str, entity_b: str, graph: "GraphStore") -> float:
    """Score based on direct relation between two entities."""
    neighbors_a = graph.get_neighbors(entity_a, depth=1)
    for rel in neighbors_a.relations:
        src = next((e for e in neighbors_a.entities if e.id == rel.source_id), None)
        tgt = next((e for e in neighbors_a.entities if e.id == rel.target_id), None)
        if src and tgt:
            if (src.name == entity_a and tgt.name == entity_b) or \
               (src.name == entity_b and tgt.name == entity_a):
                return 1.0
    return 0.0


def _source_overlap_score(entity_a: str, entity_b: str, graph: "GraphStore") -> float:
    """Score based on shared source documents (via source_text in relations)."""
    conn = graph._get_conn()
    # Get source texts for both entities
    rows_a = conn.execute("""
        SELECT source_text FROM relations
        WHERE (source_id = (SELECT id FROM entities WHERE name = ?)
               OR target_id = (SELECT id FROM entities WHERE name = ?))
        AND source_text != ''
    """, (entity_a, entity_a)).fetchall()

    rows_b = conn.execute("""
        SELECT source_text FROM relations
        WHERE (source_id = (SELECT id FROM entities WHERE name = ?)
               OR target_id = (SELECT id FROM entities WHERE name = ?))
        AND source_text != ''
    """, (entity_b, entity_b)).fetchall()

    sources_a = {r["source_text"][:100] for r in rows_a}
    sources_b = {r["source_text"][:100] for r in rows_b}

    if not sources_a or not sources_b:
        return 0.0

    overlap = len(sources_a & sources_b)
    return min(overlap / max(len(sources_a), len(sources_b)), 1.0)


def _adamic_adar_score(entity_a: str, entity_b: str, graph: "GraphStore") -> float:
    """Adamic-Adar: shared neighbors weighted by inverse log degree."""
    neighbors_a = {e.name for e in graph.get_neighbors(entity_a, 1).entities if e.name != entity_a}
    neighbors_b = {e.name for e in graph.get_neighbors(entity_b, 1).entities if e.name != entity_b}

    shared = neighbors_a & neighbors_b
    if not shared:
        return 0.0

    score = 0.0
    for neighbor in shared:
        # Degree of shared neighbor
        deg = len(graph.get_neighbors(neighbor, 1).entities)
        if deg > 1:
            score += 1.0 / math.log(deg)

    # Normalize
    return min(score / 5.0, 1.0)


def _type_affinity_score(entity_a: str, entity_b: str, graph: "GraphStore") -> float:
    """Same entity type gets a bonus."""
    a = graph.get_entity(entity_a)
    b = graph.get_entity(entity_b)
    if a and b and a.type == b.type:
        return 1.0
    return 0.0


def calculate_relevance(
    entity_a: str,
    entity_b: str,
    graph: "GraphStore",
) -> float:
    """Calculate 4-signal relevance score between two entities."""
    s1 = _direct_link_score(entity_a, entity_b, graph) * W_LINK
    s2 = _source_overlap_score(entity_a, entity_b, graph) * W_SOURCE
    s3 = _adamic_adar_score(entity_a, entity_b, graph) * W_ADAMIC
    s4 = _type_affinity_score(entity_a, entity_b, graph) * W_TYPE

    raw = s1 + s2 + s3 + s4
    # Normalize to [0, 1] (max possible = 3+4+1.5+1 = 9.5)
    return min(raw / 9.5, 1.0)


def get_related_entities(
    entity_name: str,
    graph: "GraphStore",
    top_n: int = 10,
) -> list[tuple[str, float]]:
    """Get most related entities by 4-signal relevance.

    Returns list of (entity_name, relevance_score) sorted by score desc.
    """
    # Seed: 1-hop neighbors
    neighbors = graph.get_neighbors(entity_name, depth=1)
    candidates = {e.name for e in neighbors.entities if e.name != entity_name}

    if not candidates:
        return []

    scored = []
    for candidate in candidates:
        score = calculate_relevance(entity_name, candidate, graph)
        scored.append((candidate, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n]
