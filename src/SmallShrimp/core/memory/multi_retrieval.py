"""RRF multi-phase retrieval for knowledge graph.

5-phase pipeline:
  Phase 1: Tokenized search (English stemming + CJK bigram + title bonus)
  Phase 2: Vector semantic search (chunk embedding → page aggregation)
  Phase 3: RRF fusion (1/(60+rank) merge)
  Phase 4: Graph expansion (top results as seeds, 4-signal model, 2-hop decay)
  Phase 5: Context budget control (50% knowledge, 15% response, 30% history+system)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph_store import GraphStore


# RRF constant
RRF_K = 60

# Context budget ratios
KNOWLEDGE_RATIO = 0.50
RESPONSE_RATIO = 0.15
HISTORY_RATIO = 0.35


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: English words + CJK bigrams."""
    # English words
    en_tokens = re.findall(r'[a-zA-Z]+', text.lower())
    # CJK bigrams
    cjk = re.findall(r'[一-鿿]+', text)
    cjk_bigrams = []
    for segment in cjk:
        for i in range(len(segment) - 1):
            cjk_bigrams.append(segment[i:i+2])
    return en_tokens + cjk_bigrams


def _remove_stopwords(tokens: list[str]) -> list[str]:
    """Remove common English stopwords."""
    _STOP = frozenset({
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "shall", "should", "may", "might", "can", "could", "of", "in",
        "to", "for", "with", "on", "at", "from", "by", "and", "or",
        "not", "but", "if", "then", "that", "this", "it", "its",
    })
    return [t for t in tokens if t not in _STOP]


def tokenize_search(
    query: str,
    candidates: list[str],
    title_bonus: float = 1.5,
) -> list[tuple[str, float]]:
    """Rank candidates by token overlap with query.

    Returns [(candidate, score)] sorted by score desc.
    """
    query_tokens = set(_remove_stopwords(_tokenize(query)))
    if not query_tokens:
        return []

    scored = []
    for candidate in candidates:
        cand_tokens = set(_remove_stopwords(_tokenize(candidate)))
        overlap = len(query_tokens & cand_tokens)
        if overlap == 0:
            continue

        # Title bonus: if query tokens appear in a short candidate (likely a title)
        bonus = title_bonus if len(candidate) < 100 and overlap > 0 else 1.0
        score = overlap * bonus
        scored.append((candidate, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def reciprocal_rank_fusion(
    *rankings: list[str],
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """RRF fusion across multiple ranked lists.

    score(item) = sum(1 / (k + rank_i)) for each ranking where item appears.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)

    result = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return result


def graph_expand(
    seed_entities: list[str],
    graph: "GraphStore",
    max_hops: int = 2,
    decay: float = 0.5,
    max_results: int = 20,
) -> list[tuple[str, float]]:
    """Expand from seed entities through graph neighbors.

    Each hop applies decay factor to the score.
    """
    from .relevance import calculate_relevance

    visited: dict[str, float] = {}
    frontier = [(name, 1.0) for name in seed_entities]

    for hop in range(max_hops):
        next_frontier = []
        for entity_name, score in frontier:
            if entity_name in visited:
                continue
            visited[entity_name] = score

            # Get neighbors
            neighbors = graph.get_neighbors(entity_name, depth=1)
            for neighbor in neighbors.entities:
                if neighbor.name == entity_name or neighbor.name in visited:
                    continue
                # Apply relevance and decay
                relevance = calculate_relevance(entity_name, neighbor.name, graph)
                neighbor_score = score * relevance * decay
                if neighbor_score > 0.01:  # Prune low-score
                    next_frontier.append((neighbor.name, neighbor_score))

        frontier = next_frontier
        decay *= decay  # Compound decay for 2-hop

    result = sorted(visited.items(), key=lambda x: x[1], reverse=True)
    return result[:max_results]


def multi_phase_retrieve(
    query: str,
    graph: "GraphStore",
    vector_scores: dict[str, float] | None = None,
    context_window: int = 200000,
    limit: int = 15,
) -> str:
    """Full 5-phase retrieval pipeline.

    Returns formatted context string for LLM consumption.
    """
    # Phase 1: Tokenized search
    all_entities = graph.get_all_entities(limit=200)
    entity_names = [e.name for e in all_entities]
    token_results = tokenize_search(query, entity_names)
    token_ranking = [name for name, _ in token_results]

    # Phase 2: Vector scores (if provided)
    vec_ranking = []
    if vector_scores:
        vec_ranked = sorted(vector_scores.items(), key=lambda x: x[1], reverse=True)
        vec_ranking = [name for name, _ in vec_ranked]

    # Phase 3: RRF fusion
    if vec_ranking:
        fused = reciprocal_rank_fusion(token_ranking, vec_ranking)
    else:
        fused = reciprocal_rank_fusion(token_ranking)

    # Phase 4: Graph expansion from top seeds
    seeds = [name for name, _ in fused[:5]]
    expanded = graph_expand(seeds, graph, max_hops=2, decay=0.5, max_results=limit)

    # Merge fused + expanded
    final_scores: dict[str, float] = {}
    for name, score in fused:
        final_scores[name] = final_scores.get(name, 0.0) + score
    for name, score in expanded:
        final_scores[name] = max(final_scores.get(name, 0.0), score * 0.3)

    final_ranked = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

    # Phase 5: Format with budget control
    budget_chars = int(context_window * KNOWLEDGE_RATIO * 4)  # ~4 chars per token
    lines = ["## Knowledge Graph Context\n"]
    total = 0

    for name, score in final_ranked:
        entity = graph.get_entity(name)
        if not entity:
            continue

        entry = f"### {entity.name} ({entity.type})"
        if entity.description:
            entry += f"\n{entity.description}"

        # Add neighbor context
        neighbors = graph.get_neighbors(name, depth=1)
        rel_lines = []
        for rel in neighbors.relations[:3]:
            src = next((e for e in neighbors.entities if e.id == rel.source_id), None)
            tgt = next((e for e in neighbors.entities if e.id == rel.target_id), None)
            if src and tgt:
                other = tgt if src.name == name else src
                rel_lines.append(f"  → [{rel.predicate}] {other.name}")
        if rel_lines:
            entry += "\n**关系:**\n" + "\n".join(rel_lines)

        entry += f"\n*relevance: {score:.3f}*\n"

        if total + len(entry) > budget_chars:
            break
        lines.append(entry)
        total += len(entry)

    return "\n".join(lines)
