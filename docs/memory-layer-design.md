# SmallShrimp 记忆层设计文档

> 设计决策记录。
---

## 目录

1. [设计目标与原则](#1-设计目标与原则)
2. [设计决策记录](#2-设计决策记录)
3. [架构总览](#3-架构总览)
4. [Provider 接口定义](#4-provider-接口定义)
5. [内置 Provider（SQLiteBuiltinProvider）](#5-内置-providersqlitebuiltinprovider)
6. [5 层记忆定义](#6-5-层记忆定义)
7. [自动写入管线](#7-自动写入管线)
8. [存储层（SQLite）](#8-存储层sqlite)
9. [召回与排序](#9-召回与排序)
10. [去重与合并策略](#10-去重与合并策略)
11. [Agent 集成点](#11-agent-集成点)
12. [配置项](#12-配置项)
13. [测试集规划](#13-测试集规划)
14. [实现优先级](#14-实现优先级)

---

## 1. 设计目标与原则

### 目标

为 SmallShrimp Agent 提供跨会话、跨项目的长期记忆能力，确保：

1. **不丢失** — 用户纠正、失败模式等信号自动写入，不依赖 LLM 自觉
2. **不遗忘** — 相关记忆在需要时自动召回，不依赖 LLM 主动查询
3. **不分心** — 记忆注入受 token 预算控制，不滥用上下文窗口
4. **不被污染** — 写入前安全扫描，防止注入攻击

### 原则

1. **问题驱动** — 每个设计决策对应一个已发现的真实代码问题
2. **测试先行** — 每个功能点有对应的测试集验证
3. **Provider 插件化** — 存储后端可插拔，内置 SQLite 为默认实现
4. **自动 > 手动** — 优先自动写入/召回，工具调用作为补充

---

## 2. 设计决策记录

| 决策项 | 选择 | 依据 |
|--------|------|------|
| 架构路线 | **Provider 插件化** | 灵活性，后续可接入 Honcho/Mem0 等 |
| 分层数量 | **保持 5 层，重新定义边界** | 现有代码已适配 5 层结构 |
| 存储后端 | **SQLite** | 结构化查询、索引、容量管理、并发安全 |
| 自动写入 | **Intent Detection + Post-turn Review 双通道** | / |
| Provider 接口 | **需要** | 允许第三方后端，当前内置实现 |
| 召回策略 | **Lexical + Query Expansion + 时间衰减** | 快速、可预测，不依赖外部 API |
| 去重策略 | **精确 → 子串 → 模糊三阶段** | 平衡准确率与召回率 |
| ID 格式 | **UUID4** | 全局唯一，无碰撞风险 |

---

## 3. 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent Loop                                   │
│                                                                     │
│  Turn Start:                                                        │
│    User Message                                                     │
│      ├─ Intent Detection → 命中则注入 hint                          │
│      ├─ Provider.system_prompt_block() → 冻结快照入 system          │
│      └─ Provider.prefetch(query) → 自动召回注入上下文               │
│                                                                     │
│  Turn Execution:                                                    │
│      ├─ LLM 可用 memory_manage 工具读写                             │
│      └─ 工具结果经 Scanner 安全过滤                                  │
│                                                                     │
│  Turn End:                                                          │
│      ├─ Provider.sync_turn(user, assistant) → 持久化本轮             │
│      ├─ Correction Signal → 直接写 profile                          │
│      ├─ Failure Signal → 直接写 reflections                         │
│      └─ Intent Signal → review fork                                 │
│                                                                     │
│  Session End:                                                       │
│      ├─ consolidate() → 合并近重复                                  │
│      ├─ compact() → LRU 淘汰                                        │
│      └─ sessions 层自动归档                                         │
└─────────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        MemoryManager                                │
│  编排所有 Provider，不直接操作存储                                    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 持有多个 Provider                                            │    │
│  │                                                             │    │
│  │  ┌────────────────────┐  ┌────────────────────┐            │    │
│  │  │  BuiltinProvider   │  │  ExternalProvider  │            │    │
│  │  │  (SQLite, 默认)    │  │  (如 Honcho)       │            │    │
│  │  └────────┬───────────┘  └────────────────────┘            │    │
│  │           │                                                 │    │
│  │           ▼                                                 │    │
│  │  ┌───────────────────────────────────────────────────┐     │    │
│  │  │  MemoryProvider (ABC)                            │     │    │
│  │  │  ├─ name / is_available / initialize / shutdown  │     │    │
│  │  │  ├─ system_prompt_block() → str                  │     │    │
│  │  │  ├─ prefetch(query) → list[dict]                 │     │    │
│  │  │  ├─ queue_prefetch(query)                        │     │    │
│  │  │  ├─ sync_turn(user, assistant, session_id, msgs) │     │    │
│  │  │  ├─ get_tool_schemas() → list[dict]              │     │    │
│  │  │  ├─ handle_tool_call(name, args) → str           │     │    │
│  │  │  ├─ on_turn_start / on_session_end               │     │    │
│  │  │  └─ on_memory_write()                            │     │    │
│  │  └───────────────────────────────────────────────────┘     │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Provider 接口定义

### MemoryProvider ABC

```python
class MemoryProvider(ABC):
    """记忆提供者抽象基类。所有后端必须实现此接口。"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    # ── 生命周期 ──

    @abstractmethod
    def initialize(self, session_id: str, config: dict | None = None) -> None: ...

    @abstractmethod
    def shutdown(self) -> None: ...

    # ── System Prompt ──

    @abstractmethod
    def system_prompt_block(self) -> str:
        """返回注入 system prompt 的静态文本块。
        每轮调用一次，返回冻结快照（不包含本轮刚写入的内容）。
        """

    # ── 前置召回 ──

    @abstractmethod
    def prefetch(self, query: str, session_id: str = "") -> list[dict]: ...

    def queue_prefetch(self, query: str, session_id: str = "") -> None:
        """后台预加载（默认空实现）。"""

    # ── 后置同步 ──

    @abstractmethod
    def sync_turn(self, user_content: str, assistant_content: str,
                  session_id: str = "", messages: list[dict] | None = None) -> None: ...

    # ── 工具接口 ──

    @abstractmethod
    def get_tool_schemas(self) -> list[dict]: ...

    @abstractmethod
    def handle_tool_call(self, tool_name: str, args: dict) -> str: ...

    # ── 可选钩子 ──

    def on_turn_start(self, message: str, session_id: str = "") -> None: ...
    def on_session_end(self, session_id: str) -> None: ...
    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: dict | None = None) -> None: ...
```

### MemoryManager（编排层）

```python
class MemoryManager:
    """编排所有 Provider，不直接操作存储。"""

    def __init__(self):
        self._providers: list[MemoryProvider] = []
        self._builtin: MemoryProvider | None = None

    def add_provider(self, provider: MemoryProvider, is_builtin: bool = False) -> None: ...

    def system_prompt_block(self) -> str:
        """收集所有 Provider 的块，合并返回。"""

    def prefetch(self, query: str, session_id: str = "") -> list[dict]:
        """从所有 Provider 召回，合并排序后返回。"""

    def sync_turn(self, user_content: str, assistant_content: str,
                  session_id: str = "", messages: list[dict] | None = None) -> None: ...

    def handle_tool_call(self, tool_name: str, args: dict) -> str:
        """路由到对应 Provider 执行工具。"""

    def on_session_end(self, session_id: str) -> None: ...
    def shutdown_all(self) -> None: ...
```

---

## 5. 内置 Provider（SQLiteBuiltinProvider）

### 内部模块拆分

```
memory/
├── __init__.py
├── provider.py          # MemoryProvider ABC
├── manager.py           # MemoryManager 编排
├── builtin/
│   ├── __init__.py
│   ├── provider.py      # SQLiteBuiltinProvider 实现
│   ├── store.py         # SQLite CRUD + 容量管理
│   ├── ranker.py        # 召回排序 + Query Expansion
│   ├── scanner.py       # 安全扫描
│   ├── intent.py        # 用户意图检测
│   └── models.py        # 数据模型
├── tools/
│   └── memory_tool.py   # LLM 可用记忆工具
```

### 双通道自动写入

```
Turn Start:
  User Message
      │
      ├── Intent Detection ──── HIGH ──→ 注入 hint → LLM 本轮响应
      │                                   ↓
      │                            Post-turn review fork
      │                              → 调用 memory_manage 写入
      │
      └── Correction Detection ── HIGH ──→ 直接写入 profile
                                            (不经过 LLM)

Turn End:
      └── FailureLearner ── threshold ──→ 直接写入 reflections
                                            (不经过 LLM)
```

---

## 6. 5 层记忆定义

### 分层总览

| 层 | 存什么 | 默认 imp | 注入方式 | 生命周期 | 单条上限 |
|-----|--------|---------|---------|---------|---------|
| **profile** | 用户身份、长期偏好、沟通语言、纠正 | 10 | system prompt 每轮注入 | 永久 | 500 chars |
| **facts** | 跨会话知识（技术栈、工具用法、约定） | 5 | prefetch 按需召回 | 永久 | 500 chars |
| **projects** | 项目上下文（路径、命令、技术栈） | 6 | prefetch 按需召回 | 与项目绑定 | 500 chars |
| **reflections** | Agent 反思（失败模式、行为修正） | 6 | sys prompt 高优 + prefetch | 永久 | 500 chars |
| **sessions** | 短期会话上下文 | 3 | 不跨会话 | 自动归档(7天) | 2000 chars |

### 注入预算

| 通道 | 来源 | 上限 |
|------|------|------|
| System Prompt 固定 | profile(top-10) + reflections(top-5) | ~800 chars |
| Prefetch 按需 | facts/projects/reflections | ~1500 chars |
| LLM 工具 | 全部层 | 不限（LLM 自行调） |

### system_prompt_block 策略

```python
def system_prompt_block(self) -> str:
    """冻结快照：profile + 高优 reflections。"""
    blocks = []
    profiles = self.store.list(layer="profile", limit=10)
    if profiles:
        blocks.append("## User Profile\n" + "\n".join(f"- {r['content']}" for r in profiles))
    reflections = self.store.list(layer="reflections", limit=5)
    if reflections:
        blocks.append("## Agent Reflections\n" + "\n".join(f"- {r['content']}" for r in reflections))
    return "\n\n".join(blocks)
```

---

## 7. 自动写入管线

### 7.1 Correction → Profile

```python
correction = detect_correction_combined(message, prev_assistant)
if correction and correction.confidence == CorrectionConfidence.HIGH:
    memory_manager.handle_tool_call("remember_profile", {
        "content": extract_correction_content(message, correction),
        "source": "correction",
    })
```

### 7.2 Failure → Reflections

```python
notes = self.agent.failure_learner.observe_turn(self._turn_failures)
for note in notes:
    self.state.add_message(SystemMessage(content=note))
    memory_manager.handle_tool_call("remember_reflection", {
        "content": note,
        "importance": 7,
        "source": "failure_learner",
    })
```

### 7.3 Intent Detection → Review Fork

```python
# TurnPreparer
intent = detect_memory_intent(user_message)
if intent.triggered and intent.confidence == "high":
    hint = render_memory_intent_review_hint(intent)
    user_message = f"{hint}\n\n---\n\n{user_message}"

# PostTurnPipeline
if _should_trigger_review(turn_outcome, intent):
    _run_review_turn(messages, intent)
```

---

## 8. 存储层（SQLite）

### 表结构

```sql
CREATE TABLE IF NOT EXISTS memory_records (
    id              TEXT PRIMARY KEY,
    content         TEXT NOT NULL,
    layer           TEXT NOT NULL CHECK(layer IN (
                        'profile','facts','projects','reflections','sessions'
                    )),
    source          TEXT NOT NULL DEFAULT 'auto'
                        CHECK(source IN ('explicit','review','import','auto',
                                         'correction','failure_learner')),
    importance      INTEGER NOT NULL DEFAULT 5 CHECK(importance BETWEEN 0 AND 10),
    confidence      REAL NOT NULL DEFAULT 1.0 CHECK(confidence BETWEEN 0.0 AND 1.0),
    recall_count    INTEGER NOT NULL DEFAULT 0,
    pinned          INTEGER NOT NULL DEFAULT 0,
    archived        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_recalled_at TEXT
);

CREATE INDEX idx_memory_layer ON memory_records(layer);
CREATE INDEX idx_memory_pinned ON memory_records(pinned);
CREATE INDEX idx_memory_importance ON memory_records(importance DESC);
CREATE INDEX idx_memory_recall ON memory_records(recall_count DESC);
```

### MemoryStore CRUD

```python
class MemoryStore:
    def __init__(self, db_path: str): ...

    def add(self, content: str, layer: str, *, source="auto",
            importance=None, confidence=1.0, pinned=False) -> dict: ...
    def get(self, record_id: str) -> dict | None: ...
    def list(self, layer: str | None = None, *, limit=50,
             include_archived=False, pinned_only=False) -> list[dict]: ...
    def search(self, query: str, layer: str | None = None, *,
               limit=10, include_archived=False) -> list[dict]: ...
    def delete(self, record_id: str, *, force=False) -> bool: ...
    def pin(self, record_id: str) -> bool: ...
    def unpin(self, record_id: str) -> bool: ...
    def archive(self, record_id: str) -> bool: ...
    def unarchive(self, record_id: str) -> bool: ...
    def touch_recall(self, record_ids: list[str]) -> None: ...
    def consolidate(self, threshold=0.80, layer: str | None = None) -> int: ...
    def compact(self) -> int: ...
    def stats(self) -> dict: ...
    def close(self) -> None: ...
```

### 容量管理

| 参数 | 默认 | 说明 |
|------|------|------|
| max_entries_per_layer | 500 | 每层最大非归档数 |
| max_entry_chars | 500 | 单条最大字符数 |
| compact_threshold | 0.7 | 触发 compact 的容量使用率 |

LRU 淘汰：按 (importance ASC, recall_count ASC, updated_at ASC) 排序，优先淘汰 auto 来源，pinned/explicit 不淘汰。

---

## 9. 召回与排序

### 召回管线

```
Query → [Query Expansion] → [Lexical Recall (limit×3)] → [Cross-layer Merge] → [Budget Trim] → Top-N
```

### Query Expansion

```python
_QUERY_EXPANSIONS = {
    "沟通": ("回复", "语气", "风格", "简短", "详细"),
    "偏好": ("喜欢", "不喜欢", "希望", "习惯", "prefer"),
    "代码": ("编码", "编程", "开发", "写代码", "code"),
    "错误": ("失败", "报错", "异常", "error", "bug"),
    "项目": ("仓库", "repo", "工程", "proj"),
    "配置": ("设置", "config", "setting", "cfg"),
    "路径": ("目录", "文件夹", "folder", "dir"),
}
```

### 排序公式

```python
def _rank_memory(query: str, content: str) -> float:
    score = 0.0
    if query.lower() in content.lower():
        score += 8.0                              # 子串匹配
    query_terms = _word_terms(query)
    content_terms = _word_terms(content)
    if query_terms:
        score += 4.0 * (len(query_terms & content_terms) / len(query_terms))  # 词重叠
    query_grams = _char_ngrams(query)
    content_grams = _char_ngrams(content)
    if query_grams:
        score += 3.0 * (len(query_grams & content_grams) / len(query_grams))  # ngram
    ratio = SequenceMatcher(None, query.lower(), content.lower()).ratio()
    if ratio >= 0.12:
        score += 2.0 * ratio                       # SequenceMatcher
    return score

def _quality_score(record: dict, query_score: float) -> float:
    days = (datetime.now() - datetime.fromisoformat(record["updated_at"])).days
    decay = math.exp(-0.01 * days)                 # 时间衰减
    return query_score * (record["importance"] / 10) * record["confidence"] * decay
```

---

## 10. 去重与合并策略

### store() 时去重

三阶段检测，仅在同层内进行：

```python
def _find_duplicate(self, content: str, layer: str) -> dict | None:
    for existing in self.store.list(layer=layer):
        # Stage 1: 精确匹配
        if content.strip().lower() == existing["content"].strip().lower():
            return existing
        # Stage 2: 子串匹配（短串是长串的子串）
        shorter, longer = sorted(
            [content.strip().lower(), existing["content"].strip().lower()], key=len
        )
        if len(shorter) >= 4 and shorter in longer:
            return existing
        # Stage 3: 模糊匹配（双条件）
        rank = _rank_memory(content, existing["content"])
        seq = SequenceMatcher(None, content.lower(), existing["content"].lower()).ratio()
        if rank >= 7.0 and seq >= 0.92:
            return existing
    return None
```

合并规则：保留更长的 content，importance/confidence 取 max，recall_count 求和。

### consolidate() 合并

- 仅同层
- 跳过 pinned
- 胜出者优先级：pinned > explicit > import > review > auto > correction > failure_learner
- 败者归档（不删除）

---

## 11. Agent 集成点

### PromptBuilder

```python
def _build_profile_block(self, state) -> str:
    provider = state.agent.memory_manager._builtin
    if not provider:
        return ""
    return provider.system_prompt_block()
```

### Agent.chat()

```python
async def chat(self, message: str) -> str:
    # Turn Start
    intent = detect_memory_intent(message)
    correction = detect_correction_combined(message, prev_assistant)
    if correction and correction.confidence == CorrectionConfidence.HIGH:
        self.memory_manager.handle_tool_call("remember_profile", ...)
    if intent.triggered:
        message = f"{render_memory_intent_hint(intent)}\n\n{message}"

    prefetched = self.memory_manager.prefetch(message, session_id=self.session_id)
    # → 注入 build_messages()

    # ... LLM + Tools ...

    # Turn End
    notes = self.agent.failure_learner.observe_turn(self._turn_failures)
    for note in notes:
        self.memory_manager.handle_tool_call("remember_reflection", ...)

    self.memory_manager.sync_turn(
        user_content=message, assistant_content=response,
        session_id=self.session_id, messages=self.state.messages,
    )

    if _should_trigger_review(intent, correction):
        await self._run_review_turn()
    return response
```

### Tool Schemas

```python
tools = [
    ToolSchema("recall_memory", "检索记忆"),
    ToolSchema("remember_fact", "保存事实"),
    ToolSchema("remember_project", "保存项目上下文"),
    ToolSchema("remember_reflection", "保存反思"),
    ToolSchema("remember_profile", "保存用户画像"),
    ToolSchema("forget_memory", "删除记忆"),
    ToolSchema("consolidate_memories", "合并重复记忆"),
]
```

---

## 12. 配置项

```yaml
memory:
  enabled: true
  provider: builtin

  builtin:
    db_path: workspace/memories/memory.db
    max_entries_per_layer: 500
    max_entry_chars: 500
    compact_threshold: 0.7
    max_profile_in_prompt: 10
    max_reflections_in_prompt: 5
    max_prefetch_results: 5
    max_prefetch_chars: 1500
    session_retention_days: 7
    session_max_turns_in_context: 8
    intent_detection_enabled: true
    correction_auto_write: true
    failure_auto_write: true
    post_turn_review_enabled: true
```

---

## 13. 测试集规划

| 测试文件 | 内容 | 对应 |
|---------|------|------|
| `test_memory_provider.py` | Provider ABC 接口契约 | 架构 |
| `test_memory_store.py` | SQLite CRUD + 容量 + 并发 | 存储 |
| `test_memory_dedup.py` | 去重与合并策略 | 问题 4/6 |
| `test_memory_ranking.py` | 排序 + Query Expansion + 衰减 | 问题 5/10 |
| `test_memory_intent.py` | Intent Detection | 自动写入 |
| `test_memory_scanner.py` | 安全扫描 | 安全 |
| `test_memory_auto_write.py` | 自动写入 Correction/Failure | 问题 1/2 |
| `test_memory_inject.py` | 自动预召回 + Token 预算 | 问题 3/9 |
| `test_memory_tools.py` | LLM 工具接口 | 工具 |
| `test_memory_agent_integration.py` | 全流程集成 | 全部 |

---

## 14. 实现优先级

### Phase 1（骨架 — 让记忆跑起来）

```
1. MemoryProvider ABC
2. SQLiteBuiltinProvider（store + ranker 最小集）
3. MemoryManager 编排
4. Agent 集成：prefetch + sync
5. 现有 memory_tool 适配新接口
6. 基础测试
```

### Phase 2（智能 — 让记忆自动写入）

```
1. Correction → profile 自动写入
2. Failure → reflections 自动写入
3. Intent Detection + hint 注入
4. Scanner 安全扫描
5. 去重合并策略优化
6. Token 预算控制
```

### Phase 3（完善 — 让记忆自我维护）

```
1. Query Expansion
2. Post-turn Review Fork
3. 定时 compact + consolidate
4. Session 归档
5. Provider 插件示例（如 Honcho）
6. 统计/审计 API
```
