# SmallShrimp 记忆层统一架构 v4

> 2026-06-18
> 整合 Provider 插件化 + 图谱记忆 + 萃取管线

---

## 一、设计目标

| 目标 | 说明 |
|------|------|
| **存储可切换** | 一行 config 切换 SQLite / Neo4j / 其他 |
| **萃取可选** | 小规模用 post-turn 文本提取，大规模用 LLM 三元组萃取 |
| **检索统一** | 无论底层是 SQLite 还是 Neo4j，上层检索接口一致 |
| **渐进增强** | 默认零配置跑 SQLite，需要时才开 Neo4j + 萃取 |

---

## 二、架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                        Agent Loop                           │
│                                                             │
│  Turn Start: profile/constraints 注入 → Prefetch 召回       │
│  Turn Exec:  LLM 调 recall_memory + ToolStateMemory 去重    │
│  Turn End:   Failure→reflections + Post-turn 提取           │
│                        │                                    │
│                        ▼                                    │
│              MemoryManager（编排层 + 融合）                   │
│    store → 写所有 provider                                  │
│    search → 并行查所有 provider, 结果融合排序                 │
│    get_prompt_blocks → 收集所有 provider 的 blocks           │
└──────┬─────────────────────────────────────────────────────┘
       │
       │  配置: memory.providers = [builtin, graph]  ← 支持多个
       │
       ├──────────────────────────┬──────────────────────────┐
       ▼                          ▼                          ▼
┌──────────────┐   ┌──────────────────────┐   ┌──────────────────┐
│ BuiltinProvider│   │   GraphProvider      │   │ 自定义 Provider   │
│ (SQLite+FTS5) │   │   (Neo4j + 萃取)     │   │ (用户自己写)      │
│              │   │                      │   │                  │
│ profile     │   │ entities/relations   │   │ 任意存储         │
│ constraints │   │ 多跳推理              │   │                  │
│ 轻量全文搜索 │   │ 实体关系查询          │   │                  │
└──────────────┘   └──────────────────────┘   └──────────────────┘
```

## 二、记忆类型与存储映射

### 2.1 完整性对照表

| # | 记忆类型 | 存储引擎 | 原因 | 查询模式 |
|---|---------|---------|------|---------|
| 1 | `profile` 用户画像 | **SQLite** | 简单 KV，每轮注入必须快 | 精确匹配 |
| 2 | `constraints` 硬性约束 | **SQLite** | 同 profile，需要原文保留 | 精确匹配 |
| 3 | `facts` 事实知识 | **SQLite + 向量** | 混合检索：FTS5 搜关键词 + 向量找相似 | 语义搜索 |
| 4 | `reflections` 经验教训 | **SQLite + 向量** | 同 facts | 语义搜索 |
| 5 | `projects` 项目上下文 | **SQLite** | 精确匹配为主 | 精确匹配 |
| 6 | `sessions` 对话历史 | **SQLite** | 时序追加，按时间查 | 时序查询 |
| 7 | `daily_logs` 日志 | **SQLite** | 纯追加，从不修改 | 日期范围 |
| 8 | `entities` 实体 | **Neo4j** | 图节点，带类型和属性 | 向量召回 + 邻居遍历 |
| 9 | `relations` 实体关系 | **Neo4j** | 图边，(主语,谓词,宾语) | 多跳遍历 |
| 10 | `events` 事件 | **Neo4j** | 关联实体，按时间线排序 | 实体→事件→时间线 |
| 11 | `insights` 高层洞察 | **Neo4j** | 关联实体，按主题收敛 | 主题匹配 + 实体回溯 |
| 12 | `tool_call_history` | **SQLite/Redis** | 临时状态，TTL 淘汰 | key-value |

### 2.2 为什么这样分

**SQLite 适合的（1~7）**：数据量小、关系简单、每轮都要读、需要精确匹配。

- profile/constraints 每轮都要注入 system prompt，延迟必须 < 1ms
- Neo4j 查询再快也要建连接 + 解析 Cypher，小数据量下 SQLite 绝对优势

**SQLite + 向量适合的（3~4）**：需要全文搜索又需要语义相似，混合检索已实现。

**Neo4j 适合的（8~11）**：数据之间有关联关系，查询需要多跳遍历。

- "用户学过 Python → Python 依赖 Flask → Flask 有漏洞" 这类推理，SQLite 做不到
- "Python 和 Flask 是什么关系" → Cypher 一条语句，SQLite 要 N 次 JOIN

### 2.3 写入路由

```python
_WRITE_ROUTES: dict[str, list[str]] = {
    # 只写 SQLite
    "profile": ["builtin"],
    "constraints": ["builtin"],
    "projects": ["builtin"],
    "sessions": ["builtin"],

    # 写 SQLite + 向量索引
    "facts": ["builtin"],
    "reflections": ["builtin"],

    # 只写 Neo4j
    "entities": ["graph"],
    "relations": ["graph"],
    "events": ["graph"],
    "insights": ["graph"],
}
```

不需要存两份。entity 相关数据只写 Neo4j，不写 SQLite，避免数据不一致。

### 2.4 检索路由

```python
def _resolve_search_providers(self, query: str, layer: str | None = None) -> list[str]:
    """根据查询决定查哪些 provider。"""
    if layer:
        return _WRITE_ROUTES.get(layer, ["builtin"])
    q = query.lower()
    if any(kw in q for kw in ["关系", "关联", "区别", "联系"]):
        return ["graph", "builtin"]
    if len(q) <= 6:
        return ["builtin"]
    return ["builtin", "graph"]
```

大多数查询走一个 provider 就够了，全查融合是兜底。

## 三、多 Provider MemoryManager

  providers:                                # 列表，支持多个
    - name: builtin                         # 第一个 = 默认写目标
      type: builtin
      builtin:
        memory_dir: workspace/memories

    - name: graph                           # 第二个 = 图查询
      type: graph
      graph:
        neo4j_uri: bolt://localhost:7687
        extraction:
          enabled: true

```

### 2.2 MemoryManager 多 Provider 编排

```python
class MemoryManager:
    """记忆管理器 — 编排多个 Provider，结果融合。"""

    def __init__(self, providers: list[MemoryProvider]):
        self._providers = providers
        self._primary = providers[0] if providers else None  # 默认写目标

    def store(self, layer: str, content: str, **kwargs) -> dict:
        """写入所有 provider（每层可能只落某个 provider）。"""
        for p in self._providers:
            if self._should_store(p, layer):
                p.store(layer, content, **kwargs)

    def search(self, query: str, **kwargs) -> list[dict]:
        """并行查所有 provider，结果融合去重后返回。"""
        results = []
        for p in self._providers:
            results.extend(p.search(query, **kwargs))
        # 融合排序: FTS5 分 + 向量分 + 图谱关系加权
        return self._fusion_rank(results)

    def get_prompt_blocks(self) -> list[PromptBlock]:
        """收集所有 provider 的注入块。"""
        blocks = []
        for p in self._providers:
            blocks.extend(p.get_prompt_blocks())
        return blocks

    def get_tools(self) -> list:
        """收集所有 provider 的工具。"""
        tools = []
        for p in self._providers:
            tools.extend(p.get_tools())
        return tools
```

### 2.3 写入路由 — 按层选择存储

不同种类的记忆适合不同的存储引擎，这是**多语言持久化（Polyglot Persistence）**：

| 记忆类型 | 最佳存储 | 原因 |
|---------|---------|------|
| `profile` / `constraints` | **SQLite** | 键值读写，简单快速，每轮都要注入 |
| `facts` / `reflections` | **SQLite + 向量索引** | 全文搜索 + 语义检索混合 |
| `sessions` / 每日日志 | **SQLite** | 时序追加，无复杂查询 |
| `entities` / `relations` | **Neo4j** | 实体关系图，多跳遍历 |
| `events` (时间线) | **Neo4j** | 按 event_time 排序，图关联 |
| `insights` (高层洞察) | **Neo4j** | 按主题收敛，关联实体 |
| 大规模文档知识库 | **向量数据库** | 纯语义检索，非结构化文本 |

写入路由定义（`_LAYER_ROUTES`）：

```python
_LAYER_ROUTES: dict[str, list[str]] = {
    # 写到 SQLite（全文搜索快，每轮注入用）
    "profile": ["builtin"],
    "constraints": ["builtin"],
    "sessions": ["builtin"],

    # 写到 SQLite + 向量（混合检索）
    "facts": ["builtin"],
    "reflections": ["builtin"],

    # 写到 Neo4j（知识图谱）
    "entities": ["graph"],
    "relations": ["graph"],
    "events": ["graph"],
    "insights": ["graph"],

    # 同时写到 SQLite + Neo4j（双写过渡期）
    "profile": ["builtin", "graph"],
    "constraints": ["builtin", "graph"],
}
```

### 2.4 检索路由 — 按查询路由到不同存储

检索时不是所有 provider 都要查，按查询意图路由：

```python
def _route_search(self, query: str) -> list[str]:
    """根据查询内容决定查哪些 provider。"""
    # 涉及实体的查询 → 查 Neo4j
    has_entity = detect_entity_query(query)  # "Python 和 Flask 什么关系"
    # 关键词查询 → 查 SQLite
    is_keyword = len(query.split()) <= 3    # "Python 特性"

    routes = []
    if is_keyword:
        routes.append("builtin")
    if has_entity:
        routes.append("graph")
    if not routes:
        routes = ["builtin", "graph"]  # 默认全查
    return routes
```

### 2.5 Prompt 块融合

当多个 provider 都注入内容时，按优先级拼接：

```
【系统规则】                    ← PriorityResolver
【硬性约束 Hard Constraints】   ← BuiltinProvider.constraints
【用户画像 User Profile】       ← BuiltinProvider.profile
【认知洞察 Insights】          ← GraphProvider.insights
【实体与关系 Entities】        ← GraphProvider.entities
【话题状态】                    ← TopicSegmenter
【任务进度】                    ← TodoTracker
```

---

## 三、GraphProvider 设计

### 3.1 层声明

```python
class GraphProvider(MemoryProvider):
    """Neo4j 知识图谱记忆提供者。"""

    profile = Layer("profile", "用户档案", searchable=True, inject="session")
    facts = Layer("facts", "事实知识", searchable="auto", inject=None)
    constraints = Layer("constraints", "硬性约束", searchable=True, inject="session")
    entities = Layer("entities", "实体", searchable="auto", inject=None)
    relations = Layer("relations", "关系", searchable="auto", inject=None)
    events = Layer("events", "事件", searchable=True, inject=None)
    insights = Layer("insights", "高层洞察", searchable="auto", inject="session")
```

### 3.2 配置

```yaml
memory:
  provider: graph                           # builtin | graph

  graph:
    neo4j_uri: bolt://localhost:7687
    neo4j_user: neo4j
    neo4j_password: xxx
    embedding_dims: 1024

    # 萃取（可选，默认关）
    extraction:
      enabled: false                        # 开则表示启用 LLM 萃取
      statement_model: gpt-4o-mini          # 陈述抽取用模型（省成本）
      triplet_model: gpt-4o-mini            # 三元组抽取用模型
      min_text_length: 20                   # 小于此长度不萃取
      max_chunk_length: 512                 # 分块大小（tokens）

    # 检索
    retrieval:
      top_k: 10
      recall_size: 20
      min_vector_score: 0.6
      vector_weight: 0.55
      fulltext_weight: 0.30
      importance_weight: 0.15
```

### 3.3 存储接口

```python
class MemoryProvider(ABC):
    # ── 核心（必须实现） ──
    def store(self, layer: str, content: str, **kwargs) -> dict
    def search(self, query: str, layer: str | None = None, **kwargs) -> list[dict]
    def list_all(self, layer: str | None = None, **kwargs) -> list[dict]
    def get_tools(self) -> list

    # ── GraphProvider 额外实现 ──
    def store_triplet(self, subject: str, predicate: str, object: str, **kwargs) -> dict
    def find_path(self, entity_a: str, entity_b: str, max_hops: int = 3) -> list[dict]
    def get_entity(self, name: str) -> dict | None
    def get_entity_neighbors(self, entity_id: str, max_hops: int = 1) -> list[dict]
```

---

## 四、萃取管线

管线分两步完成，文本输入到结构化三元组输出：

```
一段对话文本
  │
  ▼
第一步：分块 + 陈述抽取（1 次 LLM 调用）
  │  「我在腾讯工作，对花生过敏」
  │  → ["我在腾讯工作", "对花生过敏"]
  │
  ▼
第二步：三元组直接抽取（1 次 LLM 调用）
  │  → (用户) —[工作于]→ (腾讯)
  │  → (用户) —[过敏]→ (花生)
  │
  ▼
去重：同名同类型直接合并（不问 LLM）
  │
  ▼
写入 Neo4j
```

总共 2 次 LLM 调用。

### 开关控制

```python
class ExtractionPipeline:
    """萃取管线。由配置控制是否启用。"""

    def __init__(self, llm, embedder, config):
        self.enabled = config.get("enabled", False)
        self.llm = llm
        ...

    async def extract(self, user_id: str, text: str) -> ExtractionResult:
        if not self.enabled:
            return ExtractionResult()  # 空结果，不萃取
        if len(text) < self.min_text_length:
            return ExtractionResult()
        # 执行两步萃取
        ...
```

---

## 五、检索对比

| 场景 | BuiltinProvider (SQLite) | GraphProvider (Neo4j) |
|------|------------------------|----------------------|
| "用户喜欢什么" | FTS5 搜"喜欢" + 向量相似 | 向量召回到"偏好习惯"类实体 + 一跳关系遍历 |
| "Python 和 Flask 的关系" | FTS5 搜 Python、Flask 各自返回文本 | Cypher MATCH (p:Entity{name:'Python'})-[r]-(f:Entity{name:'Flask'}) |
| "用户对什么过敏" | 搜"过敏" → 返回 constraints 层文本 | 从用户节点沿 [:ALLERGY] 边找到 {花生} 节点 |
| "用户最近在学什么" | 搜"学" → 可能被大量混淆结果淹没 | 沿 [:LEARNING] 边找到技能实体，带时间属性 |

---

## 六、迁移路径

```
Phase 1（当前状态）
  └── BuiltinProvider (SQLite + FTS5)
       └── 已实现: entity_type / access_count / 层组去重

Phase 2（2~3 天）
  └── GraphProvider 骨架
       ├── Neo4j 连接 + Schema 初始化
       ├── store() / search() / list_all() 基本 CRUD
       ├── 配置切换: memory.provider = graph
       └── 测试: 单元测试 + 集成测试

Phase 3（2~3 天）
  └── 萃取管线
       ├── 两步萃取（陈述 + 三元组）
       ├── 同名同类型去重
       ├── ExtractionPipeline 类
       └── 配置开关: extraction.enabled = true

Phase 4（1~2 天）
  └── 检索增强
       ├── 一跳邻居遍历
       ├── 实体关系上下文组装
       └── Benchmark 对比
```

---

## 七、不做的

| 功能 | 原因 |
|------|------|
| Celery 异步 | 单用户场景同步够用，后续需要再加 |
| 社区聚类 LPA | 当前图谱规模不需要 |
| 四层完整溯源 (Dialogue→Chunk→Statement→Entity) | 简化成两层足够: 来源 + 实体 |
| 记忆动力学 (consolidation) | LRU 淘汰更务实 |
| jinja2 模板 | 沿用代码内常量，等 prompt 超 10 个再换 |

---

## 八、为什么这样设计

关键决策：**萃取和存储分离**。

- 萃取管线独立于存储后端 — 可以 SQLite + 萃取，也可以 Neo4j + 不了萃取
- 存储后端独立于萃取 — 用 Neo4j 但关掉萃取，只当 KV 用也行
- 配置驱动一切 — 用户按需叠加能力，不强制全量

```
                        萃取开               萃取关
SQLite            SQLite + 结构化提取      SQLite + 全文检索（当前）
Neo4j             Neo4j + 知识图谱        Neo4j + KV 存储
```
