"""向量召回对比实验: keyword vs HRR vs hybrid。

运行:
    python -m benchmarks.unit.memory.hrr_vector_recall.recall_hrr

对比 3 种策略在 15 条记忆上的 recall@5。
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from SmallShrimp.core.memory.builtin.store import SQLiteBackend
from SmallShrimp.core.memory.builtin.common import _rank_memory, _expand_query
from benchmarks.unit.memory.dataset import MEMORIES, QUERIES
from benchmarks.unit.memory.hrr_vector_recall import hrr

DIM = 1024


# ── 策略实现 ─────────────────────────────────────────────

def _encode_all() -> dict[int, "hrr.np.ndarray"]:
    """预编码 15 条记忆为 HRR 向量（避免 benchmark 内重复编码）。"""
    return {i: hrr.encode_text(content, DIM) for i, (_, content) in enumerate(MEMORIES)}


def _hrr_score(query: str, vec: "hrr.np.ndarray") -> float:
    """HRR 相似度 → [0, 1] 区间。"""
    qv = hrr.encode_text(query, DIM)
    return (hrr.similarity(qv, vec) + 1.0) / 2.0


def recall_keyword() -> tuple[int, int, list[dict]]:
    """纯关键词召回（当前方案，作为 baseline 复算）。"""
    hits, total = 0, 0
    details = []
    for query, expected in QUERIES:
        queries = _expand_query(query) if query else {query}
        scored: dict[int, float] = {}
        for q in queries:
            for i, (_, content) in enumerate(MEMORIES):
                s = _rank_memory(q, content)
                if s >= 1.0:
                    scored[i] = max(scored.get(i, 0), s)
        top5 = [i for i, _ in sorted(scored.items(), key=lambda x: x[1], reverse=True)[:5]]
        hit = len(set(top5) & expected)
        hits += hit
        total += len(expected)
        details.append({"query": query, "expected": expected, "top5": top5, "hit": hit, "total": len(expected)})
    return hits, total, details


def recall_hrr_only(encoded: dict[int, "hrr.np.ndarray"]) -> tuple[int, int, list[dict]]:
    """纯 HRR 向量召回。"""
    hits, total = 0, 0
    details = []
    for query, expected in QUERIES:
        scored = {i: _hrr_score(query, vec) for i, vec in encoded.items()}
        top5 = [i for i, _ in sorted(scored.items(), key=lambda x: x[1], reverse=True)[:5]]
        hit = len(set(top5) & expected)
        hits += hit
        total += len(expected)
        details.append({"query": query, "expected": expected, "top5": top5, "hit": hit, "total": len(expected)})
    return hits, total, details


def recall_hybrid(encoded: dict[int, "hrr.np.ndarray"], kw_weight: float = 0.7) -> tuple[int, int, list[dict]]:
    """混合召回: keyword + HRR。"""
    hrr_weight = 1.0 - kw_weight
    hits, total = 0, 0
    details = []
    for query, expected in QUERIES:
        scored: dict[int, float] = {}
        # keyword
        queries = _expand_query(query) if query else {query}
        for q in queries:
            for i, (_, content) in enumerate(MEMORIES):
                s = _rank_memory(q, content)
                if s >= 1.0:
                    scored[i] = max(scored.get(i, 0), s)
        # HRR
        for i, vec in encoded.items():
            hs = _hrr_score(query, vec)
            kw = scored.get(i, 0)
            scored[i] = kw * kw_weight + hs * 10.0 * hrr_weight  # HRR 分数放大到与 keyword 可比
        top5 = [i for i, _ in sorted(scored.items(), key=lambda x: x[1], reverse=True)[:5]]
        hit = len(set(top5) & expected)
        hits += hit
        total += len(expected)
        details.append({"query": query, "expected": expected, "top5": top5, "hit": hit, "total": len(expected)})
    return hits, total, details


# ── 主流程 ───────────────────────────────────────────────

def run() -> dict:
    print("=" * 65)
    print("  向量召回对比实验: keyword vs HRR vs hybrid")
    print("=" * 65)

    # 编码计时
    t0 = time.perf_counter()
    encoded = _encode_all()
    encode_time = time.perf_counter() - t0

    vec_size = len(hrr.phases_to_bytes(encoded[0]))
    print(f"\n  HRR 编码: {len(MEMORIES)} 条, {encode_time*1000:.1f}ms, "
          f"每条 {vec_size/1024:.0f}KB (dim={DIM})")

    # 三路测试
    results = {}

    for name, fn in [
        ("keyword-only", lambda: recall_keyword()),
        ("hrr-only", lambda: recall_hrr_only(encoded)),
        ("hybrid (0.7kw+0.3hrr)", lambda: recall_hybrid(encoded)),
    ]:
        t0 = time.perf_counter()
        hits, total, details = fn()
        elapsed = time.perf_counter() - t0
        results[name] = {"hits": hits, "total": total, "elapsed": elapsed, "details": details}

    # ── 输出 ──────────────────────────────────────────
    print(f"\n{'策略':<28s} {'recall@5':>10s} {'耗时':>8s}")
    print("-" * 48)
    for name, r in results.items():
        rate = r["hits"] / r["total"] * 100
        print(f"  {name:<26s} {r['hits']}/{r['total']} = {rate:4.0f}%  {r['elapsed']*1000:6.1f}ms")

    # ── 逐条对比 ──────────────────────────────────────
    print(f"\n{'查询':<18s} {'期望':>6s} {'keyword':>8s} {'HRR':>8s} {'hybrid':>8s}")
    print("-" * 54)
    for j, (query, expected) in enumerate(QUERIES):
        kw_hit = results["keyword-only"]["details"][j]["hit"]
        hrr_hit = results["hrr-only"]["details"][j]["hit"]
        hy_hit = results["hybrid (0.7kw+0.3hrr)"]["details"][j]["hit"]
        total_exp = results["keyword-only"]["details"][j]["total"]

        def _mark(h: int) -> str:
            return "✅" if h > 0 else "❌"

        print(f"  {query:<16s} {total_exp:>4d}个  {_mark(kw_hit):>6s}      {_mark(hrr_hit):>6s}    {_mark(hy_hit):>6s}")

    # ── 权重扫描 ──────────────────────────────────────
    print(f"\n{'权重扫描 (keyword 占比)':─^48s}")
    print(f"  {'kw_weight':>10s}  {'recall@5':>10s}")
    print(f"  {'─'*10}  {'─'*10}")
    best_w, best_r = 0.7, 0
    for kw_w in [round(x * 0.1, 1) for x in range(11)]:
        hits, total, _ = recall_hybrid(encoded, kw_weight=kw_w)
        rate = hits / total * 100
        marker = " ←" if hits > best_r else ""
        print(f"  {kw_w:>10.1f}  {hits}/{total} = {rate:4.0f}%{marker}")
        if hits > best_r:
            best_r, best_w = hits, kw_w
    print(f"\n  最优融合权重: kw={best_w:.1f}, hrr={1-best_w:.1f}, recall={best_r}/{total}={best_r/total*100:.0f}%")

    # ── 漏报诊断 ──────────────────────────────────────
    _diagnose_misses(encoded)

    return results


def _diagnose_misses(encoded: dict[int, "hrr.np.ndarray"]) -> None:
    """打印漏报 query 的 HRR top-5 详情。"""
    miss_queries = [
        (q, e) for q, e in QUERIES
        if not (set(e) & {i for i, _ in sorted(
            {i: _hrr_score(q, vec) for i, vec in encoded.items()}.items(),
            key=lambda x: x[1], reverse=True
        )[:5]})
    ]
    if not miss_queries:
        print("\n  🎉 零漏报！")
        return

    print(f"\n{'漏报诊断':─^60s}")
    lookup = {i: (l, c) for i, (l, c) in enumerate(MEMORIES)}
    for query, expected in miss_queries:
        target_indices = expected
        scored = {i: _hrr_score(query, vec) for i, vec in encoded.items()}
        ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)
        print(f"\n  查询: \"{query}\"")
        print(f"  期望命中 (index {target_indices}):")
        for ei in target_indices:
            layer, content = lookup[ei]
            sim = scored[ei]
            rank = next(j+1 for j, (i, _) in enumerate(ranked) if i == ei)
            print(f"    [{ei}] rank={rank:>2d}, sim={sim:.4f}  [{layer}] {content}")
        print(f"  HRR top-5 实际返回:")
        for rank, (i, sim) in enumerate(ranked[:5], 1):
            layer, content = lookup[i]
            marker = " ★" if i in target_indices else ""
            print(f"    rank={rank}, sim={sim:.4f}  [{layer}] {content}{marker}")


if __name__ == "__main__":
    run()
