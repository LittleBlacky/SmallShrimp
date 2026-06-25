# 记忆向量检索增强 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 涉及层: Core / Memory

---

## 1. 产品概述

### 1.1 产品定位

将 `core/memory/builtin/` 内置记忆存储从纯关键词/文件级检索升级为语义向量检索，使得 `prefetch()` 和 `sync_turn()` 召回的记忆与用户当前提问在语义上相关，大幅提升记忆系统的召回质量。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| `BuiltinProvider` 使用 JSON 文件 + 线性扫描存储，`prefetch` 依赖关键词匹配 | 引入 `sentence-transformers` 向量化，按语义相似度召回 |
| 现有 `hybrid_search.py` 有接口框架但 sqlite-vec 是可选依赖 | 将向量检索从可选提升为默认能力，安装时自动启用 |
| 不同记忆层（profile/facts/reflections）之间无跨层语义关联 | 统一向量索引，支持跨层 `kNN` 检索 |
| 大记忆量下线性扫描性能下降（O(n)） | 向量索引（HNSW/IVF）实现 O(log n) 检索 |
| 无记忆排序/打分 | 统一按余弦相似度排序，可叠加时间衰减 |

### 1.3 目标用户

- **Agent 会话**：每次 chat 时的 `MemoryManager.prefetch(query)` 召回更相关的记忆
- **反思引擎**：`MemoryManager.reflect()` 多天记忆汇聚时有语义聚类能力

---

## 2. 功能范围

### 2.1 MVP（P0 — 必须实现）

| 模块 | 功能 | 说明 |
|------|------|------|
| **向量化服务** | 封装 `sentence-transformers` 异步调用 | `TextEmbedder` 类，单例化 + LRU 缓存 |
| **向量存储** | 集成 `sqlite-vec` 作为向量索引后端 | 每个记忆条目存储 `(id, layer, content_hash, embedding, metadata)` |
| **混合检索** | `hybrid_search.py` 完整实现 | BM25 关键词 + 向量相似度，RRF 融合排序 |
| **prefetch 升级** | 语义召回替代关键词匹配 | `prefetch(query)` 返回语义 top-k 记忆 |

### 2.2 V1（P1 — 体验完善）

| 模块 | 功能 |
|------|------|
| **向量存储** | 支持多个 embedding 模型切换（配置项） |
| **索引** | 增量索引（新增条目立即可用，无需全量重建） |
| **时间衰减** | 检索结果按余弦相似度 + 时间衰减加权排序 |

### 2.3 V2（P2 — 高级功能）

| 模块 | 功能 |
|------|------|
| **索引** | HNSW 图索引（比 IVF 更快的近似搜索） |
| **跨层召回** | 一次向量检索同时召回 profile + facts + reflections 层的匹配项 |
| **在线学习** | 用户确认/忽略的记忆可反馈调整排序权重 |

---

## 3. 技术架构

```
                 query text
                     │
                     ▼
             TextEmbedder
    (sentence-transformers, 单例+LRU)
                     │
                     ▼
           ┌────────────────────┐
           │   HybridRetriever  │
           │  (RRF 融合排序)     │
           └───┬────────────┬───┘
               │            │
               ▼            ▼
        VectorIndex      BM25 Index
       (sqlite-vec)     (sqlite FTS5)
               │            │
               └─────┬──────┘
                     ▼
             Top-K 记忆条目
                     │
             随时间衰减加权
                     │
                     ▼
           MemoryManager.prefetch()
```

### 3.1 TextEmbedder

```python
# core/memory/builtin/embedder.py
from functools import lru_cache
import numpy as np

class TextEmbedder:
    """文本向量化服务，单例。"""

    _instance = None

    def __new__(cls, model_name: str = "all-MiniLM-L6-v2"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
            cls._instance._model_name = model_name
        return cls._instance

    async def embed(self, text: str) -> list[float]:
        """向量化单条文本。"""
        return await self._embed_batch([text])[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量向量化，带 LRU 缓存。"""
        # 实际推理在 executor 中运行避免阻塞事件循环
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._infer, texts)

    @lru_cache(maxsize=1000)
    def _infer(self, texts_tuple: tuple) -> list[list[float]]:
        texts = list(texts_tuple)
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model.encode(texts).tolist()
```

### 3.2 HybridRetriever

```python
# core/memory/builtin/hybrid_search.py

def hybrid_search(query: str, k: int = 10, alpha: float = 0.5) -> list[dict]:
    """BM25 + 向量相似度，RRF 融合。

    Args:
        query: 查询文本
        k: 召回数
        alpha: 向量权重 (0=仅BM25, 1=仅向量)
    """
    # 1. 向量检索 top-K*2
    query_vec = embedder.embed(query)
    vec_results = vector_index.search(query_vec, k=k * 2)

    # 2. BM25 检索 top-K*2
    bm25_results = bm25_index.search(query, k=k * 2)

    # 3. RRF 融合
    rrf_k = 60
    scores = {}
    for rank, item in enumerate(vec_results):
        scores[item["id"]] = scores.get(item["id"], 0) + alpha / (rrf_k + rank)
    for rank, item in enumerate(bm25_results):
        scores[item["id"]] = scores.get(item["id"], 0) + (1 - alpha) / (rrf_k + rank)

    # 4. 排序 + 截断
    ranked = sorted(scores.items(), key=lambda x: -x[1])[:k]
    # ...
```

---

## 4. 数据库设计

### sqlite-vec 向量存储表

```sql
CREATE TABLE memory_vectors (
    id TEXT PRIMARY KEY,
    layer TEXT NOT NULL,          -- profile/facts/reflections/sessions
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,                -- JSON
    created_at REAL NOT NULL,     -- Unix timestamp
    importance INTEGER DEFAULT 5, -- 1-10 重要性
    embedding VECTOR(384)         -- all-MiniLM-L6-v2 维度
);

-- 创建向量索引
CREATE INDEX idx_mv_layer ON memory_vectors(layer);
CREATE INDEX idx_mv_importance ON memory_vectors(importance);
```

---

## 5. 配置项

```yaml
# config.user.yaml
memory:
  embedding:
    model: "all-MiniLM-L6-v2"   # sentence-transformers 模型名
    device: "cpu"               # cpu / cuda / mps
    batch_size: 32              # 批量编码大小
  retrieval:
    top_k: 10                   # 默认召回数量
    alpha: 0.5                  # 向量/BM25 融合权重
    time_decay_days: 30         # 时间衰减半衰期
```

---

## 6. 测试要点

| 场景 | 说明 |
|------|------|
| 向量化 | `embed("hello")` 返回 384 维向量，归一化 |
| 混合检索 | 语义相关 > 关键词匹配的条目在结果中更靠前 |
| 增量索引 | 新 store 的条目立即可被检索 |
| 纯 BM25 降级 | embedding 模型加载失败 → 自动降级为纯 BM25 |
| 空结果 | 搜索无相关条目返回空列表 |
| 时间衰减 | 同样相似度下，新条目 > 旧条目 |

---

## 7. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | TextEmbedder + sqlite-vec 集成 + 向量索引写入 | 2d |
| P0+ | HybridRetriever RRF 融合 + prefetch 接入 | 2d |
| P1 | 增量索引 + 时间衰减 + 配置化模型选择 | 1d |
| P2 | HNSW 索引 + 跨层检索 + 反馈学习 | 2d |

---

## 8. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| sentence-transformers 模型下载慢 | 首次使用延迟 | 后台异步下载 + 进度提示；支持手动下载离线模型 |
| 向量索引占用内存（384维 × 10万条 ≈ 150MB） | 内存压力 | 可选 sqlite-vec 的磁盘模式；支持降级为纯 BM25 |
| embedding 推理阻塞事件循环 | Agent 响应变慢 | `run_in_executor` 异步推理；批量编码而非逐条 |
| 用户无 GPU 时推理慢 | 体验下降 | 默认 CPU 推理 + 可选 mini 模型（如 all-MiniLM-L6-v2 仅 80MB） |

---

## 9. 附录

### 9.1 依赖变更

| 依赖 | 当前 | 目标 |
|------|------|------|
| `sentence-transformers` | 否 → `memory` extra | 否 → 核心依赖中可选，默认推荐安装 |
| `sqlite-vec` | `vector` extra | 核心依赖 |

### 9.2 变更文件

| 文件 | 变更类型 |
|------|----------|
| `src/SmallShrimp/core/memory/builtin/provider.py` | 修改 — `BuiltinProvider` 集成向量存储 |
| `src/SmallShrimp/core/memory/builtin/hybrid_search.py` | 修改 — 完整实现混合检索 |
| `src/SmallShrimp/core/memory/builtin/embedder.py` | 新增 — TextEmbedder 封装 |
| `pyproject.toml` | 修改 — 依赖可选→推荐提升 |

### 9.3 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始草案 |
