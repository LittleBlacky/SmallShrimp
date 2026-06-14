# Memory Improvement Benchmark Report

**Date**: 2026-06-14
**Run**: `experiments/benchmark_memory.py`
**Tests**: 98 unit tests + 5 phase benchmarks, all pass

---

## Phase 1: Autocompact 分级压缩 + constraints 层

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| COMPACT_PROMPT 长度 | 489 chars | 1,372 chars | +883 chars |
| 约束关键词覆盖率 | 0/13 | **11/13** | +11 |
| 结构化输出段落 | 0/4 | **4/4** | +4 |
| constraints 持久化 | N/A | 3 条 | New |
| constraints 注入 prompt | N/A | ✅ 排在 profile 之前 | New |

**结论**: 新 COMPACT_PROMPT 包含 11 个显式约束保留指令，要求原文保留否定条件和数字约束。constraints 层与 profile/facts 隔离，不参与 prefetch 和压缩。

---

## Phase 2: 话题分段 + Buffer

| Metric | Before fix | After fix | Delta |
|--------|-----------|----------|-------|
| 混合对话生成话题数 | 1 (全合并) | **3** (独立话题) | +2 |
| 话题切换次数 | 0 | **5** | +5 |
| 话题标签可读性 | 不可读(bigram) | 可读(去启动词) | ✅ |
| Buffer 20 轮耗时 | N/A | **0.0ms** | ✅ |

**结论**: 修复后话题分段正常工作——"换个话题"创建新话题，"回到刚才"正确回溯。Buffer 20 轮秒级完成，overflow 检测准确。

---

## Phase 3: To-do List + 工具态记忆

| Metric | Value | Note |
|--------|-------|------|
| 10 步任务 prompt block | **160 chars** | 紧凑，已完成折叠 |
| 已完成折叠 | ✅ 显示结论 | 节省 token |
| 10 次调用去重跳过 | **3 次** | 30% 调用被缓存命中 |
| write 失败追踪 | 2/2 失败 | ✅ 可回溯 |

**结论**: ToolStateMemory 成功避免 30% 的重复调用。TodoTracker 已完成任务折叠节省 token。

---

## Phase 4: Reflection + Dreaming

| Metric | Value | Note |
|--------|-------|------|
| Reflection 阈值触发 | **15 importance** | 3 条 * 5 imp = ✅ |
| 冲突检测召回率 | **5/5 = 100%** | 5 对对立词全检出 |
| 衰减起始 | **30 天** | 30 天后 confidence 从 1.0→0.8 |
| 衰减 90 天 | confidence=0.40 | 逐步降权 |

**结论**: Dreaming 的冲突检测 100% 覆盖 5 组对立词。衰减策略有效保护高 importance 记忆。

---

## Phase 5: 优先级引擎

| Metric | Value | Note |
|--------|-------|------|
| 槽位数 | **5** | 规则/状态/输入/历史/知识 |
| 优先级排序 | ✅ | 系统规则(100) > 状态(80) > 输入(60) > 历史(40) |
| Prompt 完整性 | 147 chars | 5 段分离，结构清晰 |

**结论**: 优先级排序正确，Prompt 按槽位分离确保模型看清每段信息的权重边界。

---

## 最终验证

| 测试集 | 数量 | 通过率 |
|--------|------|--------|
| test_phase1_memory.py | 16 | **100%** |
| test_topic_segmenter.py | 10 | **100%** |
| test_conversation_buffer.py | 13 | **100%** |
| test_phase3_modules.py | 24 | **100%** |
| test_phase4_modules.py | 22 | **100%** |
| test_phase5_priority.py | 13 | **100%** |
| test_context_guard.py | 5 | **100%** |
| **Total** | **103** | **100%** |
