# SmallShrimp 记忆层改进路线图

> 基于 [记忆与上下文最佳实践](https://onefly.top/zero2Agent/learn-agent-interview/04-memory-context/index.html) 对照分析。
> 最后更新: 2026-06-14

---

## 现状总结

| 已具备 | 说明 |
|--------|------|
| Provider 插件化 | `MemoryProvider` ABC + `BuiltinProvider`，可替换后端 |
| 声明式 Layer 系统 | `Layer(name, searchable, inject)` 自描述分层 |
| 5 层记忆 | profile / facts / projects / reflections / sessions |
| ContextGuard 4-tier 压缩 | Budget → Snip → Microcompact → Autocompact |
| Correction 检测 | 用户纠正自动写 profile |
| Failure 学习 | 工具失败自动写 reflections |
| 混合检索 | FTS5 + jieba 分词 + 可选 sqlite-vec 向量 |
| 去重合并 | 三阶段去重 + consolidate |
| Prefix Cache 稳定性 | system_prompt_block 缓存快照设计 |
| 容量管理 | LRU 淘汰 + compact |

---

## Phase 1: 上下文压缩增强（当前最紧迫）

### 1.1 Autocompact 分级压缩 Prompt

**目标**: 压缩时不丢失否定约束和硬性条件。

**改动范围**: `src/SmallShrimp/core/context_guard.py` 的 `COMPACT_PROMPT`

**方案**: 把当前笼统的摘要 prompt 改为分级指令——

```
当前: "总结对话，包括用户请求、操作、关键上下文"

改为:
"总结以下对话。不同类型的信息用不同策略处理：

【必须保留原文，不压缩不转述】
- 否定约束：'不要XX'、'禁止XX'、'不能XX'
- 数字约束：预算、日期、数量、版本号
- 用户身份信息：姓名、角色、联系方式

【可以压缩为摘要】
- 讨论过程、推理步骤、中间结果

【可以直接丢弃】
- 寒暄客套、确认性回复（'好的''明白了'）
- 已完成的工具调用原始 JSON

输出格式：
## 硬性约束（原文）
- ...
## 对话摘要
- ...
## 待解决问题
- ..."
```

**验收标准**: 压缩后「不含坚果」「预算≤500」等约束在摘要中逐字保留。

### 1.2 约束外置存储

**目标**: 关键约束独立存储，与摘要分离，不参与压缩。

**改动范围**:

- `src/SmallShrimp/core/memory/builtin/file_store.py` — 新增 `constraints` 层
- `src/SmallShrimp/core/memory/builtin/provider.py` — 新增 `constraints` Layer 声明，`inject="session"`
- `src/SmallShrimp/core/context_guard.py` — Autocompact 时 constraints 不参与压缩，直接保留注入

**方案**:

```
上下文组装结构:
[System Prompt]
[硬性约束（从不压缩）]           ← 新增，每次注入
  - 不含坚果
  - 预算 ≤ 500
[压缩摘要（定期更新）]
  用户正在为朋友选生日礼物...
[最近原始对话]
  ...
```

**验收标准**: constraints 层内容永远不进入 Autocompact 的压缩流程，始终原文注入。

---

## Phase 2: 会话记忆增强

### 2.1 话题分段存储

**目标**: 用户频繁切换话题时，Agent 能无缝接续之前的话题。

**改动范围**:

- `src/SmallShrimp/core/memory/topic_segmenter.py` — **新文件**，话题检测与分段
- `src/SmallShrimp/core/memory/builtin/provider.py` — 集成话题分段

**方案**:

```
数据结构:
topics = [
  { id: "flight", label: "机票预订", turns: [...], summary: "...", last_active: "..." },
  { id: "hotel",  label: "酒店预订", turns: [...], summary: "...", last_active: "..." }
]

流程:
1. 每条用户消息 embedding → 与活跃话题计算相似度
2. 相似度 > 阈值 → 归入已有话题，更新该话题 mini-buffer
3. 相似度 < 所有话题阈值 → 创建新话题
4. 上下文组装: System Prompt + 活跃话题完整记忆 + 暂停话题简要摘要 + 当前输入
```

**降级方案**: 如果 embedding 话题检测不够可靠，改为给每轮对话打话题标签，检索时按标签过滤而非按时间截断。

**验收标准**: 用户说"回到刚才的机票"时，Agent 能从机票话题的 mini-buffer 中恢复上下文。

### 2.2 滑动窗口 Buffer + 摘要压缩双层架构

**目标**: 近期对话保留原文（精确），远期对话压缩为摘要（省 token）。

**改动范围**:

- `src/SmallShrimp/core/memory/buffer.py` — **新文件**，ConversationBuffer
- `src/SmallShrimp/core/agent.py` — 集成 Buffer，替换当前直接操作 `state.messages`

**方案**:

```
Buffer Memory（滑动窗口）:
- 保留最近 5-10 轮原始对话
- 存储: 内存 / Redis
- 触发压缩条件（满足任一）:
  1. Token 数达窗口 70%
  2. Buffer 超过 8 轮
  3. 话题切换（当前轮与 Buffer 语义相似度 < 阈值）

Summary Memory（摘要层）:
- Buffer 溢出时，最早 K 轮压缩为结构化摘要
- 保留: 用户偏好、关键决策、事实性承诺、未解决问题
- 丢弃: 寒暄、重复信息、中间推理步骤
- 存储: 持久化数据库

上下文组装 = System Prompt + Summary 摘要 + Buffer 原始对话 + 当前输入
```

**与 ContextGuard 的关系**: ContextGuard 管理的是整个 context window 的压缩（全局），ConversationBuffer 管理的是对话历史的滚动窗口（局部）。两者互补：Buffer 处理「哪些对话该保留原文」，ContextGuard 处理「上下文超标时兜底压缩」。

**验收标准**:

- Buffer 中的对话保留完整原文
- Buffer 溢出时自动生成摘要，摘要中关键决策不丢失
- 与 ContextGuard 不冲突（ContextGuard 的阈值设在 Buffer+Summary 之外）

---

## Phase 3: 任务执行增强

### 3.1 To-do List 锚点机制

**目标**: 多步任务执行中，模型每一步都能看到全局进度，不偏离目标。

**改动范围**:

- `src/SmallShrimp/core/todo_tracker.py` — **新文件**，任务进度追踪
- `src/SmallShrimp/core/prompt_builder.py` — 注入 to-do list 到 system prompt
- `src/SmallShrimp/tools/` — 新增 `task_update` 工具

**方案**:

```
System Prompt 注入格式:
[任务进度]
✅ 1. 分析用户需求
🔄 2. 查询数据库 (进行中)
⏳ 3. 生成推荐列表
⏳ 4. 发送邮件通知

工具: task_update(task_id, status)
  status: "pending" | "in_progress" | "completed" | "blocked"

每轮对话前，从持久化存储加载最新 to-do list
注入位置: System Prompt 末尾（靠近当前轮输入，注意力权重高）

已完成 item 折叠策略:
- 已完成的 item 只保留一行结论
- 进行中的 item 保留原始上下文
- 待处理的 item 保留简要描述
```

**验收标准**:

- 模型在 10 步以上的复杂任务中不会忘记初始目标
- 任务中断后恢复时，能从 to-do list 恢复进度

### 3.2 工具态记忆 (Tool-state Memory)

**目标**: 避免重复调用工具，从失败中学习。

**改动范围**:

- `src/SmallShrimp/core/tool_state.py` — **新文件**，工具调用状态追踪
- `src/SmallShrimp/core/agent.py` — 集成到 `_execute_tool_calls`

**方案**:

```
四类工具态记忆:
1. 调用历史: (tool_name, params_hash, result_summary, timestamp)
2. 执行状态: pending → running → success/failed
3. 能力记忆: 工具在特定条件下的成功率、平均延迟
4. 失败记忆: 哪些参数组合导致过失败，失败原因

去重逻辑:
- Agent 调用工具前，Runtime 检查 (tool_name, params_hash) 是否已执行
- 已执行且结果仍有效 → 返回缓存结果，不发实际调用
- 已执行但可能过期 → 提示 Agent "此工具已调用过，是否重新执行？"

注入方式:
- 调用历史以紧凑表格注入 context:
  [已完成操作]
  - read(file="config.py") → 成功 (200 lines)
  - grep(pattern="TODO") → 成功 (5 matches)
```

**验收标准**: Agent 不会在 3 轮内对同一参数重复调用同一工具。

---

## Phase 4: 长期记忆增强

### 4.1 Reflection 升级：归纳 + 抽象 + 策略推导

**目标**: 从多次对话中提炼高层认知，不只是记录失败。

**改动范围**:

- `src/SmallShrimp/core/memory/reflection.py` — **新文件**，Reflection 引擎
- `src/SmallShrimp/core/memory/builtin/provider.py` — 新增 reflection 触发逻辑

**方案**:

```
触发条件: 最近 N 条记忆的 importance 累计 > 阈值时触发

Reflection vs Summarization 区别:
  Summarization: "用户问了三次 Python 装饰器" (压缩)
  Reflection:    "用户是有经验的 Java 后端，正在学 Python。
                 装饰器/元编程是薄弱点，基础语法已掌握。
                 建议: 用 Java 类比解释 Python 概念。" (产生新认知)

Reflection 产物:
1. 归纳: 从多条记忆中提取共性
2. 抽象: 从具体事件上升到模式识别
3. 策略推导: 基于认知产出行动建议

输出: 写入独立的 "insights" 层，inject="session"
```

**验收标准**: Reflection 输出包含原始记忆中不存在的新认知（如"用户学习模式是 X"）。

### 4.2 Dreaming 离线记忆整合

**目标**: Agent 空闲时主动整理记忆——冲突检测、跨会话关联、长尾淘汰。

**改动范围**:

- `src/SmallShrimp/core/memory/dreaming.py` — **新文件**，Dreaming 引擎
- `src/SmallShrimp/core/cron_loader.py` — 注册 Dreaming 为 CronJob

**方案**:

```
四项核心工作:
1. 记忆重放与巩固:
   - 高频访问的短期记忆 → 标记为长期保存
   - 低频记忆 → 逐步衰减

2. 冲突检测与消解:
   - 扫描记忆库，发现矛盾条目
   - 例: "不吃辣" vs "来点辣的" → 标记冲突，下次交互时确认

3. 跨会话关联发现:
   - 不同会话中看似无关的记忆通过推理发现关联
   - 例: "周一聊健身" + "周三买蛋白粉" → 推断健身需求

4. 记忆压缩与抽象层级提升:
   - 多条具体记忆合并为更抽象的用户画像
   - 例: 5 条关于日料的记忆 → "用户偏好日料（置信度: 5）"

触发方式: CronJob，每小时或每次会话结束后运行
```

**验收标准**: Dreaming 运行后，冲突记忆被标记、长尾记忆被衰减、隐含关联被发现。

---

## Phase 5: 决策引擎增强

### 5.1 信息源冲突优先级引擎

**目标**: 当多源信息矛盾时，有明确的决策逻辑。

**改动范围**:

- `src/SmallShrimp/core/priority_resolver.py` — **新文件**，优先级引擎
- `src/SmallShrimp/core/prompt_builder.py` — 按优先级槽位组装 Prompt

**方案**:

```
优先级链（高→低）:
1. 系统安全/合规约束（不可违反）
2. 系统实时状态（当前事实，如账户被冻结）
3. 当前轮用户显式声明（当前意愿）
4. 历史记忆/行为模式（参考但可被覆盖）

Prompt 槽位分离组装:
【系统规则】...
【硬性约束（从不压缩）】预算 ≤ 500, 不含坚果
【当前任务】...
【实时状态】账户状态: 正常, VIP等级: 金卡
【检索证据】[来源: 产品手册 v2.3] ...
【用户历史画像】偏好 Python, 最近在学 Rust
【当前问题】用户问: ...
```

**验收标准**:

- 用户说"预算不限"但系统显示账户余额不足时，余额约束优先
- 用户历史偏好"中餐"但当前说"想吃日料"时，当前声明覆盖历史

---

## 实施顺序与依赖

```
Phase 1 (1-2 天)
├── 1.1 Autocompact 分级压缩 Prompt ← 改一个常量，收益大
└── 1.2 约束外置存储           ← 新增 constraints 层，轻量

Phase 2 (2-3 天)
├── 2.1 话题分段存储           ← 新模块，有复杂度
└── 2.2 滑动窗口 Buffer        ← 新模块，需与 ContextGuard 协调

Phase 3 (2-3 天)
├── 3.1 To-do List 锚点         ← 新模块
└── 3.2 工具态记忆             ← 新模块

Phase 4 (3-4 天)
├── 4.1 Reflection 升级         ← 依赖现有 reflections 层
└── 4.2 Dreaming 离线整合       ← 依赖 CronJob 基础设施

Phase 5 (1-2 天)
└── 5.1 信息源冲突优先级引擎    ← 主要是 prompt 组装逻辑
```

---

## 不做的

| 项目 | 原因 |
|------|------|
| Code Agent 专用 AST/LSP 索引 | SmallShrimp 定位是通用 Agent，非 Code Agent 专用 |
| NER 实体提取 + 知识图谱 | 当前规模不需要，先用 Layer + FTS5 覆盖 |
| Prompt Caching 服务端集成 | 依赖 LLM Provider API，属于部署配置而非框架层 |
| MemGPT 式虚拟内存管理 | 过度设计，ContextGuard + Buffer 已覆盖核心需求 |
