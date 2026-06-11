"""向量召回对比实验: keyword vs HRR vs hybrid。

运行:
    python -m benchmarks.unit.memory.hrr_vector_recall.recall_hrr

对比多种策略在 15 条记忆上的 recall@5。

LLM Query Expansion（可选）:
    设置环境变量 LLM_EXPAND=true 即可启用 LLM 扩展查询。
    会从 workspace/config.user.yaml 读取 LLM 配置。
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

from SmallShrimp.core.memory.builtin.store import SQLiteBackend
from SmallShrimp.core.memory.builtin.common import _rank_memory, _expand_query
from benchmarks.unit.memory.dataset import MEMORIES, QUERIES, resolve_expected
from benchmarks.unit.memory.hrr_vector_recall import hrr

DIM = 1024

_LM_EXPANSIONS: dict[str, list[str]] = {}


def _get_llm_expansions(query: str) -> list[str]:
    """获取 LLM 生成的查询扩展（首次调用时生成，后续缓存）。"""
    if not os.environ.get("LLM_EXPAND", "").lower() in ("1", "true", "yes"):
        return []
    if query in _LM_EXPANSIONS:
        return _LM_EXPANSIONS[query]

    # 读取配置
    ws = Path(os.environ.get("WORKSPACE", "."))
    config_path = ws / "workspace" / "config.user.yaml"
    if not config_path.exists():
        config_path = ws / "config.user.yaml"

    try:
        import yaml
    except ImportError:
        print("  [LLM] 需要 PyYAML: pip install pyyaml")
        return []

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}

    # 找 provider 和 model
    provider_name = config.get("default_provider", "deepseek")
    provider_cfg = config.get("providers", {}).get(provider_name, {})
    api_key = provider_cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")
    api_base = provider_cfg.get("api_base")

    if not api_key:
        print("  [LLM] 未配置 API key，跳过 LLM Query Expansion")
        return []

    model = f"{provider_name}/deepseek-chat"
    expansions = _call_llm_expand(model, api_key, api_base, query)
    _LM_EXPANSIONS[query] = expansions
    return expansions


def _call_llm_expand(model: str, api_key: str, api_base: str | None,
                     query: str) -> list[str]:
    """调用 LLM 生成查询扩展。"""
    prompt = (
        "You are a memory search assistant. The user query below will be used to recall "
        "past conversation memories. Generate 3-5 alternative phrasings / synonyms so the "
        "search can find semantically related memories. "
        "Keep the core meaning but vary the wording. "
        "If the query is in Chinese, you may include mixed Chinese-English variants.\n\n"
        "Output one alternative per line, NO numbering, NO extra text.\n\n"
        f"Query: {query}"
    )
    try:
        from litellm import completion
        resp = completion(
            model=model,
            api_key=api_key,
            api_base=api_base,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )
        content = resp.choices[0].message.content.strip()
        lines = [line.strip().lstrip("0123456789.- ") for line in content.split("\n") if line.strip()]
        lines = [line for line in lines if line.lower() != query.lower()]
        if lines:
            print(f"  [LLM] {query:16s} → {lines}")
            return lines
    except Exception as e:
        print(f"  [LLM] 调用失败 ({query}): {e}")
    return []


def _expand_with_llm(query: str) -> set[str]:
    """合并静态扩展 + LLM 扩展。"""
    terms = _expand_query(query)
    llm_terms = _get_llm_expansions(query)
    if llm_terms:
        terms.update(llm_terms)
    return terms


# ── 策略实现 ─────────────────────────────────────────────

def _encode_all() -> dict[int, "hrr.np.ndarray"]:
    """预编码 15 条记忆为 HRR 向量（避免 benchmark 内重复编码）。"""
    return {i: hrr.encode_text(content, DIM) for i, (_, content) in enumerate(MEMORIES)}


def _encode_all_tf() -> dict[int, "hrr.np.ndarray"]:
    """TF 加权版预编码。"""
    return {i: hrr.encode_text_tf(content, DIM) for i, (_, content) in enumerate(MEMORIES)}


def _hrr_score(query: str, vec: "hrr.np.ndarray", tf: bool = False) -> float:
    """HRR 相似度 → [0, 1] 区间。"""
    qv = hrr.encode_text_tf(query, DIM) if tf else hrr.encode_text(query, DIM)
    return (hrr.similarity(qv, vec) + 1.0) / 2.0


def recall_keyword() -> tuple[int, int, list[dict]]:
    """纯关键词召回（当前方案，作为 baseline 复算）。"""
    hits, total = 0, 0
    details = []
    for query, expected in QUERIES:
        expected = resolve_expected(expected, MEMORIES)
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
        expected = resolve_expected(expected, MEMORIES)
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
        expected = resolve_expected(expected, MEMORIES)
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


def recall_hrr_tf(encoded_tf: dict[int, "hrr.np.ndarray"]) -> tuple[int, int, list[dict]]:
    """TF 加权 HRR 召回。"""
    hits, total = 0, 0
    details = []
    for query, expected in QUERIES:
        expected = resolve_expected(expected, MEMORIES)
        scored = {i: _hrr_score(query, vec, tf=True) for i, vec in encoded_tf.items()}
        top5 = [i for i, _ in sorted(scored.items(), key=lambda x: x[1], reverse=True)[:5]]
        hit = len(set(top5) & expected)
        hits += hit
        total += len(expected)
        details.append({"query": query, "expected": expected, "top5": top5, "hit": hit, "total": len(expected)})
    return hits, total, details


def recall_hrr_llm(encoded: dict[int, "hrr.np.ndarray"]) -> tuple[int, int, list[dict]]:
    """HRR + LLM Query Expansion 召回。"""
    hits, total = 0, 0
    details = []
    for query, expected in QUERIES:
        expected = resolve_expected(expected, MEMORIES)
        queries = _expand_with_llm(query)
        scored: dict[str, tuple[float, int]] = {}
        for q in queries:
            for i, vec in encoded.items():
                hs = _hrr_score(q, vec)
                key = f"{i}"
                if key not in scored or hs > scored[key][0]:
                    scored[key] = (hs, i)
        top5 = [idx for _, idx in sorted(scored.values(), key=lambda x: x[0], reverse=True)[:5]]
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

    t0 = time.perf_counter()
    encoded_tf = _encode_all_tf()
    encode_tf_time = time.perf_counter() - t0

    vec_size = len(hrr.phases_to_bytes(encoded[0]))
    print(f"\n  等权 HRR: {len(MEMORIES)} 条, {encode_time*1000:.1f}ms")
    print(f"  TF 加权:  {len(MEMORIES)} 条, {encode_tf_time*1000:.1f}ms")
    print(f"  每条向量: {vec_size/1024:.0f}KB (dim={DIM})")

    # ── LLM 预检查 ─────────────────────────────────
    use_llm = os.environ.get("LLM_EXPAND", "").lower() in ("1", "true", "yes")
    if use_llm:
        print("  LLM Query Expansion: 已启用")
        # 预加载一次检查配置是否可用
        _get_llm_expansions("test")
    else:
        print("  LLM Query Expansion: 未启用（设置 LLM_EXPAND=true）")

    # 策略测试
    results: dict[str, Any] = {}

    for name, fn in [
        ("keyword-only", lambda: recall_keyword()),
        ("hrr (等权)", lambda: recall_hrr_only(encoded)),
        ("hrr (TF)", lambda: recall_hrr_tf(encoded_tf)),
        ("hybrid (0.7kw+0.3hrr)", lambda: recall_hybrid(encoded)),
    ]:
        t0 = time.perf_counter()
        hits, total, details = fn()
        elapsed = time.perf_counter() - t0
        results[name] = {"hits": hits, "total": total, "elapsed": elapsed, "details": details}

    # LLM expansion（如果启用）
    if use_llm:
        t0 = time.perf_counter()
        hits, total, details = recall_hrr_llm(encoded)
        elapsed = time.perf_counter() - t0
        results["hrr + LLM扩展"] = {"hits": hits, "total": total, "elapsed": elapsed, "details": details}

    # ── 输出 ──────────────────────────────────────────
    print(f"\n{'策略':<28s} {'recall@5':>10s} {'耗时':>8s}")
    print("-" * 48)
    llm_key = "hrr + LLM扩展"
    for name, r in results.items():
        if name == llm_key and not use_llm:
            continue
        rate = r["hits"] / r["total"] * 100
        print(f"  {name:<26s} {r['hits']}/{r['total']} = {rate:4.0f}%  {r['elapsed']*1000:6.1f}ms")

    # ── 逐条对比 ──────────────────────────────────────
    headers = ["keywd", "等权", "TF", "hybrd"]
    if use_llm:
        headers.append("LLM+")
    header_line = "  ".join(f"{h:>6s}" for h in headers)
    print(f"\n{'查询':<18s} {'期望':>6s} {header_line}")
    print("-" * (24 + len(header_line) * 8))
    for j, (query, expected) in enumerate(QUERIES):
        vals = [
            results["keyword-only"]["details"][j]["hit"],
            results["hrr (等权)"]["details"][j]["hit"],
            results["hrr (TF)"]["details"][j]["hit"],
            results["hybrid (0.7kw+0.3hrr)"]["details"][j]["hit"],
        ]
        if use_llm:
            vals.append(results["hrr + LLM扩展"]["details"][j]["hit"])
        total_exp = results["keyword-only"]["details"][j]["total"]

        def _mark(h: int) -> str:
            return " ✅" if h > 0 else " ❌"

        val_str = "  ".join(_mark(v) for v in vals)
        print(f"  {query:<16s} {total_exp:>4d}个  {val_str}")

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
    miss_queries: list[tuple[str, set[int]]] = []
    for q, e in QUERIES:
        expected = resolve_expected(e, MEMORIES)
        top5 = {i for i, _ in sorted(
            {i: _hrr_score(q, vec) for i, vec in encoded.items()}.items(),
            key=lambda x: x[1], reverse=True
        )[:5]}
        if not (expected & top5):
            miss_queries.append((q, expected))
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
