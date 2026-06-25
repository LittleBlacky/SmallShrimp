# 记忆推理系统 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 涉及层: Core / Memory

---

## 1. 产品概述

### 1.1 产品定位

在 `core/memory/` 现有存储基础上增加推理层，让记忆系统不仅能「存储与召回」，还能检测矛盾、推断用户画像、管理记忆老化与衰减、生成跨会话洞察。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| 用户说"我讨厌咖啡" -> 随后说"来杯美式"——无矛盾检测 | 矛盾检测器标记冲突记忆，Agent 追问澄清 |
| 一年前的记忆与上周的记忆权重一样 | 时间衰减排序，遗忘曲线：半年未提及的记忆权重降至 10% |
| Agent 不理解隐含偏好：'我程序员'、'我用 Mac'、'每周写博客' → 推断"用户是技术创作者" | 推理引擎从离散事实提取高频模式 → 生成 Profile Insight |
| 跨会话无主题关联 | 跨会话话题聚类器，按周/月生成主题摘要 |

### 1.3 目标用户

- **Agent 长期用户**：随使用时间积累，Agent 越来越了解用户偏好、习惯、知识背景
- **Agent 本身**：`sync_turn` 后推理层自动运行，生成 insights 写入 reflections 层

---

## 2. 功能范围

### 2.1 MVP（P0 — 必须实现）

| 模块 | 功能 | 说明 |
|------|------|------|
| **矛盾检测器** | 同一主题上相反的陈述检测 | `store()` 时与历史比对，标记语义相反的条目 |
| **时间衰减** | 检索时按时间加权 | `prefetch()` 结果按 `time_decay_days` 半衰期降权 |
| **推理引擎** | 从 profile 层提取高频模式 | 每日/每周扫描 profile 事实，推测隐含的用户画像标签 |

### 2.2 V1（P1 — 体验完善）

| 模块 | 功能 |
|------|------|
| **Insight 生成器** | 利用 LLM 分析 profile 事实，生成自然语言的用户洞察 |
| **跨会话摘要** | 按时间窗口聚类 session 主题，生成每周/每月回顾 |
| **记忆巩固** | 多次提及的低重要性内容 → 自动提升重要性 |

### 2.3 V2（P2 — 高级功能）

| 模块 | 功能 |
|------|------|
| **遗忘引擎** | 长时间未提及的低重要性记忆自动归档到冷存储 |
| **知识图谱推理** | 结合 Neo4j 图谱，路径推理（A 认识 B，B 认识 C → A 可能认识 C） |
| **主动提问** | Agent 在发现矛盾或信息缺口时主动追问用户 |

---

## 3. 技术架构

```
                    MemoryManager.store()
                           │
                    ┌──────┴──────┐
                    ▼             ▼
             ContradictDetector    ConfidenceGate
                    │                  │
         ┌──────────┘                  │
         ▼                             ▼
    (发现矛盾)                    MemoryProvider.store()
         │                              │
    report conflict                AsyncInsightEngine
         │                          (后台运行)
    Agent 可以追问                      │
                                  ┌────┴────┐
                                  ▼         ▼
                              Profile     Reflections
                              Insights    摘要
```

### 3.1 矛盾检测器

```python
# core/memory/reasoning/contradiction.py

class ContradictionDetector:
    """检测记忆间的语义矛盾。"""

    def __init__(self, provider: MemoryProvider):
        self._provider = provider
        # 预设已知矛盾对（关键词级别）
        self._known_opposites = {
            ("喜欢", "讨厌"), ("爱", "恨"), ("是", "不是"),
            ("有", "没有"), ("会", "不会"), ("能", "不能"),
            ("在", "不在"), ("去", "不去"),
        }

    async def check(self, layer: str, content: str) -> list[dict]:
        """检查新内容是否与已有记忆矛盾。

        Returns:
            [{"existing": "...", "new": "...", "field": "topic", "confidence": 0.9}]
        """
        results = []
        existing_items = self._provider.recall(layer, top_k=50, threshold=0.3)

        for item in existing_items:
            conflict = self._detect_pair(content, item["content"])
            if conflict:
                results.append({
                    "new": content,
                    "existing": item["content"],
                    "confidence": conflict["confidence"],
                    "existing_id": item["id"],
                })

        return results

    def _detect_pair(self, a: str, b: str) -> dict | None:
        """检测一对文本是否矛盾。"""
        # 1. 关键词对立检测
        for opp_a, opp_b in self._known_opposites:
            has_a = opp_a in a and opp_b in b
            has_b = opp_b in a and opp_a in b
            if has_a or has_b:
                # 进一步检查主题是否相同
                topic_a = a.replace(opp_a, "").replace(opp_b, "").strip()
                topic_b = b.replace(opp_a, "").replace(opp_b, "").strip()
                if self._topic_similar(topic_a, topic_b):
                    return {"confidence": 0.7}

        # 2. (V1) LLM 语义矛盾判断 — 高置信度场景
        return None
```

### 3.2 时间衰减排序

```python
# core/memory/reasoning/decay.py

def apply_time_decay(
    items: list[dict],
    half_life_days: float = 30.0,
    now: float | None = None,
) -> list[dict]:
    """对检索结果应用时间衰减权重。

    使用指数衰减: weight = 2^(-days_ago / half_life_days)
    - half_life_days=30: 30天前记忆权重减半
    - half_life_days=7:  一周前记忆权重减半
    """
    if now is None:
        from time import time
        now = time()
    for item in items:
        age_days = (now - item.get("created_at", now)) / 86400
        decay = 2 ** (-age_days / half_life_days)
        item["_score"] = item.get("_score", 1.0) * decay
        item["_decay"] = decay
    items.sort(key=lambda x: -x.get("_score", 0))
    return items
```

### 3.3 推理引擎

```python
# core/memory/reasoning/insight.py

class InsightEngine:
    """从 profile 事实提取用户画像洞察。"""

    def __init__(self, provider: MemoryProvider):
        self._provider = provider

    async def run(self) -> list[dict]:
        """运行推理管线，返回新生成的 insights。"""
        profile_items = self._provider.recall("profile", top_k=200)

        insights = []

        # 1. 频率分析 — "经常提及"的模式
        topic_freq = self._count_topics(profile_items)
        for topic, count in topic_freq.most_common(5):
            if count >= 3:  # 至少提及 3 次
                insights.append({
                    "type": "frequent_topic",
                    "topic": topic,
                    "count": count,
                    "summary": f"用户经常提及 {topic}（{count} 次）",
                })

        # 2. 隐含推断
        implicit = self._infer_implicit(profile_items)
        insights.extend(implicit)

        return insights

    def _infer_implicit(self, items: list[dict]) -> list[dict]:
        """基于事实组合推断隐含属性。"""
        all_text = " ".join(item["content"] for item in items)

        # 启发式规则
        inferences = []
        if "程序员" in all_text or "写代码" in all_text or "编程" in all_text:
            if "Python" in all_text or "JavaScript" in all_text:
                inferences.append({
                    "type": "profile_insight",
                    "inference": "用户是软件开发者",
                    "evidence": ["程序员/写代码", "Python/JavaScript"],
                    "confidence": 0.85,
                })
        # ...更多规则

        # V1: LLM 推断
        return inferences
```

---

## 4. 配置项

```yaml
# config.user.yaml
memory:
  reasoning:
    enable_contradiction_detection: true
    half_life_days: 30
    insight_interval_hours: 24       # 推理引擎运行间隔
    insight_llm_provider: ""         # 推理用独立 LLM（可选，默认使用主 LLM）
```

---

## 5. 测试要点

| 场景 | 说明 |
|------|------|
| 简单关键词矛盾 | store("我喜欢咖啡") → store("我讨厌咖啡") → 检测到矛盾 |
| 时间衰减排序 | 相同相关性下，新条目 > 半年旧条目 |
| 频率分析 | 同一主题出现 3+ 次 → 生成 frequent_topic insight |
| 无矛盾正常 | 一致的内容不触发矛盾报告 |
| 空 profile | 推理引擎空运行不报错 |

---

## 6. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | 矛盾检测器（关键词级）+ 时间衰减排序 | 2d |
| P1 | 频率分析推理 + 洞察写入 reflections | 2d |
| P1+ | LLM 驱动的语义矛盾检测 | 1d |
| P2 | 遗忘引擎 + 主动提问 | 2d |

---

## 7. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 矛盾检测误报 | 用户被频繁追问"你说过 X 又说 Y" | 置信度分层：低 confidence 的矛盾不触发追问，仅日志记录 |
| 推理引擎运行开销 | 记忆写入变慢 | 异步后台运行，不阻塞 store() 与 sync_turn() |
| LLM 推理成本 | 每天多次 LLM 调用 | 控制在每日/每 session 一次的频率；关键词推理优先 |

---

## 8. 附录

### 8.1 变更文件

| 文件 | 变更类型 |
|------|----------|
| `src/SmallShrimp/core/memory/reasoning/` | 新增目录 |
| `src/SmallShrimp/core/memory/reasoning/contradiction.py` | 新增 — 矛盾检测器 |
| `src/SmallShrimp/core/memory/reasoning/decay.py` | 新增 — 时间衰减 |
| `src/SmallShrimp/core/memory/reasoning/insight.py` | 新增 — 推理引擎 |
| `src/SmallShrimp/core/memory/memory_manager.py` | 修改 — 集成矛盾检测和时间衰减 |

### 8.2 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始草案 |
