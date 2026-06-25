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
| **零依赖存储** | SQLite 为唯一存储，去掉 .md 文件层，减少双写 I/O |

---

## 二、存储层统一

### 2.1 SQLite 为唯一存储

BuiltinProvider 过去以 `.md` 文件为真相源，SQLite 仅做检索索引。实际上读取路径从来不走文件，用户也几乎不打开文件编辑记忆，双写只有开销没有收益。

现在统一为 **SQLite 为唯一存储**，去掉 `.md` 文件层：

```
改前: 写 .md + 写 SQLite（双写，文件真相源从不被读取）
改后: 只写 SQLite（单写，WAL 日志保崩溃恢复）
```

影响：

| 维度 | 改前 | 改后 |
|------|------|------|
| 写入 I/O | 文件 + SQLite 双写 | 仅 SQLite 单写 |
| 真相源 | `.md` 文件 | SQLite + WAL |
| 记忆可编辑 | 文件手改（几乎不用） | 命令 `/edit` `/forget` |
| 数据迁移 | 需要同步文件和索引 | 一份 SQLite 完事 |

### 2.2 架构总览

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
│    store → 按路由写对应 provider                            │
│    search → 按路由查对应 provider, 结果融合排序              │
│    get_prompt_blocks → 收集所有 provider 的 blocks           │
└──────┬─────────────────────────────────────────────────────┘
       │
       │  配置: memory.providers = [builtin, graph]
       │
       ├──────────────────────────┬────────────────────────────┐
       ▼                          ▼                            ▼
┌──────────────────┐   ┌────────────────────────┐   ┌──────────────────┐
│ BuiltinProvider   │   │   GraphProvider         │   │ 自定义 Provider   │
│ (SQLite 唯一存储)  │   │   (图记忆, 两层存储)    │   │ (用户自己写)      │
│                   │   │                        │   │                  │
│ 检索分层:          │   ├── SQLiteGraphBackend    │   │ 任意存储         │
│  ① FTS5(零依赖)   │   │   (默认, 零依赖)         │   │                  │
│  ② +向量(sqllite) │   │   3 张表存图结构         │   │                  │
│  ③ +API 向量      │   │   SQL 递归 CTE 多跳     │   │                  │
│  ④ 专用向量库     │   │                        │   │                  │
└──────────────────┘   ├── Neo4jGraphBackend    │   └──────────────────┘
                       │   (进阶, 需 Docker)     │
                       │   原生图遍历 + 向量索引  │
                       │   Cypher 多跳查询       │
                       └────────────────────────┘
```

GraphProvider 本身不绑定存储，通过 Backend 策略实现两层存储切换：

```python
class GraphProvider(MemoryProvider):
    def __init__(self, config):
        backend_type = config.get("backend", "sqlite")  # sqlite | neo4j
        if backend_type == "neo4j":
            self._backend = Neo4jGraphBackend(config)
        else:
            self._backend = SQLiteGraphBackend(config)
```

用户配置决定：

```yaml
# 轻量版（默认，零额外依赖）
memory:
  providers:
    - name: builtin
    - name: graph
      graph:
        backend: sqlite          # 默认

# 进阶版（需要 Docker + Neo4j）
memory:
  providers:
    - name: builtin
    - name: graph
      graph:
        backend: neo4j
        neo4j_uri: bolt://localhost:7687
```

### 2.3 检索与 Embedding 渐进增强

检索和 embedding 分层组合，用户按需升级：

| 层级 | 检索引擎 | Embedding 源 | 依赖 | 场景 |
|------|---------|-------------|------|------|
| ① | FTS5 全文 | 无 | 无 | 纯关键词 |
| ② | FTS5 + sqlite-vec | 本地 sentence-transformers | `pip install smallshrimp[local]` | 本地语义 |
| ③ | FTS5 + sqlite-vec | OpenAI 兼容 API | API key | 云端语义 |
| ④ | 专用向量库 | OpenAI 兼容 API | Docker + API key | 大规模生产 |

```yaml
memory:
  embedding: local             # null | local | api://模型名 | milvus
```

检索自动降级：有 embedding 则混合检索，无则纯全文。
`EmbeddingProvider` 已是 ABC，新增后端只需实现 `encode(text) -> list[float]`。

### 2.4 升级兼容与重新索引

升级不影响已有数据，但旧数据不会自动获得新能力，需要一次主动重新索引：

| 升级路径 | 旧数据影响 | 操作 |
|---------|-----------|------|
| ① → ② 加本地向量 | 旧记忆无 embedding | `/rebuild-index` |
| ② → ③ 换 API 向量 | 旧 embedding 维度不同 | `/rebuild-index --force` |
| ③ → ④ 加专用向量库 | 元数据在 SQLite，向量在旧库 | 迁移脚本 |
| 不加图 → 加图记忆 | 旧实体未萃取 | 不回溯，新对话自动萃取 |

`/rebuild-index` 遍历 `memory_index` 全部记录，重新计算 embedding 写入向量表。**不跑不影响已有功能**——FTS5 关键词搜索一直在，旧数据始终能被搜到。

---

## 三、置信度管线 — 写入把关

### 3.1 问题：写入入口没有统一标准

当前有四条写入路径，各自为政：

| 写入路径 | 触发者 | 有无过滤 | 置信度 |
|---------|--------|---------|-------|
| `remember_*` 工具 | LLM 自己决定调不调 | ❌ LLM 说啥就写啥 | 未知 |
| `failure_learner` | 工具执行失败计数 | ✅ 阈值过滤 | 高 |
| `sync_turn` → sessions | 每轮自动 | ✅ 只写日志，不进长期记忆 | — |
| 外部直接调 `store()` | 任意代码 | ❌ 无 | 未知 |

最大的问题是 **LLM 调 `remember_*` 时，它自己判断"这值得记住"，但这个判断没有经过任何校验。** LLM 还经常不记得调这些工具。

### 3.2 方案：置信度管线

核心思路：**在 `MemoryManager.store()` 之前加一层 `ConfidenceGate`，把所有写入请求收口**，用信号强度决定该不该写、写到哪里。

```
工具层 / Agent 内部调用
       │
       ▼
┌─────────────────────────────────────┐
│          ConfidenceGate              │
│                                     │
│  输入: layer, content, signals      │
│                                     │
│  1. 信号识别（SignalDetector）       │
│     · 用户纠正 → 0.9                │
│     · 失败模式 → 0.8                │
│     · 重复信息 → 0.7                │
│     · 关键词触发 → 0.5              │
│     · LLM 自觉 → 0.3                │
│                                     │
│  2. 置信度裁决（resolve）            │
│     confidence = max(signals)       │
│                                     │
│  3. 路由（route）                    │
│     ≥ 0.7 → 直接写入 target layer    │
│     ≥ 0.4 → 暂存 staging 区         │
│     < 0.4 → 丢弃                    │
│                                     │
└─────────────────────────────────────┘
       │
       ▼
   MemoryProvider.store()
```

### 3.3 组件详解

#### SignalDetector — 信号识别

从输入上下文中提取多个独立的置信度信号。每个信号有明确的触发条件，不依赖 LLM 判断。

```python
class SignalDetector:
    """从 store() 的输入上下文提取多个置信度信号。"""

    # 确定性信号（高置信度）
    def detect_correction(user_msg: str, assistant_msg: str) -> float:
        """用户纠正检测。
        触发条件: 用户在下一轮指出 Agent 的错误
        关键词: "不对" "不是" "错了" "应该说" "更正"
        置信度: 0.9
        """

    def detect_failure(tool_results: list) -> float:
        """工具执行失败。
        触发条件: 当前 turn 的工具调用有 error
        置信度: 0.8
        现状: FailureLearner 已有此能力，直接复用
        """

    def detect_repetition(content: str, existing: list) -> float:
        """用户重复提到同一信息。
        触发条件: 新 content 与已有记忆相似度 > 0.8
        置信度: 0.7
        注意: 非精确去重，而是「同一信息出现多次应提升」
        """

    # 弱信号（低置信度）
    def detect_keyword(content: str) -> float:
        """关键词触发。
        触发条件: content 包含 "我是" "记住" "我在" "我的" "不要" 等
        置信度: 0.5
        """

    def detect_llm_call(content: str) -> float:
        """LLM 自觉调用 remember_*。
        触发条件: 来自 LLM 生成的 tool call
        置信度: 0.3
        说明: LLM 觉得重要不一定真重要，给它低分去 staging
        """
```

#### ConfidenceGate — 裁决与路由

```python
class ConfidenceGate:
    THRESHOLD_DIRECT = 0.7    # 直接写入正式层
    THRESHOLD_STAGING = 0.4   # 暂存待强化
    THRESHOLD_DISCARD = 0.0   # 丢弃

    def judge(self, layer: str, content: str, signals: dict[str, float]) -> RoutingDecision:
        """综合所有信号做裁决。"""
        confidence = max(signals.values()) if signals else 0.0

        if confidence >= self.THRESHOLD_DIRECT:
            return RoutingDecision(
                action="write",
                target_layer=layer,
                confidence=confidence,
            )
        elif confidence >= self.THRESHOLD_STAGING:
            return RoutingDecision(
                action="stage",
                target_layer=layer,
                confidence=confidence,
            )
        else:
            return RoutingDecision(
                action="discard",
                confidence=confidence,
            )
```

#### StagingArea — 暂存与提升

暂存起来的记录不直接进长期记忆，而是等**证据累积**到了再提升：

```python
class StagingArea:
    """暂存低置信度记忆，累积到阈值后提升到正式层。"""

    def __init__(self, db: sqlite3.Connection):
        self._conn = db
        # staging 表: id, content_hash, content, layer, count, first_seen, last_seen
        self._ensure_table()

    def stage(self, content: str, layer: str, confidence: float, **kwargs) -> str:
        """暂存一条记录。如果同内容已存在，bump 计数。"""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        existing = self._find_by_hash(content_hash)
        if existing:
            self._bump(existing["id"])
            return self._promote_if_ready(existing["id"], content_hash, layer)
        return self._insert(content_hash, content, layer, confidence, **kwargs)

    def _promote_if_ready(self, row_id: int, content_hash: str, layer: str) -> str | None:
        """同内容出现 2 次 → 提升到正式层。"""
        row = self._conn.execute(
            "SELECT count FROM staging WHERE id = ?", (row_id,)
        ).fetchone()
        if row and row[0] >= 2:
            self._move_to_layer(content_hash, layer)
            self._remove(content_hash)
            return layer
        return None
```

### 3.4 整合位置

```
agent.py 的 turn_end 流程
    │
    ├── failure_learner.observe_turn()
    │       └── 已有确定性信号 → 带 confidence=0.8 调 ConfidenceGate → 直接写
    │
    ├── LLM 生成了 remember_* tool call
    │       └── 带 confidence=0.3 调 ConfidenceGate → staging（除非有额外信号叠加）
    │
    ├── sync_turn()
    │       └── 只写 sessions 日志，不进入 ConfidenceGate
    │
    └── 新: 快速规则扫描（写 staging）
            └── 扫描 user_msg 关键词模式："我是" "我在" "记住" 等
                → 暂存到 staging，等第二次出现再提升
```

MemoryManager 的改动最小：

```python
class MemoryManager:
    def __init__(self, provider_or_dir):
        # 现有初始化 + 新增
        self._confidence_gate = ConfidenceGate()
        self._signal_detector = SignalDetector()
        self._staging = StagingArea()  # 复用同一 SQLite

    def store(self, layer: str, content: str, **kwargs) -> dict:
        # 新: 走置信度管线
        signals = self._signal_detector.detect_all(
            layer=layer, content=content, **kwargs
        )
        decision = self._confidence_gate.judge(layer, content, signals)

        if decision.action == "discard":
            return {"action": "discard", "content": content, "confidence": decision.confidence}

        if decision.action == "stage":
            self._staging.stage(content, decision.target_layer, decision.confidence, **kwargs)
            return {"action": "staged", "content": content, "confidence": decision.confidence}

        # write — 直接穿透到 provider
        return self._provider.store(decision.target_layer, content, **kwargs)
```

### 3.5 置信度与现有字段的关系

现在 `MemoryRecord` 已有 `confidence` 字段（0.0~1.0），但它的含义不明确，实际上从未被使用。

重新定义：

| 字段 | 含义 | 设置者 |
|------|------|--------|
| `importance` | 这条记忆的重要程度（1-10），影响排序权重 | ConfidenceGate 根据信号设置 |
| `confidence` | 这条记忆的可靠程度（0.0-1.0），影响是否出现在 prompt | 写入时由 ConfidenceGate 设定 |
| `access_count` | 检索命中次数，热度浮出 | 检索时自动回写 |

置信度 ≤ 0.5 的记录在 prompt 注入时标记为"待确认"：

```
- 用户好像对花生过敏（待确认，LLM 推测）
- 用户对花生过敏（已确认，用户明确说明）
```

### 3.6 不做 LLM 后置提取的原因

文档 2.2 节已阐明：**post-turn 提取依赖 LLM，不稳定且昂贵。**

置信度管线的替代思路：

- **LLM 调 `remember_*` 本身是一个信号**，但给它低置信度，走 staging，等第二次出现才提升
- **规则扫描比 LLM 提取便宜得多**，关键词 + 正则几毫秒跑完
- **确定性信号（correction/failure）直接写**，不走 LLM
- **Evidence accumulation 取代一次性判断**——不需要 LLM 一次判断准不准，只需要 LLM 提取，累积归置信度管

### 3.7 改动范围

| 改动 | 范围 | 复杂度 |
|------|------|--------|
| 新增 `SignalDetector` | 新文件 `src/SmallShrimp/core/memory/confidence.py` | 低 |
| 新增 `ConfidenceGate` | 同上 | 低 |
| 新增 `StagingArea` | 同上 | 中 |
| 修改 `MemoryManager.store()` | 插入 ConfidenceGate 调用 | 低 |
| 修改 `remember_*` 工具 | 传递信号来源信息 | 低 |

## 四、记忆类型与存储映射

### 4.1 完整性对照表

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

### 4.2 为什么这样分

**SQLite 适合的（1~7）**：数据量小、关系简单、每轮都要读、需要精确匹配。

- profile/constraints 每轮都要注入 system prompt，延迟必须 < 1ms
- Neo4j 查询再快也要建连接 + 解析 Cypher，小数据量下 SQLite 绝对优势

**SQLite + 向量适合的（3~4）**：需要全文搜索又需要语义相似，混合检索已实现。

**Neo4j 适合的（8~11）**：数据之间有关联关系，查询需要多跳遍历。

- "用户学过 Python → Python 依赖 Flask → Flask 有漏洞" 这类推理，SQLite 做不到
- "Python 和 Flask 是什么关系" → Cypher 一条语句，SQLite 要 N 次 JOIN

### 4.3 写入路由

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

### 4.4 检索路由

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

## 五、多 Provider MemoryManager

### 5.1 配置

memory:
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

### 5.2 MemoryManager 多 Provider 编排

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

### 5.3 写入路由 — 按层选择存储

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

### 5.4 检索路由 — 按查询路由到不同存储

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

### 5.5 Prompt 块融合

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

## 六、GraphProvider 设计

### 6.1 层声明

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

### 6.2 配置

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

### 6.3 存储接口

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

## 七、萃取管线

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

### 7.1 开关控制

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

## 八、检索对比

| 场景 | BuiltinProvider (SQLite) | GraphProvider (Neo4j) |
|------|------------------------|----------------------|
| "用户喜欢什么" | FTS5 搜"喜欢" + 向量相似 | 向量召回到"偏好习惯"类实体 + 一跳关系遍历 |
| "Python 和 Flask 的关系" | FTS5 搜 Python、Flask 各自返回文本 | Cypher MATCH (p:Entity{name:'Python'})-[r]-(f:Entity{name:'Flask'}) |
| "用户对什么过敏" | 搜"过敏" → 返回 constraints 层文本 | 从用户节点沿 [:ALLERGY] 边找到 {花生} 节点 |
| "用户最近在学什么" | 搜"学" → 可能被大量混淆结果淹没 | 沿 [:LEARNING] 边找到技能实体，带时间属性 |

---

## 九、图存储 Backend 对比

| 维度 | SQLiteGraphBackend（默认） | Neo4jGraphBackend（进阶） |
|------|--------------------------|-------------------------|
| 额外依赖 | 无 | Docker + Neo4j 5 |
| 安装时间 | 0 | ~5 分钟 |
| 数据量上限 | ~10 万条 | 千万级以上 |
| 多跳查询 | SQL 递归 CTE，深度 ≤ 5 | Cypher 原生图遍历 |
| 向量索引 | 共用 SQLite FTS5 | 原生向量索引 |
| 适用场景 | 个人使用、小项目 | 生产环境、大规模 |

## 十、迁移路径

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

## 十一、不做的

| 功能 | 原因 |
|------|------|
| Celery 异步 | 单用户场景同步够用，后续需要再加 |
| 社区聚类 LPA | 当前图谱规模不需要 |
| 四层完整溯源 (Dialogue→Chunk→Statement→Entity) | 简化成两层足够: 来源 + 实体 |
| 记忆动力学 (consolidation) | LRU 淘汰更务实 |
| jinja2 模板 | 沿用代码内常量，等 prompt 超 10 个再换 |

---

## 十二、为什么这样设计

关键决策：**萃取和存储分离**。

- 萃取管线独立于存储后端 — 可以 SQLite + 萃取，也可以 Neo4j + 不了萃取
- 存储后端独立于萃取 — 用 Neo4j 但关掉萃取，只当 KV 用也行
- 配置驱动一切 — 用户按需叠加能力，不强制全量

```
                        萃取开               萃取关
SQLite            SQLite + 结构化提取      SQLite + 全文检索（当前）
Neo4j             Neo4j + 知识图谱        Neo4j + KV 存储
```
