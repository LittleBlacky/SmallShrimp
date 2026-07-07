# SmallShrimp Runtime Harness 总体改造设计

## 目标

这份文档定义 SmallShrimp 长期 runtime harness 的改造方向，避免后续开发变成松散的“agent 框架功能堆叠”。SmallShrimp 的定位是一个多端响应、持续进化的个人助理 Agent。它的 runtime 必须能够帮助用户完成任务、理解用户场景和偏好、沉淀可复用方法、持续进化这些方法，并最终把改进反馈给用户。

这是一份路线图和架构护栏，不是一次性实现计划。后续每个实现步骤仍然需要先小范围讨论、由用户确认、补充测试，并独立提交。

## 产品定义

SmallShrimp 不是通用 agent 框架，而是围绕用户电脑、文件、工作习惯和任务场景运行的个人助理。

产品演进分为四个阶段：

1. **协助用户完成任务**：理解请求、调用工具、操作本地资源，并通过多个端响应用户。
2. **近似用户克隆**：学习用户的任务场景、画像、偏好、反馈和可复用方法。
3. **自我进化**：通过反思、失败学习、技能沉淀和重复任务结果持续改进方法。
4. **反哺用户成长**：把有价值的总结、习惯、工作流和纠错反馈给用户，让用户和助理一起进步。

所有 runtime 子系统都应该围绕这四个阶段判断是否值得建设。

## 指导原则

- **一个核心循环，多层 harness 挂载**：agent loop 是稳定核心；hooks、skills、memory、permissions、tools、compaction、tasks、subagents、cron、channels 都应该挂在它周围。
- **个人助理优先**：抽象必须服务于用户的电脑、文件、工作模式和偏好，不为通用 agent 框架 API 做优化。
- **用户可控**：自动学习、技能创建、记忆提取和自治行为必须可观察、可审查、可关闭。
- **小步可回退**：每个实现步骤都要小到可以先讨论、独立测试、单独提交。
- **方法沉淀为资产**：重复成功的工作流应该沉淀为版本化 skills、memories 或 task templates。
- **先 runtime，后自治**：hooks、memory、skills、task graph、permissions、observability 稳定之前，不做激进自治行为。

## 目标 Runtime 流程

目标 runtime pipeline 如下：

```text
endpoint input
  -> 标准化输入消息
  -> 查找 session/runtime context
  -> 用户输入 hooks
  -> 注入待处理的 cron/background/task 通知
  -> memory 预取
  -> skill catalog 附加
  -> context compaction 检查
  -> system prompt 组装
  -> LLM 调用前 hooks
  -> LLM 调用与错误恢复
  -> LLM 调用后 hooks
  -> 如果存在 tool calls:
       -> tool 调用前 hooks
       -> permission 和 guardrail 检查
       -> tool dispatch / MCP dispatch / background dispatch
       -> tool 调用后 hooks
       -> 追加 tool results
       -> 继续循环
     否则:
       -> response 前 hooks
       -> 把响应交付给 endpoint
       -> response 后 hooks
       -> stop/task completion hooks
       -> 后台学习和 consolidation
```

代码不一定要变成一个巨大的文件。真正重要的不变式是：每个子系统都必须在 runtime 生命周期里有明确位置。

## 分层职责

### 1. Endpoint 层

负责接收和发送消息。

示例：

- CLI
- 桌面端
- web/server workers
- 企业微信、Telegram、Discord 或未来其他 channel

Endpoint 代码应该把消息标准化为统一 runtime request，不应该包含自己的助理行为逻辑。

### 2. Runtime Session 层

负责一次主要助理执行过程。

职责：

- 创建或恢复 session
- 持有 session state
- 运行主循环
- 按确定顺序调用 hooks
- 协调 memory、skills、compaction、tools 和 response delivery
- 暴露 trace 数据，方便调试和审查

这一层是整个 harness 的中心。

### 3. Hook 层

负责有序的生命周期拦截。

Hooks 不只是为了 skills。它们是以下能力的扩展层：

- audit 和 observability
- permissions 和 safety
- memory extraction
- skill learning
- task completion detection
- background jobs
- fork/subagent lifecycle
- 用户或开发者自定义行为

Hooks 不应该替代 event bus。Hooks 负责有序生命周期拦截，event bus 负责跨组件异步通信。

### 4. Skill 层

负责可复用任务方法。

目标行为：

- 把 skill metadata 加载成轻量 catalog
- 只在需要时加载完整 `SKILL.md`
- 支持标准 skill 结构，以及可选 `references/`、`scripts/`、`assets/`
- 每个 skill 独立版本化
- 支持用户主动创建 skill
- 支持 agent 在任务完成后建议 draft skill
- 自动创建的 skill 必须先进入可审查状态，不能直接激活

Skills 是长期可复用方法论的主要载体。

### 5. Memory 层

负责长期个人上下文。

Memory 分类：

- `user`：用户画像、风格、偏好、约束
- `feedback`：从用户纠正和反馈里学到的偏好
- `project`：持久项目背景和架构事实
- `reference`：重复使用资源的位置和查找线索
- `methodology`：可复用做事方法，后续可以提升为 skill

目标行为：

- 保持轻量 memory index 可用
- 每轮选择相关 memories
- 在稳定停止点后提取新 memories
- 合并、去重、淘汰过期 memories
- 允许用户查看、编辑、禁用或删除 memories

Memory 和 skills 有关联但不是同一个东西。Memory 存事实和偏好，skills 存可复用流程。

### 6. Context 与 Compaction 层

负责保持当前上下文有用。

职责：

- 保留当前目标
- 保留用户约束
- 保留未解决的工具结果和任务状态
- 总结过时 tool outputs
- 避免丢失应该进入 memory 的信息
- 触发 compact 前后 hooks

Compaction 应该是 runtime service，而不是隐藏在某个 channel 里的工具函数。

### 7. Tool 与 Permission 层

负责受控行动。

职责：

- 为当前 session 组装可用 tools
- 根据策略加入 built-in、skill-provided、MCP、channel-specific tools
- 执行前进行 permission checks
- 对 file、shell、network 和外部 tools 运行 guardrails
- 对慢任务支持 background dispatch
- 记录 tool traces 供审查

Permission 决策应该能在 runtime traces 里看到。

### 8. Task Graph 层

负责持久化工作协调。

它和当前轮 todo list 是两层东西。

Todo list：

- 短生命周期
- 帮助当前 agent 保持方向
- 存在于 session 或 turn 内

Task graph：

- 持久化
- 可跨 session
- 支持依赖
- 支持 owner 和 claim
- 支持 subagent 与未来 autonomous workers

初始 task 字段应该保守：

- `id`
- `title`
- `description`
- `status`
- `owner`
- `blocked_by`
- `created_at`
- `updated_at`
- `source_session_id`

### 9. Fork 与 Subagent 层

负责干净的上下文委派。

定义：

- `fork`：从当前上下文创建独立 child context。
- `subagent`：在 fork 出来的上下文里执行任务，并返回结果。
- `teammate`：更长期存在的 worker，可以通信和认领持久任务。

Fork 是通用基础设施。Skill creation 只是 fork 的一个使用场景。

目标用途：

- skill creation
- memory extraction
- research subtasks
- code review
- parallel file inspection
- autonomous task execution

### 10. Learning 与 Evolution 层

负责让 SmallShrimp 随时间改进。

学习来源：

- 成功任务
- 失败任务
- 用户纠正
- 重复工作流
- 重复 tool sequences
- 重复项目方法

输出：

- memory updates
- skill drafts
- skill version updates
- task templates
- user feedback summaries
- runtime configuration suggestions

这一层必须保持可审查。早期版本应该生成 drafts 和 suggestions，不能静默改写助理行为。

### 11. Observability 层

负责解释发生了什么。

Runtime traces 后续应该能回答：

- 哪个 endpoint 发起了本轮
- 哪些 hooks 被触发
- 哪些 memory entries 被加载
- 哪些 skills 被列出或加载
- 提供了哪些 tools
- 执行了哪些 tools
- 哪些 permissions 被请求或拒绝
- 是否发生 compaction
- 是否调度了 learning tasks
- 是否创建了 fork/subagents

没有 observability，自治学习就很难被信任。

## Hook Event Map

当前 hook foundation 应该逐步演进到下面的事件表。

### 当前核心事件

- `session.start`
- `session.end`
- `message.received`
- `context.built`
- `llm.before_call`
- `llm.after_call`
- `tool.before_call`
- `tool.after_call`
- `response.before`
- `response.after`
- `task.completed`
- `task.failed`
- `fork.created`
- `subagent.started`
- `subagent.completed`
- `error`

### 建议新增事件

- `runtime.input.normalized`
- `runtime.notifications.injected`
- `memory.prefetch.before`
- `memory.prefetch.after`
- `memory.extract.before`
- `memory.extract.after`
- `skills.catalog.built`
- `skills.before_load`
- `skills.after_load`
- `compact.before`
- `compact.after`
- `permission.request`
- `permission.denied`
- `tool.failed`
- `config.changed`
- `file.changed`
- `instructions.loaded`
- `background.enqueued`
- `background.completed`
- `task.created`
- `task.claimed`

这些事件不应该一次性全实现。它们先作为方向定义，保证后续功能能挂到一致的位置。

## Skill 系统方向

目标 skill 格式应该遵循常见的 `SKILL.md` 模式：

```text
skill-name/
  SKILL.md
  references/
  scripts/
  assets/
```

Frontmatter 支持常见字段：

```yaml
name: task-flow-retrospective
description: Summarize completed task flows into reusable lessons.
version: 0.1.0
when_to_use: Use after repeated task execution or user correction.
allowed_tools:
  - read_file
  - write_file
context: inline
hooks:
  - task.completed
```

实现方向：

1. 启动或 session 组装时只放 catalog
2. 通过显式加载获取完整内容
3. 后续支持 `context: fork`，让 skill 在隔离上下文中执行
4. 自动创建的 skills 先进入 draft 状态
5. 用户批准后激活，或拒绝草稿

## Memory 系统方向

目标 memory model 应该同时兼容文件型和索引型实现。第一版存储引擎不是重点，重点是架构契约。

必需行为：

- LLM 调用前组装 memory index
- context build 前选择相关 memory
- stop/task completion 后提取 memory
- consolidation 作为后台任务执行
- memory 变更有审计轨迹
- 用户可以 review 和 edit

早期实现应该聚焦：

- stop-hook extraction interface
- draft memory records
- mocked extraction 的确定性测试
- 不做静默不可逆的 memory rewrite

## Task 与 Autonomy 方向

自治行为必须在持久任务系统之后引入。

顺序：

1. persistent task graph
2. task lifecycle tools
3. subagent 可以处理显式 forked tasks
4. worker 可以 claim 未拥有、未阻塞的 tasks
5. idle polling 放在配置开关后
6. 用户可见的进度总结和审批

不要一上来做完全自治 workers。先做持久 task state 和手动 claim。

## 开发路线图

### Phase 1：Runtime Harness 规格

交付物：

- 本设计文档
- 对 runtime pipeline 达成共识
- 确认未来实现按小步、可 review 的方式推进

这一阶段不要求改变 runtime 行为。

### Phase 2：Hook 生命周期对齐

交付物：

- 细化 hook event map
- 保守增加缺失 event names
- 文档化哪些事件已实现、哪些只是预留
- 增加 trace-friendly hook execution records

这一阶段暂时不改变 skills 或 memory 行为。

### Phase 3：Skill Loading 标准化

交付物：

- skill catalog attachment
- 明确的 `load_skill` 行为
- 标准 frontmatter parser 覆盖
- draft/active skill state model 设计

这一阶段暂时不实现 autonomous skill creation。

### Phase 4：Memory Extraction 接口

交付物：

- stop/task-completed hook 的 memory extraction 接口
- draft memory records
- memory review path
- consolidation design stub

这一阶段避免静默自动修改重要用户记忆。

### Phase 5：Persistent Task Graph

交付物：

- task data model
- create/list/get/claim/complete 行为
- dependency checks
- blocked tasks 和 ownership 测试

这一阶段为 autonomous agents 做准备，但不要求实现自治。

### Phase 6：Forked Workflows

交付物：

- fork context policies
- subagent result contract
- skill drafting 和 memory extraction 的 fork 使用场景
- parent 与 child session 的 trace linkage

### Phase 7：Controlled Autonomy

交付物：

- opt-in idle task scanning
- safe task claiming
- background execution limits
- 用户可见 progress summaries
- shutdown 和 failure recovery policy

### Phase 8：用户提升反馈

交付物：

- task retrospectives
- 面向用户的 improvement suggestions
- workflow reports
- skill 和 memory review summaries

## 近期建议

下一步实现应该很小：

1. Review 并确认这份 runtime harness design。
2. 只为 **Hook 生命周期对齐** 创建聚焦实现计划。
3. 用一个小批次实现 hook event additions 和 runtime trace records。
4. 在触碰 skill loading 或 memory extraction 前停下来 review。

这样可以让项目继续朝长期个人助理愿景推进，同时避免把多个子系统混在一次改动里。

## 下一批不做什么

- 不重建整个 agent loop。
- 不添加 autonomous workers。
- 不重写 memory system。
- 不替换现有 skill loader。
- 不引入 marketplace 或 plugin system。
- 不创建大量兼容转发文件。

## 待确认决策

这些问题需要在实现前由用户确认：

1. 预留 hook events 是现在就加到 enum，还是先只写在文档里？
2. Runtime traces 第一版应该存到 session history、单独 trace store，还是先只输出 logs？
3. 第一版实现里，skill catalog attachment 应该在 memory prefetch 之前还是之后？
4. 自动 memory extraction 是否默认只创建 inactive drafts？
5. Task graph 存储应该放在 `workspace/tasks/`，还是沿用现有 runtime workspace 结构？

## 后续每批工作的验收标准

每个后续实现批次都应该满足：

- 用户先 review 小设计，再写代码
- 改动限制在一个子系统边界内
- 测试覆盖新行为
- 最终交付前完整测试通过
- git commit 只包含一个逻辑变更
- 最终总结说明改了什么，以及哪些内容是刻意不做的
