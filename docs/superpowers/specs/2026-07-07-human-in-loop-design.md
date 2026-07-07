# Human-in-loop 基础设计

## 目标

为 SmallShrimp 增加一套接近 LangGraph human-in-the-loop 的 runtime 语义：当 agent 遇到模糊需求、关键决策、人工审批、人工编辑或长期状态写入时，可以 **interrupt** 当前执行，保存 **checkpoint**，把问题交给用户，等用户返回后再 **resume** 原执行流程。

这不是普通的 `input()` 或权限确认框，而是 runtime 层的暂停与恢复协议。第一版只设计最小闭环，不改大范围 agent loop。

## 当前状态

当前代码里已经有几个相关能力，但它们还不是完整 human-in-loop：

- `AgentSession.set_confirm_fn(fn)`：给 CLI 注入确认回调。
- `_confirm_fn`：目前主要用于工具权限确认、目录信任确认。
- `PermissionChecker`：能返回 `allow`、`deny`、`confirm`。
- `ChatLoop`：CLI 用 `rich.prompt.Confirm` 实现同步确认。
- `SessionState`：保存 messages、memory budget、tool result budget 等，但没有 pending human request 或 checkpoint。

当前缺口：

- 没有统一的 `HumanRequest` / `HumanResponse` 数据结构。
- 没有 interrupt/resume/checkpoint 协议。
- 现有确认是同步回调，不能跨端、跨时间恢复。
- 模糊需求澄清没有进入 runtime 生命周期。
- 用户回答后的任务定义、约束和验收标准没有结构化保存。
- 权限确认、需求澄清、memory/skill draft 审批还是不同机制，无法统一追踪。

## 核心语义

### Interrupt

当 runtime 判断当前执行需要用户参与时，生成一个 `HumanRequest`，暂停当前 turn 或 task。

典型触发：

- 需求模糊，需要澄清目标、范围、输出格式或验收标准。
- 多个合理方案，需要用户选择。
- 高风险工具调用，需要用户批准。
- agent 准备写入长期 memory。
- agent 准备创建、更新或激活 skill。
- agent 需要用户修改计划、参数或输出草稿。

### Checkpoint

interrupt 之前必须保存足够状态，保证用户稍后回答也能继续。

第一版 checkpoint 不追求保存 Python 调用栈，只保存可恢复的 runtime 状态：

- `session_id`
- `turn_id`
- `request_id`
- `request_type`
- 当前 messages 快照或可重建引用
- pending action
- 用户原始输入
- 当前任务摘要
- 恢复策略

第一版恢复策略可以保守：resume 后重新进入 `session.chat()`，但必须把用户回答和原 request 作为结构化上下文注入，而不是让 agent 从头猜。

### Present

Endpoint 负责把 `HumanRequest` 展示给用户。

CLI 可以用文本问题和选项；桌面端可以弹窗；IM 端可以按钮或文本回复。Endpoint 不负责决定业务语义，只负责展示和收集回答。

### Resume

用户返回 `HumanResponse` 后，runtime 根据 `request_id` 找到 pending request 和 checkpoint，将用户响应注入原 session，恢复执行。

第一版可以限制：

- 每个 session 同一时间最多一个 pending human request。
- resume 只支持当前 session。
- 不支持长期离线恢复到任意历史调用栈。

### Trace

每次 interrupt/resume 都必须进入 runtime trace，至少记录：

- request id
- request type
- question 或 action summary
- options
- created_at
- responded_at
- response action
- response text
- resumed 是否成功

## 数据结构

### HumanRequest

建议第一版放在 `src/SmallShrimp/core/runtime/human_loop.py`。

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


HumanRequestType = Literal[
    "clarification",
    "approval",
    "edit",
    "feedback",
]


@dataclass
class HumanOption:
    id: str
    label: str
    description: str = ""


@dataclass
class HumanRequest:
    id: str
    type: HumanRequestType
    session_id: str
    turn_id: str | None
    question: str
    options: list[HumanOption] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    required: bool = True
    created_at: str = ""
```

字段说明：

- `type="clarification"`：用于模糊需求反问。
- `type="approval"`：用于工具、memory、skill、task 等审批。
- `type="edit"`：用于让用户修改计划、参数或草稿。
- `type="feedback"`：用于任务完成后的评价和纠正。

### HumanResponse

```python
HumanResponseAction = Literal[
    "answer",
    "approve",
    "reject",
    "edit",
    "revise",
]


@dataclass
class HumanResponse:
    request_id: str
    action: HumanResponseAction
    content: str = ""
    selected_option_ids: list[str] = field(default_factory=list)
    edits: dict[str, Any] = field(default_factory=dict)
    responded_at: str = ""
```

字段说明：

- `answer`：回答澄清问题。
- `approve`：批准继续。
- `reject`：拒绝执行或拒绝写入。
- `edit`：用户直接修改任务定义、参数或草稿。
- `revise`：要求 agent 按新要求重新规划。

### HumanCheckpoint

```python
@dataclass
class HumanCheckpoint:
    request_id: str
    session_id: str
    turn_id: str | None
    messages_snapshot: list[dict[str, Any]]
    pending_action: dict[str, Any] = field(default_factory=dict)
    task_summary: str = ""
    resume_hint: str = ""
    created_at: str = ""
```

第一版 checkpoint 可以直接存在 `SessionState` 内。后续如果要跨进程或跨端恢复，再持久化到 history 或单独 store。

## SessionState 变化

第一版只增加最小字段：

```python
pending_human_request: HumanRequest | None = None
pending_human_checkpoint: HumanCheckpoint | None = None
human_trace: list[dict[str, Any]] = field(default_factory=list)
```

设计约束：

- 第一版每个 session 同时只允许一个 pending request。
- 创建新 request 前，如果已有 pending request，应返回已有 request 或明确报错。
- `human_trace` 只记录摘要，不存大段私密上下文。

## Runtime API

建议在 `AgentSession` 上提供最小 API：

```python
def interrupt_for_human(
    self,
    request: HumanRequest,
    checkpoint: HumanCheckpoint,
) -> HumanRequest:
    ...


async def resume_from_human(
    self,
    response: HumanResponse,
) -> str:
    ...
```

第一版 `resume_from_human` 可以采用保守实现：

1. 验证 `response.request_id` 匹配当前 pending request。
2. 把 response 写入 trace。
3. 清空 pending request/checkpoint。
4. 生成一段结构化 user message，例如：

```text
<human_response>
request_type: clarification
question: 你希望优先整理目录结构、代码分层，还是文档说明？
answer: 先整理目录结构，不要移动文件，只输出方案。
</human_response>

请基于用户澄清后的目标继续执行。
```

5. 调用 `chat()` 继续。

这个方式不是最终形态，但足够形成 interrupt/resume 闭环，并且不会大改 agent loop。

## 需求澄清入口

第一版的需求澄清不需要复杂意图系统，可以先用保守规则触发：

触发条件示例：

- 用户输入很短且动作范围大，例如“整理一下项目”“优化一下”“帮我改好”。
- 用户要求大范围修改，但没有说明是否允许改文件。
- 用户要求生成交付物，但没有说明输出格式或验收标准。
- agent 准备执行多个可能方向前，需要用户选方向。

第一版不应该过度打断用户。建议规则：

- 最多提出 1-4 个问题。
- 只问会改变执行结果的问题。
- 能用默认值安全执行时，不必打断。
- 对低风险只读分析任务，可以先分析再提问。

澄清问题应该变成结构化 `HumanRequest(type="clarification")`，而不是普通 assistant 文本。这样后续 CLI、桌面、IM 都可以统一展示。

## 权限确认迁移路径

当前 `_confirm_fn` 不需要马上删除。第一版可以这样过渡：

1. 保留 `_confirm_fn`，不破坏现有 CLI 权限确认。
2. 新增 human-loop API。
3. 先让需求澄清走 `HumanRequest`。
4. 后续再把高风险工具确认从 `_confirm_fn` 逐步迁移到 `HumanRequest(type="approval")`。

这样避免一次性重写 permission 系统。

## CLI 第一版交互

CLI 第一版可以简单实现：

- 如果 `session.chat()` 返回或抛出一个 pending human request，CLI 展示问题。
- 如果有 options，展示编号。
- 用户输入回答后，CLI 调用 `resume_from_human()`。

示例：

```text
SmallShrimp 需要你确认几个问题：

1. 你希望优先整理哪一部分？
   [1] 目录结构
   [2] 代码分层
   [3] 文档说明

你的回答：
```

第一版可以先不做复杂多轮表单。用户的一段自然语言回答也可以作为 `HumanResponse(action="answer")`。

## Hooks 关系

Human-in-loop 需要后续 hook events，但第一版实现不必全部接入。

建议预留事件：

- `human.clarification.requested`
- `human.clarification.received`
- `human.approval.requested`
- `human.approval.granted`
- `human.approval.rejected`
- `human.revision.requested`
- `human.feedback.received`

第一版可先记录 trace，hook 接入可以作为后续批次。

## 非目标

第一版不做：

- 不做完整 LangGraph 状态机。
- 不保存 Python 调用栈。
- 不支持多个 pending human requests 并发。
- 不做复杂桌面端 UI。
- 不把所有 permission confirm 一次性迁移。
- 不自动把用户回答写入长期 memory。
- 不让 agent 因为任何小模糊都频繁打断用户。

## 建议实现顺序

### Step 1：数据结构与 SessionState

新增 `HumanRequest`、`HumanResponse`、`HumanCheckpoint`，并在 `SessionState` 增加 pending 字段和 trace 字段。

### Step 2：AgentSession interrupt/resume API

新增 `interrupt_for_human()` 和 `resume_from_human()`，先支持单 pending request。

### Step 3：CLI 最小展示和恢复

让 CLI 能展示 clarification request，并把用户回答传回 `resume_from_human()`。

### Step 4：模糊需求触发器

在 turn setup 早期加入保守的 clarification detector。只对明显模糊且可能导致大范围行动的请求触发。

### Step 5：测试

覆盖：

- 创建 pending human request。
- 同 session 只能有一个 pending request。
- request/response id 匹配。
- resume 后清空 pending 状态。
- resume 会把用户回答注入后续 chat。
- CLI 可以把回答转成 `HumanResponse`。

## 待确认问题

1. 第一版是否只做 `clarification`，暂不迁移 permission approval？
2. 模糊需求检测第一版是规则型，还是让 LLM 判断是否需要澄清？
3. `HumanRequest` 是否应该通过普通 chat response 返回，还是定义专门的 result 类型？
4. checkpoint 第一版是否只存在内存，后续再持久化？
5. CLI 第一版是否允许自然语言回答，不强制用户选择 options？

## 推荐决策

建议第一版选择：

1. **只做 clarification**，permission approval 暂时保留 `_confirm_fn`。
2. **先规则型检测**，避免额外 LLM 调用和不稳定判断。
3. **定义专门 result 类型或异常式中断**，不要把 HumanRequest 混成普通 assistant 文本。
4. **checkpoint 先存在内存**，等 session/task 持久化更稳定后再落盘。
5. **CLI 支持自然语言回答**，options 只是辅助。

这样能用最小改动建立 human-in-loop 的 runtime 语义，同时不破坏现有权限、工具和多端结构。
