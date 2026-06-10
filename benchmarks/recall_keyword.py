"""基准: 当前 keyword + CJK unigram + QueryExpansion 方案。

运行: python -m benchmarks.recall_keyword
"""
import tempfile
from pathlib import Path

from SmallShrimp.core.memory.builtin.store import SQLiteBackend
from SmallShrimp.core.memory.builtin.common import _rank_memory, _expand_query
from benchmarks.dataset import MEMORIES, QUERIES


def run() -> dict:
    with tempfile.TemporaryDirectory() as td:
        db = SQLiteBackend(Path(td) / "bench.db")
        try:
            for layer, content in MEMORIES:
                db.store(layer, content)

            lookup = {(l, c): i for i, (l, c) in enumerate(MEMORIES)}
            hits = 0
            total = 0
            details = []

            for query, expected in QUERIES:
                queries = _expand_query(query) if query else {query}
                scored: dict[str, tuple[float, dict]] = {}
                for q in queries:
                    for r in db.list_all():
                        s = _rank_memory(q, r["content"])
                        if s >= 1.0:
                            rid = r["id"]
                            if rid not in scored or s > scored[rid][0]:
                                scored[rid] = (s, r)

                sorted_results = sorted(scored.values(), key=lambda x: x[0], reverse=True)
                top_indices = [
                    lookup[(r["layer"], r["content"])]
                    for _, r in sorted_results[:5]
                    if (r["layer"], r["content"]) in lookup
                ]
                hit = len(set(top_indices) & expected)
                hits += hit
                total += len(expected)
                details.append((query, expected, top_indices, hit, len(expected)))
        finally:
            db.close()
    return {"hits": hits, "total": total, "details": details}


if __name__ == "__main__":
    result = run()
    print(f"召回率: {result['hits']}/{result['total']} = {result['hits'] / result['total'] * 100:.0f}%")
    for query, expected, top, hit, total in result["details"]:
        status = "✅" if hit > 0 else "❌"
        print(f"  {status} {query:16s} → hit={hit}/{total}")
