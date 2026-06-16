# SmallShrimp 记忆层参考 Comet 改进方案

> 2026-06-16
> 对照 [Comet](https://github.com/lm041520/Comet) 的 Neo4j 知识图谱记忆系统，提炼出适用于 SmallShrimp 轻量 Agent 框架的改进项。

---

## 改进一：记忆存储加 entity_type + source_turn_id

### 现状

每条记忆只有 `(layer, content, source, importance, confidence)`，缺少实体类型和来源追踪：

```json
{
  "layer": "constraints",
  "content": "用户对花生过敏",
  "source": "auto",
  "importance": 10
}
```

无法区分是"偏好习惯"还是"健康信息"；无法溯回到原始对话的哪一句话。

### 改进目标

```json
{
  "layer": "constraints",
  "content": "用户对花生过敏",
  "entity_type": "医疗健康",          // 新增：实体类型标签
  "source_turn_id": "session_abc_5", // 新增：来源对话轮次 ID
  "source_text": "我对花生过敏",       // 新增：来源原文
  "source": "auto",
  "importance": 10
}
```

### 受控实体类型词表

参考 Comet 的 `ontology.py`，定义适用于 SmallShrimp 的实体类型（精简版，后续可扩展）：

| 实体类型 | 说明 | 举例 |
|---------|------|------|
| `身份信息` | 姓名、角色、联系方式 | "用户是后端开发" |
| `偏好习惯` | 稳定的偏好、习惯、倾向 | "偏好黑咖啡" |
| `知识能力` | 技能、知识领域、编程语言 | "会 Python 和 Go" |
| `具体目标` | 明确的目标或安排 | "计划通过雅思" |
| `健康医疗` | 过敏、病史、健康约束 | "对花生过敏" |
| `地点设施` | 地理位置、场所 | "住在北京" |
| `软件平台` | 工具、框架、平台 | "用 VS Code" |
| `时间约束` | 日期、截止时间、时间段 | "预算不超过500" |
| `组织项目` | 公司、团队、项目 | "在腾讯工作" |

### 改动范围

1. **`builtin/common.py`** — 新增 `ENTITY_TYPES` 常量和 `normalize_entity_type()` 函数
2. **`builtin/file_store.py`** — `store()` 方法新增 `entity_type` / `source_turn_id` / `source_text` 参数，写入 SQLite 索引
3. **`builtin/provider.py`** — `get_tools()` 中的 `remember_*` 工具加 `entity_type` 可选参数

### SQLite 索引改动

```sql
ALTER TABLE memory_index
  ADD COLUMN entity_type TEXT DEFAULT '';
ALTER TABLE memory_index
  ADD COLUMN source_turn_id TEXT DEFAULT '';
ALTER TABLE memory_index
  ADD COLUMN source_text TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_memory_entity_type ON memory_index(entity_type);
```

### 收益

- 检索时可以按 `entity_type` 过滤（"只查偏好"、"只查健康信息"）
- 注入 prompt 时可以分组展示（`[偏好] ... [健康] ...`）
- 每条记忆可溯回到原始对话，可解释、可纠错

---

## 改进二：检索排序引入 access_count + 命中回写

### 现状

当前排序公式：

```python
score = fts_score * 0.4 + vector_score * 0.6
time_decay = exp(-0.01 * days_since_update)
final = score * (importance / 10) * confidence * time_decay
```

只有静态属性（importance/confidence），没有动态热度反馈。高频使用的记忆和一次性的记忆排序上没区别。

### 改进目标

```python
score = fts_score * 0.30
      + vector_score * 0.40
      + importance_norm * 0.15     # 来自 LLM 评分
      + popularity_norm * 0.10     # 新增：access_count 热度
      + layer_bonus                # 新增：constraints 层 +0.10
time_decay = exp(-0.005 * days)    # 衰减变慢（重要记忆保值更久）
```

### 改动范围

1. **`builtin/common.py`** — `MemoryRecord` 新增 `access_count`、`last_access_at` 字段
2. **`builtin/file_store.py`** — `store()` 初始化 `access_count=0`；新增 `touch_recall()` 方法，检索命中后回写
3. **`builtin/hybrid_search.py`** — 排序公式加入 `popularity_norm` 和 `layer_bonus`
4. **`builtin/provider.py`** — `search()` 调完后调用 `touch_recall()` 回写命中

### 命中回写流程

```
search(query)
  → 执行检索
  → 对 top-5 结果的 record_id 调 touch_recall()
    touch_recall():
      UPDATE memory_index
      SET access_count = access_count + 1,
          last_access_at = now()
      WHERE id IN (...)
  → 返回结果
```

### 收益

- 用户频繁问 Python → Python 相关记忆 `access_count` 升高 → 下次检索自动排前面
- 一次性的闲聊被低频使用 → 慢慢沉淀到底部
- 结合 LRU 淘汰时，高 access_count 的记忆更晚被淘汰

---

## 改进三：去重加入 layer 匹配条件

### 现状

三段式去重在所有层之间模糊匹配：

```python
def _find_duplicate(self, content, layer):
    for existing in self.store.list(layer=layer):  # 虽然传了 layer，但...
        # Stage 3 只做文本模糊匹配，不检查类型相容
        rank = _rank_memory(content, existing["content"])
        seq = SequenceMatcher(None, ...).ratio()
        if rank >= 7.0 and seq >= 0.92:
            return existing
```

跨层误合并风险：profile 层的 "用户喜欢北京" 和 facts 层的 "北京是首都" 可能因文本相似被合并。

### 改进目标

引入「层组」概念，只有同组内的层才做模糊匹配：

| 层组 | 包含的层 | 组内可合并 |
|------|---------|-----------|
| 画像组 | `profile`, `constraints` | ✅ 可合并 |
| 知识组 | `facts`, `projects`, `reflections` | ✅ 可合并 |
| 会话组 | `sessions` | ❌ 不参与去重（临时） |

### 改动范围

1. **`builtin/common.py`** — 新增 `LAYER_GROUPS` 映射 + `same_layer_group()` 函数
2. **`builtin/file_store.py`** — `_find_duplicate()` 的 Stage 2/3 先检查组相容性

### 代码改动

```python
LAYER_GROUPS: dict[str, set[str]] = {
    "profile": {"profile", "constraints"},
    "knowledge": {"facts", "projects", "reflections"},
    "session": set(),  # 不参与去重
}

def same_layer_group(a: str, b: str) -> bool:
    """判断两层是否属于同一去重组。"""
    if a == b:
        return True
    for group in LAYER_GROUPS.values():
        if a in group and b in group:
            return True
    return False
```

在 `_find_duplicate()` 的 Stage 2/3 加判断：

```python
if not same_layer_group(normalized, existing["layer"]):
    continue  # 不同组不合并
```

### 收益

- profile 的偏好和 facts 的知识不再误合并
- constraints 的硬性约束和 profile 的偏好可以在组内合理合并（都是用户画像类）
- sessions 的临时对话完全不参与去重，避免污染长期记忆

---

## 实施优先级

| 改进 | 改动量 | 收益 | 风险 | 建议 |
|------|--------|------|------|------|
| 改进一：entity_type + source_turn_id | 小 | 中 | 低 | **Phase 1** |
| 改进二：access_count + 命中回写 | 小 | 中 | 低 | **Phase 1** |
| 改进三：去重加入 layer 匹配 | 小 | 低 | 低 | **Phase 2** |

1. **Phase 1**：改进一 + 改进二 同时做，改动在同一文件集中，测试可以覆盖
2. **Phase 2**：改进三，改动集中在 `file_store.py` 的去重逻辑

## 不做的

| Comet 的做法 | 不做的原因 |
|-------------|-----------|
| Neo4j 图数据库 | SmallShrimp 是轻量框架，Neo4j 太重 |
| LPA 社区聚类 | 通用 Agent 不需要自动主题聚类 |
| Celery 异步萃取 | 单用户场景同步够用 |
| 记忆不遗忘 | 数据总有膨胀的一天，LRU 淘汰更务实 |
| jinja2 prompt 模板 | 代码内常量更简单 |
| 四层完整溯源链路 | SmallShrimp 不需要 Dialogue→Chunk→Statement→Entity 四层，两层（source_turn_id + source_text）足够 |
