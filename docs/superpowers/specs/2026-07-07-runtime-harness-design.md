# SmallShrimp Runtime Harness Design

## Goal

Define the long-term runtime harness for SmallShrimp so future changes do not drift into an unstructured agent framework. SmallShrimp is a multi-endpoint, continuously evolving personal assistant Agent. Its runtime must help the user complete tasks, learn the user's scenes and preferences, consolidate reusable methods, evolve those methods over time, and eventually feed improvements back to the user.

This document is a route map and architectural guardrail. It is not an implementation batch. Each implementation step still requires a small design discussion, user confirmation, focused tests, and an isolated commit.

## Product Definition

SmallShrimp is not a generic agent framework. It is a personal assistant that lives around the user's computer and work context.

The product stages are:

1. **Task assistance**: understand requests, call tools, operate local resources, and respond through multiple endpoints.
2. **User clone approximation**: learn task scenes, user profile, preferences, feedback, and reusable methods.
3. **Self-evolution**: improve methods through reflection, failure learning, skill consolidation, and repeated task outcomes.
4. **Human improvement loop**: feed useful summaries, habits, workflows, and corrections back to the user so the user and assistant improve together.

Every runtime subsystem should be judged against these stages.

## Guiding Principles

- **One loop, many harness layers**: the agent loop remains the stable core. Hooks, skills, memory, permissions, tools, compaction, tasks, subagents, cron, and channels attach around it.
- **Personal assistant first**: abstractions must serve the user's computer, files, work patterns, and preferences. Do not optimize for a generic agent framework API.
- **User-visible control**: automatic learning, skill creation, memory extraction, and autonomous actions must be observable, reviewable, and disableable.
- **Small reversible steps**: every implementation step must be small enough to discuss before coding, test independently, and commit separately.
- **Methods become assets**: repeated successful workflows should become versioned skills, memories, or task templates.
- **Runtime before autonomy**: do not build aggressive autonomous behavior until hooks, memory, skills, task graph, permissions, and observability are stable.

## Runtime Pipeline

The target runtime pipeline is:

```text
endpoint input
  -> normalize inbound message
  -> session/runtime context lookup
  -> user prompt hooks
  -> pending cron/background/task notifications
  -> memory prefetch
  -> skill catalog attachment
  -> context compaction guard
  -> system prompt assembly
  -> before LLM hooks
  -> LLM call with recovery
  -> after LLM hooks
  -> if tool calls:
       -> before tool hooks
       -> permission and guardrail checks
       -> tool dispatch / MCP dispatch / background dispatch
       -> after tool hooks
       -> append tool results
       -> continue loop
     else:
       -> before response hooks
       -> deliver response to endpoint
       -> after response hooks
       -> stop/task completion hooks
       -> background learning and consolidation
```

The exact code does not need to become one large file. The important invariant is that every subsystem has a defined position in the runtime lifecycle.

## Layer Responsibilities

### 1. Endpoint Layer

Responsible for receiving and sending messages.

Examples:

- CLI
- desktop app
- web/server workers
- WeCom, Telegram, Discord, or future channels

Endpoint code should normalize messages into a common runtime request and should not contain its own assistant behavior.

### 2. Runtime Session Layer

Responsible for the main assistant episode.

Responsibilities:

- create or resume sessions
- hold session state
- run the loop
- invoke hooks in deterministic order
- coordinate memory, skills, compaction, tools, and response delivery
- expose trace data for debugging and review

This layer is the center of the harness.

### 3. Hook Layer

Responsible for ordered lifecycle interception.

Hooks are not only for skills. They are the extension layer for:

- audit and observability
- permissions and safety
- memory extraction
- skill learning
- task completion detection
- background jobs
- fork/subagent lifecycle
- user or developer custom behavior

Hooks should not replace the event bus. Hooks are ordered lifecycle interception. Event bus is asynchronous cross-component communication.

### 4. Skill Layer

Responsible for reusable task methods.

Target behavior:

- load skill metadata into a lightweight catalog
- load full `SKILL.md` only when needed
- support standard skill layout with optional `references/`, `scripts/`, and `assets/`
- version each skill independently
- allow user-created skills
- allow agent-suggested draft skills after task completion
- keep auto-created skills reviewable before activation

Skills are the primary long-term carrier for reusable methodology.

### 5. Memory Layer

Responsible for long-term personal context.

Memory categories:

- `user`: user profile, style, preferences, constraints
- `feedback`: corrections and preferences learned from user reactions
- `project`: durable project context and architecture facts
- `reference`: where to find recurring resources
- `methodology`: reusable ways of doing tasks, possibly promotable into skills

Target behavior:

- keep a lightweight memory index available
- select relevant memories per turn
- extract new memories after stable stopping points
- consolidate, deduplicate, and age out stale memories
- let the user inspect, edit, disable, or delete memories

Memory and skills are related but distinct. Memory stores facts and preferences. Skills store reusable procedures.

### 6. Context and Compaction Layer

Responsible for keeping the active context useful.

Responsibilities:

- preserve the active goal
- preserve user constraints
- preserve unresolved tool results and task state
- summarize stale tool outputs
- avoid losing information that should become memory
- emit pre/post compact hooks

Compaction should be a runtime service, not an isolated utility hidden in a specific channel.

### 7. Tool and Permission Layer

Responsible for controlled action.

Responsibilities:

- assemble available tools for the current session
- include built-in, skill-provided, MCP, and channel-specific tools according to policy
- run permission checks before execution
- run guardrails for file, shell, network, and external tools
- support background dispatch for slow tasks
- record tool traces for review

Permission decisions should be visible in runtime traces.

### 8. Task Graph Layer

Responsible for durable work coordination.

It is separate from the current-turn todo list.

Todo list:

- short-lived
- helps the current agent stay oriented
- lives inside a session or turn

Task graph:

- durable
- can span sessions
- supports dependencies
- supports ownership and claiming
- supports subagent and future autonomous workers

Initial task fields should be conservative:

- `id`
- `title`
- `description`
- `status`
- `owner`
- `blocked_by`
- `created_at`
- `updated_at`
- `source_session_id`

### 9. Fork and Subagent Layer

Responsible for clean context delegation.

Definitions:

- `fork`: create an independent child context from current context.
- `subagent`: run work inside a forked context and return a result.
- `teammate`: longer-lived worker that can communicate and claim durable tasks.

Fork is generic infrastructure. Skill creation is only one use case.

Target uses:

- skill creation
- memory extraction
- research subtasks
- code review
- parallel file inspection
- autonomous task execution

### 10. Learning and Evolution Layer

Responsible for improving SmallShrimp over time.

Sources:

- successful tasks
- failed tasks
- user corrections
- repeated workflows
- repeated tool sequences
- repeated project-specific methods

Outputs:

- memory updates
- skill drafts
- skill version updates
- task templates
- user feedback summaries
- runtime configuration suggestions

This layer must stay reviewable. Early versions should generate drafts and suggestions, not silently rewrite the assistant's behavior.

### 11. Observability Layer

Responsible for explaining what happened.

Runtime traces should eventually answer:

- which endpoint started the turn
- which hooks ran
- which memory entries were loaded
- which skills were listed or loaded
- which tools were offered
- which tools executed
- which permissions were requested or denied
- whether compaction occurred
- whether learning tasks were scheduled
- whether fork/subagents were created

Without observability, autonomous learning becomes hard to trust.

## Hook Event Map

The current hook foundation should evolve toward this event map.

### Current Core Events

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

### Proposed Additions

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

These additions should not all be implemented at once. They define the direction so future features attach consistently.

## Skill System Direction

The target skill format should follow the common `SKILL.md` pattern:

```text
skill-name/
  SKILL.md
  references/
  scripts/
  assets/
```

Frontmatter should support common fields:

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

Implementation direction:

1. catalog only at startup or session assembly
2. full content through explicit load
3. optional `context: fork` later for isolated skill execution
4. auto-created skills enter draft state first
5. user approval activates or rejects drafts

## Memory System Direction

The target memory model should support both file-backed and indexed implementations. The architectural contract matters more than the first storage engine.

Required behaviors:

- memory index assembly before LLM calls
- relevant memory selection before context build
- extraction after stop/task completion
- consolidation as a background job
- audit trail for changes
- user review and edit path

Early implementation should focus on:

- stop-hook extraction interface
- draft memory records
- deterministic tests with mocked extraction
- no silent irreversible memory rewrites

## Task and Autonomy Direction

Autonomy should be introduced only after durable tasks exist.

Order:

1. persistent task graph
2. task lifecycle tools
3. subagent can work on explicit forked tasks
4. worker can claim unowned unblocked tasks
5. idle polling behind config flag
6. user-visible summaries and approvals

Do not start with fully autonomous workers. Start with durable task state and manual claiming.

## Development Roadmap

### Phase 1: Runtime Harness Specification

Deliverables:

- this design document
- agreement on runtime pipeline
- agreement that future implementation proceeds in small reviewable steps

No runtime behavior changes are required in this phase.

### Phase 2: Hook Lifecycle Alignment

Deliverables:

- refine hook event map
- add missing event names conservatively
- document which events are implemented vs reserved
- add trace-friendly hook execution records

This phase should not change skills or memory behavior yet.

### Phase 3: Skill Loading Standardization

Deliverables:

- skill catalog attachment
- explicit `load_skill` behavior
- standard frontmatter parser coverage
- draft/active skill state model design

This phase should not implement autonomous skill creation yet.

### Phase 4: Memory Extraction Interface

Deliverables:

- stop/task-completed hook interface for memory extraction
- draft memory records
- memory review path
- consolidation design stub

This phase should avoid silent automatic mutation of important user memory.

### Phase 5: Persistent Task Graph

Deliverables:

- task data model
- create/list/get/claim/complete behavior
- dependency checks
- tests for blocked tasks and ownership

This phase prepares for autonomous agents but does not require autonomy.

### Phase 6: Forked Workflows

Deliverables:

- fork context policies
- subagent result contract
- fork use cases for skill drafting and memory extraction
- trace linkage from parent to child session

### Phase 7: Controlled Autonomy

Deliverables:

- opt-in idle task scanning
- safe task claiming
- background execution limits
- user-visible progress summaries
- shutdown and failure recovery policy

### Phase 8: User Improvement Feedback

Deliverables:

- task retrospectives
- user-facing improvement suggestions
- workflow reports
- skill and memory review summaries

## Near-Term Recommendation

The next implementation should be small:

1. Review and approve this runtime harness design.
2. Create a focused implementation plan for **Hook Lifecycle Alignment** only.
3. Implement hook event additions and runtime trace records in one small batch.
4. Stop for review before touching skill loading or memory extraction.

This keeps the project moving toward the long-term personal assistant vision without mixing multiple subsystems in one change.

## Non-Goals for the Next Batch

- Do not rebuild the whole agent loop.
- Do not add autonomous workers yet.
- Do not rewrite the memory system yet.
- Do not replace the existing skill loader yet.
- Do not introduce a marketplace or plugin system yet.
- Do not create broad compatibility forwarding files.

## Open Decisions

These require user confirmation before implementation:

1. Should reserved hook events be added to the enum now, or only documented until used?
2. Should runtime traces be stored in session history, a separate trace store, or only emitted in logs first?
3. Should skill catalog attachment happen before or after memory prefetch in the first implementation?
4. Should automatic memory extraction create inactive drafts by default?
5. Should task graph storage live under `workspace/tasks/` or the existing runtime workspace structure?

## Acceptance Criteria for Future Work

Every future implementation batch should satisfy:

- user reviewed the small design before code
- changes are limited to one subsystem boundary
- tests cover new behavior
- full test suite passes before final handoff
- git commit contains one logical change
- final summary explains what changed and what remains intentionally out of scope
