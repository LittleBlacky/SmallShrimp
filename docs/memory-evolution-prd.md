# SmallShrimp 记忆三阶段升级 PRD

## 背景

SmallShrimp 定位为全权电脑管家，长期运行（数月级别）。记忆系统需要从"被动存储"演进到"主动理解"再到"经验复用"，让 agent 越来越懂用户、越来越聪明。

## 三阶段框架

借鉴 ACL 2026 学术研究和工程实践，将记忆演进分为三阶段：

```
第一阶段：存储与沉淀 (Storage & Preservation)
  目标：可靠地记录一切值得记住的信息
  关键词：完整性、持久化、去噪

第二阶段：反思与理解 (Reflection & Understanding)
  目标：从原始数据中提炼用户画像、偏好、关系
  关键词：结构化、抽象化、个性化

第三阶段：经验化与进化 (Experiencing & Evolving)
  目标：将成功模式固化为可复用技能，越用越聪明
  关键词：技能化、工作流复用、自我进化
```

## 当前状态

| 能力 | 状态 | 所属阶段 |
|------|------|---------|
| 5 层记忆存储 | ✅ 完成 | 第一阶段 |
| 置信度管线 | ✅ 完成 | 第一阶段 |
| 意图检测 | ✅ 完成 | 第一阶段 |
| 图谱存储 | ✅ 完成 | 第一阶段 |
| PatternLearner | ✅ 完成 | 第二阶段 |
| 统一检索管线 | ✅ 完成 | 第一阶段 |
| access_count | ❌ 缺失 | 第一阶段 |
| 语义去重 | ❌ 缺失 | 第一阶段 |
| 对话自动提取 | ❌ 缺失 | 第二阶段 |
| Profile 自增强 | ❌ 缺失 | 第二阶段 |
| 实体描述增强 | ❌ 缺失 | 第二阶段 |
| 技能动态学习 | ❌ 缺失 | 第三阶段 |
| 工作流复用 | ❌ 缺失 | 第三阶段 |
| 经验抽象 | ❌ 缺失 | 第三阶段 |

## 第一阶段：存储与沉淀

### 1.1 access_count 追踪

**目标**：每次记忆被检索命中时计数 +1，为排序、晋升、Profile 增强提供数据基础。

**改动**：
- `memory_index` 表新增 `access_count INTEGER DEFAULT 0` 和 `last_accessed_at TEXT`
- `MarkdownStore.search()` 命中后异步更新 access_count
- `entities` 表新增 `access_count REAL DEFAULT 0`
- `GraphStore.search_entities()` 命中后更新 access_count

**验收**：检索同一记忆 3 次后，access_count = 3。

### 1.2 语义去重

**目标**：GraphIndexer 建实体前先做 embedding 相似度比对，cosine > 0.85 则合并到已有实体。

**改动**：
- `GraphIndexer.index()` 中，upsert_entity 前先搜索相似实体
- 相似则合并：更新 description、aliases，复用已有 entity_id
- 无 embedding provider 时降级为 name 精确匹配（现有行为）

**验收**：存入"Alice Zhang"时，如果已有"Alice"且 embedding cosine > 0.85，合并为一个实体。

### 1.3 隐含信息自动提取

**目标**：每轮对话结束后，自动从对话中提取用户偏好、事实、环境信息，无需用户说"记住这个"。

**改动**：
- `AgentSession.chat()` 返回前，调用 `_extract_implicit_memories()`
- 用轻量 prompt 让 LLM 从本轮对话中提取值得记住的信息
- 提取结果通过 MemoryManager.store() 写入（走置信度管线）
- 频率控制：每轮最多提取 3 条，避免噪声

**验收**：用户说"我习惯用 VS Code"，即使没有说"记住这个"，也会自动存入 reflections 层。

## 第二阶段：反思与理解

### 2.1 Profile 自增强

**目标**：定期从所有记忆中合成用户画像，profile 层自动变丰富。

**改动**：
- `MemoryManager` 新增 `enhance_profile()` 方法
- 读取 facts/reflections 中的 top-K 高 access_count 记忆
- LLM 合成为结构化用户画像（角色、偏好、习惯、环境）
- 写入 profile 层，覆盖旧画像（不是追加）

**验收**：运行 1 周后，profile 层从空白变成包含用户角色、偏好、习惯的结构化画像。

### 2.2 实体描述增强

**目标**：图谱实体的 description 随使用变丰富，从空字符串变成有意义的描述。

**改动**：
- 实体被检索命中时，如果 description 为空或很短，触发增强
- 从关联的记忆条目中提取描述，写入 entity.description
- 频率控制：每个实体每小时最多增强一次

**验收**：图谱中"Python"实体从 description="" 变成 description="用户的主要编程语言，用于后端开发"。

### 2.3 记忆晋升机制

**目标**：新记忆经过验证后晋升为长期记忆，获得更高权重。

**改动**：
- 记忆分三级：暂存（StagingArea）→ 短期（default）→ 长期（promoted）
- 晋升条件（任一满足）：access_count >= 5，importance >= 8，出现 >= 3 次
- 长期记忆在检索时获得 +0.05 分加成
- 晋升时触发 Profile 增强

**验收**：一条记忆被检索 5 次后自动晋升为长期，检索排名提升。

## 第三阶段：经验化与进化（规划，暂不实现）

### 3.1 技能动态学习

- 用户纠正 agent 的操作方式 → 自动更新 SKILL.md
- 同一操作成功 3 次 → 固化为技能

### 3.2 工作流复用

- 成功的任务序列 → 抽象为工作流模板
- 类似任务出现时 → 自动匹配并复用

### 3.3 经验抽象

- 同类问题的多次解决经验 → 合成领域知识
- PatternLearner 升级为 ExperienceEngine

## 实施顺序

```
第一阶段（当前）：
  1.1 access_count      → 基础设施
  1.2 语义去重           → 基础设施
  1.3 隐含信息自动提取   → 智能化

第二阶段：
  2.1 Profile 自增强
  2.2 实体描述增强
  2.3 记忆晋升机制

第三阶段：待第一、二阶段验证后规划
```

## 验证方式

每阶段完成后：
1. `pytest tests/` — 现有测试全部通过
2. 单元测试覆盖新模块
3. 端到端：对话 → 存储 → 检索 → 晋升 全链路验证
4. 长期验证：连续运行 1 周，检查 profile 增强效果
