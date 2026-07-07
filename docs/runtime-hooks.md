# Runtime Hooks

SmallShrimp hooks are ordered runtime lifecycle interceptors for the personal assistant runtime. They are separate from EventBus: hooks run inside the agent turn and may observe, modify, skip, abort, fork, or enqueue work. EventBus remains the asynchronous cross-component messaging layer.

## Configuration Shape

Hooks are enabled from trusted local runtime configuration:

```yaml
hooks:
  enabled: true
  builtin: {}
  user: {}
```

If `hooks.enabled` is not `true`, neither built-in hooks nor user Python hooks are registered for the session.

## Phase B: Built-In Hooks

Built-in hooks are implemented by SmallShrimp code and enabled through YAML. YAML can select and configure built-in hook factories, but it does not import arbitrary Python code.

```yaml
hooks:
  enabled: true
  builtin:
    audit_log:
      enabled: true
      point: tool.after_call
      path: workspace/.cache/hooks/audit.log
    skill_learning:
      enabled: false
      point: task.completed
      mode: auto_draft
```

Unknown built-in hook names are ignored. Malformed built-in entries are skipped rather than blocking the session.

## Phase C: User Python Hooks

User hooks are explicitly enabled Python handlers loaded from `workspace/hooks/`. The loader resolves the final path and rejects traversal, absolute paths outside `workspace/hooks/`, missing files, and non-`.py` modules.

```yaml
hooks:
  enabled: true
  user:
    local_quality_gate:
      enabled: true
      module: hooks/local_quality_gate.py
      handler: handle
      point: response.before
      timeout_ms: 1000
      priority: 250
      permissions:
        observe: true
        modify_response: true
```

Example handler:

```python
from src.SmallShrimp.core.hooks import HookResult


async def handle(ctx):
    response = ctx.assistant_response or ""
    return HookResult.modify({"response": response.strip()})
```

Sync handlers are also supported. Each user hook is wrapped with `asyncio.wait_for`; timeout returns an observe result and does not fail the agent turn. Import errors, missing handlers, and invalid hook points are logged and skipped.

## Hook Points

Current hook point values:

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

## Permissions

Hook actions are permission-gated by `HookManager`. A hook without the matching permission is downgraded to observe behavior, so user hooks cannot modify messages, responses, tools, or control flow unless explicitly granted.

Common permission fields include:

- `observe`
- `modify_message`
- `modify_llm_request`
- `modify_llm_response`
- `modify_tool_args`
- `modify_tool_result`
- `modify_response`
- `skip_tool`
- `abort`
- `fork_agent`
- `enqueue_task`
- `write_files`

Unknown permission keys in user config are ignored.

## Built-In Examples

Audit every tool result:

```yaml
hooks:
  enabled: true
  builtin:
    audit_log:
      enabled: true
      point: tool.after_call
      path: workspace/.cache/hooks/audit.log
```

Enable the skill-learning stub on task completion:

```yaml
hooks:
  enabled: true
  builtin:
    skill_learning:
      enabled: true
      point: task.completed
```

## User Hook Examples

Trim assistant responses before returning them:

```yaml
hooks:
  enabled: true
  user:
    trim_response:
      enabled: true
      module: hooks/trim_response.py
      handler: handle
      point: response.before
      permissions:
        observe: true
        modify_response: true
```

`workspace/hooks/trim_response.py`:

```python
from src.SmallShrimp.core.hooks import HookResult


async def handle(ctx):
    return HookResult.modify({"response": (ctx.assistant_response or "").strip()})
```

Observe tool calls without modifying them:

```yaml
hooks:
  enabled: true
  user:
    observe_tools:
      enabled: true
      module: hooks/observe_tools.py
      handler: handle
      point: tool.after_call
      timeout_ms: 500
      permissions:
        observe: true
```

## Design Boundaries

- Hooks are runtime lifecycle interceptors; EventBus is still used for asynchronous cross-component messaging.
- User Python hooks are general runtime extensions, not a skills-only mechanism.
- Fork and subagent hook points are generic lifecycle points and are not coupled to skill creation.
- Local configuration is trusted for enabling built-in hooks, while user Python hook files still pass path, timeout, and permission controls.
