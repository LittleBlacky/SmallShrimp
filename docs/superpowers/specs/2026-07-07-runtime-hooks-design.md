# Runtime Hooks System Design

## Goal

Build a complete, general-purpose runtime hook system for SmallShrimp. Hooks are not only for skill creation; they are the extension layer that lets built-in modules, user configuration, developers, plugins, and future skills participate in the agent lifecycle.

## Design Direction

The hook system should evolve in two phases:

1. **Phase B: Built-in hooks controlled by YAML**
   - Support code-registered hook handlers.
   - Support `workspace/config.user.yaml` toggles for built-in hooks.
   - Do not load arbitrary user Python files yet.
   - Use this phase for internal modules such as audit logging, observability, skill learning, memory review, and safety policies.

2. **Phase C: User-defined Python hook files**
   - Add explicit support for user-authored hook modules after Phase B is stable.
   - Require a permission model, sandbox boundary, timeout, error isolation, and explicit enablement.
   - Treat user hook files as powerful local automation, not ordinary configuration.

This staged route keeps the runtime extensible without making arbitrary code execution part of the first implementation.

## Non-Goals

- Do not build a hook system only for skills.
- Do not put skill learning logic directly into `AgentSession.chat()`.
- Do not make EventBus replace hooks. EventBus handles cross-component asynchronous events; hooks handle ordered agent lifecycle interception.
- Do not allow third-party or user Python hook files in Phase B.
- Do not let observe-only hooks mutate or control execution.

## Hook Sources

### Phase B Sources

- **Core runtime**: registers lifecycle behavior needed by the agent itself.
- **Built-in modules**: memory, audit, observability, skill learning, safety.
- **YAML config**: enables or disables known built-in hooks and configures their mode.
- **Tests**: register hooks directly for deterministic verification.

### Phase C Sources

- **Workspace Python hooks**: user-owned Python files loaded from an explicit hook directory.
- **Plugin hooks**: plugin-owned hook modules with declared permissions.
- **Skill hooks**: only after the same permission and lifecycle rules exist for plugins.

## Hook Points

Use stable string values so config, plugins, and tests can reference them.

```python
class HookPoint(str, Enum):
    SESSION_START = "session.start"
    SESSION_END = "session.end"
    MESSAGE_RECEIVED = "message.received"
    CONTEXT_BUILT = "context.built"
    BEFORE_LLM_CALL = "llm.before_call"
    AFTER_LLM_CALL = "llm.after_call"
    BEFORE_TOOL_CALL = "tool.before_call"
    AFTER_TOOL_CALL = "tool.after_call"
    BEFORE_RESPONSE = "response.before"
    AFTER_RESPONSE = "response.after"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    FORK_CREATED = "fork.created"
    SUBAGENT_STARTED = "subagent.started"
    SUBAGENT_COMPLETED = "subagent.completed"
    ERROR = "error"
```

`response.after` and `task.completed` are intentionally separate. A response can be intermediate or clarification; task completion means the runtime or a completion detector believes the current task episode is complete enough for post-task learning, audit, or review.

## Hook Actions

```python
HookAction = Literal[
    "observe",
    "modify",
    "skip",
    "abort",
    "fork",
    "enqueue",
]
```

- `observe`: read-only inspection.
- `modify`: replace or patch allowed fields in the hook context.
- `skip`: skip the current unit, such as one tool call.
- `abort`: stop the current turn with a message.
- `fork`: request a child session or subagent run.
- `enqueue`: schedule a background task.

Each hook point defines which actions it accepts. Unsupported actions are ignored or converted to an error result according to policy.

## Hook Context

Use one common context shape with point-specific optional fields.

```python
@dataclass
class HookContext:
    hook_point: HookPoint
    session_id: str
    agent_id: str
    parent_session_id: str | None = None
    source: str | None = None
    state: SessionState | None = None
    turn_id: str | None = None
    user_message: str | None = None
    assistant_response: str | None = None
    messages: list[dict] | None = None
    tools: list[dict] | None = None
    llm_response: dict | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result: str | None = None
    failed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
```

Context must carry enough information for audit, safety, observability, skill learning, and fork-based background work without forcing each subsystem to inspect agent internals.

## Hook Result

```python
@dataclass
class HookResult:
    action: HookAction = "observe"
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
```

`data` contains point-specific modifications, for example:

- `{"message": "..."}`
- `{"messages": [...], "tools": [...]}`
- `{"response": "..."}`
- `{"tool_args": {...}}`
- `{"tool_result": "..."}`

## Hook Permissions

Every registered hook receives permissions. Phase B built-ins can define permissions in code; YAML only enables or configures those built-ins. Phase C user hooks must declare and receive explicit permissions.

```yaml
permissions:
  observe: true
  modify_message: false
  modify_llm_request: false
  modify_llm_response: false
  modify_tool_call: false
  modify_tool_result: false
  modify_response: false
  skip_tool: false
  abort_turn: false
  fork_agent: false
  enqueue_task: false
  write_files: false
  network: false
```

Default rules:

- Observe-only hooks cannot return `modify`, `skip`, `abort`, `fork`, or `enqueue`.
- Built-in hooks get explicit permissions by handler.
- YAML cannot grant a built-in hook permissions it did not declare in code.
- Phase C user hooks require explicit enablement and permission declaration.

## Phase B Configuration

```yaml
hooks:
  enabled: true
  builtin:
    audit_log:
      enabled: true
      point: tool.after_call
    skill_learning:
      enabled: true
      point: task.completed
      mode: auto_draft
      min_confidence: medium
    sensitive_response_filter:
      enabled: false
      point: response.before
```

The config names map only to registered built-in hook factories. Unknown names should be ignored with a warning, not imported dynamically.

## Phase C Configuration

```yaml
hooks:
  user:
    local_quality_gate:
      enabled: true
      module: workspace/hooks/local_quality_gate.py
      handler: handle
      point: response.before
      timeout_ms: 1000
      permissions:
        observe: true
        modify_response: true
```

Phase C loader requirements:

- Only load from allowed workspace hook directories.
- No wildcard import from arbitrary paths.
- Enforce timeout per handler.
- Catch and isolate exceptions.
- Log hook execution and failures.
- Require explicit permissions per hook.

## Runtime Integration

The runtime should create or receive one `HookManager` per session or per agent instance. For now, session-level is simplest because hooks often need session state and test isolation.

Integration points:

- `Agent.new_session()` triggers `session.start`.
- `AgentSession.chat()` triggers:
  - `message.received`
  - `context.built`
  - `llm.before_call`
  - `llm.after_call`
  - `response.before`
  - `response.after`
  - `task.completed` or `task.failed`
  - `error`
- `_execute_tool_calls()` triggers:
  - `tool.before_call`
  - `tool.after_call`
- `fork_session()` triggers `fork.created`.
- `subagent_dispatch` triggers:
  - `subagent.started`
  - `subagent.completed`

## Backward Compatibility

Keep existing callback APIs:

- `set_on_tool_call(fn)`
- `set_on_thinking(fn)`
- `set_confirm_fn(fn)`

Bridge them internally:

- `set_on_tool_call` should behave like an `after_tool_call` observer.
- `set_on_thinking` should behave like an `after_llm_call` observer for reasoning content.
- `set_confirm_fn` remains a permission-specific callback and does not need to become a hook in Phase B.

## Skill Learning Use Case

Skill learning is a built-in Phase B hook, not hardcoded runtime logic.

```text
task.completed
  -> SkillLearningHook
      -> evaluate reusable workflow candidate
      -> if worth learning:
            fork learning child session
            child agent follows skill-creator
            write workspace/skills/.drafts/<skill>/SKILL.md
            notify main session
```

Manual skill creation remains separate:

```text
/skill create
  -> build_skill_creator_task(origin="user")
  -> current agent or forked agent executes it
```

Both paths share `build_skill_creator_task`.

## EventBus Boundary

Hooks are ordered, in-process lifecycle interceptors. EventBus is asynchronous cross-component messaging.

Allowed relationship:

- A hook can publish an EventBus event as an observer.
- EventBus can start tasks that register hooks.

Disallowed relationship:

- EventBus should not be used to implement `before_*` blocking or mutation semantics.

## Implementation Phases

### Phase 1: Core Hook Types and Manager

- Add `src/SmallShrimp/core/hooks.py`.
- Implement `HookPoint`, `HookResult`, `HookPermissions`, `RegisteredHook`, `HookManager`.
- Add tests for register, unregister, priority, modify, skip, abort, permission enforcement, exception isolation.

### Phase 2: Runtime Lifecycle Integration

- Add `hooks` to `AgentSession`.
- Trigger hooks at message, context, LLM, tool, response, task, error, fork, and subagent points.
- Keep old callbacks working.
- Add tests with fake LLM/tool registries.

### Phase 3: Built-in YAML Hooks

- Add a small built-in hook registry.
- Load enabled built-in hooks from `workspace/config.user.yaml`.
- Add audit/logging example and skill-learning stub.

### Phase 4: Skill Learning Hook

- Implement candidate evaluation.
- Fork learning child session.
- Generate learned skill draft through `skill-creator`.
- Add `/skill drafts`, `/skill approve`, `/skill reject` later.

### Phase 5: User Python Hooks

- Add controlled loader for `workspace/hooks/*.py`.
- Enforce permissions, timeout, path boundary, and error isolation.
- Add audit trail for user hooks.

## Acceptance Criteria

- Hooks cover the full agent lifecycle, not only skill learning.
- Built-in hooks can be enabled through YAML.
- Hook actions are permission checked.
- Existing CLI callbacks still work.
- Hook failures do not crash the agent unless the hook is explicitly configured as critical.
- A `task.completed` hook can later trigger fork-based skill learning without touching `AgentSession.chat()` again.
