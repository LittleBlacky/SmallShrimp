# Skill Evolution Design

## Status

Approved direction: versioned skills, draft approval, usage feedback, and curator-driven continuous evolution.

## Product Context

SmallShrimp is a multi-endpoint, continuously evolving personal assistant Agent. Its long-term goal is not only to finish tasks, but to learn the user's task scenes, preferences, methods, and quality standards, then improve those methods over time.

Skills are the procedural memory layer for that vision.

A skill is not just a reusable prompt. A skill is a versioned methodology asset: it describes when a method applies, how to execute it, what tools and context it needs, how to match the user's preferences, how to verify the result, and how it has changed through repeated use.

## Goals

1. Turn completed tasks into reusable skills when the task produced a repeatable method.
2. Let existing skills evolve from real task outcomes, user corrections, and failures.
3. Give every skill independent version management and rollback points.
4. Keep generated skills safe through draft approval and risk-based activation.
5. Prevent skill clutter through usage tracking, curator review, merge, deprecation, and archival.
6. Support scene-specific agents with private skills while preserving shared user knowledge.

## Non-Goals

1. Do not replace memory. Memory stores facts, preferences, events, and user profile data. Skills store repeatable methods.
2. Do not auto-activate high-risk computer-control skills without review.
3. Do not create a large marketplace or remote distribution system in the first implementation.
4. Do not require every task to generate a skill.
5. Do not keep compatibility forwarding modules for new skill architecture paths.

## Skill Definition

SmallShrimp should define a skill as:

> A reusable, versioned method for completing a class of tasks in a specific scene, with trigger rules, execution steps, user preferences, required context, tool requirements, safety boundaries, and verification criteria.

Skill content should answer:

1. What task scene does this skill cover?
2. When should it be used?
3. What context should be gathered before using it?
4. What steps should the assistant follow?
5. What user preferences should be respected?
6. What tools or permissions are required?
7. What risks or stop conditions exist?
8. How should the result be verified?
9. What task outcomes caused this version to exist?

## Skill Package Layout

SmallShrimp skills should follow the common Markdown-first skill package convention used by mainstream agent skill systems.

`SKILL.md` is the only required file. It is the entrypoint the assistant reads to understand when and how to use the skill. Its frontmatter must stay compatible with the common convention: `name` and `description` are required; everything else is optional. SmallShrimp-specific evolution fields must be additive extensions, not a separate incompatible standard.

The first implementation should use a file-based layout under the user workspace:

```text
workspace/skills/
├── coding.code-review/
│   ├── SKILL.md
│   ├── skill.yaml
│   ├── CHANGELOG.md
│   ├── usage.json
│   ├── scripts/
│   ├── references/
│   ├── assets/
│   ├── tests/
│   └── versions/
│       ├── 1.0.0/
│       │   └── SKILL.md
│       ├── 1.1.0/
│       │   └── SKILL.md
│       └── 2.0.0/
│           └── SKILL.md
└── document.meeting-summary/
    ├── SKILL.md
    ├── skill.yaml
    ├── CHANGELOG.md
    ├── usage.json
    └── versions/
```

`SKILL.md` is the active entrypoint and must exist for every skill.

`skill.yaml` is optional. It is useful when metadata becomes too large for frontmatter or when system-managed fields should be kept out of the human-authored instructions. A normal user-authored skill must not require `skill.yaml`.

`versions/<semver>/SKILL.md` is optional. It stores immutable historical versions when rollback is needed. Updating a versioned skill creates a new version directory instead of overwriting historical content.

`scripts/` is optional. It stores helper scripts referenced by relative path from `SKILL.md`.

`references/` is optional. It stores longer instructions, API notes, methodology references, or examples that should not bloat the main `SKILL.md`.

`assets/` is optional. It stores templates, images, document samples, and other reusable resources.

`tests/` is optional. It stores examples or validation material for the skill.

`CHANGELOG.md` is optional. It explains human-readable changes.

`usage.json` is optional and system-managed. It records usage and outcome data for retrieval ranking and curator decisions.

## Skill Metadata

SmallShrimp should support metadata in two forms:

1. `SKILL.md` frontmatter for simple and user-authored skills.
2. Optional `skill.yaml` for system-managed metadata, large metadata, or versioned skills.

For the first implementation, frontmatter should be enough for normal skills. The minimum valid skill should look like this:

```yaml
---
name: Code Review
description: Review local code changes for bugs, regressions, missing tests, and maintainability risks.
---
```

SmallShrimp can additionally understand optional fields:

```yaml
---
id: coding.code-review
name: Code Review
description: Review a local code change for bugs, regressions, missing tests, and maintainability risks.
scene: coding
origin: learned
status: active
created_by: agent
version: 1.1.0
source_task_id: task_20260707_001
confidence: 0.82
risk_level: medium
pinned: false
requires_approval: false
triggers:
  - code review
  - review this change
  - 帮我审查代码
related_skills:
  - coding.test-verification
last_used_at: "2026-07-07T12:00:00+08:00"
usage_count: 14
success_count: 11
failure_count: 1
user_correction_count: 2
---
```

Required fields:

1. `name`
2. `description`

Optional fields:

1. `id`
2. `triggers`
3. `scene`
4. `origin`
5. `status`
6. `created_by`
7. `version`
8. `source_task_id`
9. `confidence`
10. `risk_level`
11. `pinned`
12. `requires_approval`
13. `related_skills`
14. `last_used_at`
15. usage counters

`description` remains the primary discovery and trigger surface. `triggers` may improve matching, but a skill without `triggers` is still valid.

### Skill Origin

Skill origin values:

1. `user`: user-authored, imported, configured, or explicitly confirmed skills. These have the highest priority. SmallShrimp must not automatically overwrite, merge, or archive them.
2. `learned`: skills distilled from daily tasks, reflections, user corrections, and successful workflows. These may start as drafts and can be improved by the system under the risk policy.
3. `bundled`: built-in product skills. These provide defaults and can be overridden by user skills.

`created_by` remains useful for audit history, but `origin` is the product-level ownership model.

## Version Rules

Skills use semantic versions:

1. Patch version: wording changes, trigger improvements, minor step clarification, small verification fixes.
2. Minor version: new supported scenario, new tool step, new user preference handling, stronger validation.
3. Major version: changed methodology, changed risk boundary, changed execution strategy, or incompatible behavior.

Every version update must record:

1. Previous version.
2. New version.
3. Source task or reflection that caused the update.
4. Reason for the update.
5. Risk level.
6. Whether user approval was required.
7. Rollback target.

Historical versions should be treated as immutable. Rollback means making an older version the active version again and writing a new changelog entry.

## Lifecycle

Skill status values:

1. `draft`: generated or imported, but not active for automatic retrieval.
2. `active`: available for matching and use.
3. `deprecated`: still readable, but should not be selected unless explicitly requested.
4. `archived`: hidden from ordinary discovery and preserved for audit/history.

Lifecycle transitions:

```text
new task outcome
  -> draft skill or update proposal
  -> risk review
  -> active skill
  -> usage feedback
  -> version update, merge, deprecate, or archive
```

High-risk skills must enter `draft` first. Low-risk, high-confidence skills may become active automatically if configured by the user.

## Risk Policy

Risk levels:

1. `low`: reading, summarizing, formatting, planning, local analysis without modification.
2. `medium`: editing files, running tests, changing local project state, preparing external messages.
3. `high`: sending messages, deleting/moving files, changing credentials, running broad shell commands, controlling desktop applications.

Default activation policy:

1. Low-risk generated skills may auto-activate when confidence is high.
2. Medium-risk generated skills should default to draft unless the user opts into auto-activation.
3. High-risk generated skills always require user approval.

## Task-to-Skill Pipeline

After a task completes, SmallShrimp should run a post-task reflection step:

1. Summarize the task goal, context, actions, tools, user corrections, and outcome.
2. Decide whether the task produced reusable methodology.
3. Match the task against existing skills.
4. Choose one of four actions:
   - create a new skill draft
   - propose an update to an existing skill
   - record usage only
   - do nothing
5. If creating or updating a skill, generate a structured proposal.
6. Apply risk policy.
7. Persist the result as draft or active.
8. Update usage and reflection records.

The pipeline should be conservative. A task should only generate or update a skill when the method is repeatable and meaningfully useful.

## Skill Update Pipeline

When a task uses an existing skill, SmallShrimp should track:

1. Was the skill selected manually or automatically?
2. Did the skill help complete the task faster?
3. Did the user correct the output?
4. Did any step fail?
5. Did the assistant need extra steps not covered by the skill?
6. Did the final task outcome meet verification standards?

If enough evidence accumulates, SmallShrimp should propose a new skill version.

Update proposal types:

1. Add missing step.
2. Remove obsolete step.
3. Improve trigger rules.
4. Add user preference.
5. Add safety warning.
6. Add verification command or checklist.
7. Split broad skill into narrower skills.
8. Merge duplicate skills.

## Curator

The skill curator is a maintenance process for procedural memory.

Responsibilities:

1. Promote useful draft skills.
2. Find duplicate or overlapping skills.
3. Merge skills that represent the same methodology.
4. Deprecate skills that repeatedly fail.
5. Archive unused low-confidence generated skills.
6. Protect pinned or user-authored skills from automatic archival.
7. Suggest skill improvements from recurring user corrections.

The curator should only automatically modify skills with `origin: learned`. User-authored, bundled, or pinned skills require explicit approval before destructive lifecycle changes.

## Retrieval Behavior

Skill retrieval should happen in two stages:

1. Lightweight discovery: load metadata only.
2. Full skill loading: load `SKILL.md` only for matched skills.

Ranking signals:

1. Trigger match.
2. Scene match.
3. User-selected agent.
4. Confidence.
5. Success rate.
6. Recency.
7. Pinned status.
8. Risk compatibility with current task.

The assistant should not blindly load many full skills into context. It should load concise metadata first, then escalate to the full skill only when likely useful.

## Scene Agents

Scene-specific agents may own private skill collections:

```text
workspace/agents/
└── coding/
    └── skills/
        └── code-review/
```

The first implementation can keep all skills in `workspace/skills/` and use the `scene` metadata to scope retrieval. Later implementations can add agent-local skill overlays.

Skill lookup order:

1. Current scene agent private skills.
2. User workspace global skills.
3. Bundled product skills.

The user profile and memory system remain shared across agents.

## Relationship With Memory

Memory and skills should remain separate:

1. Memory stores user facts, preferences, entities, events, and context.
2. Skills store procedures, methods, workflows, and verification standards.
3. Reflections explain what happened and why a skill or memory changed.

Example:

1. Memory: "The user prefers concise Chinese summaries for project planning."
2. Skill: "When writing project planning docs, use sections for goal, architecture, phases, tests, and risks."
3. Reflection: "The previous plan was too broad, so the skill was updated to force smaller implementation phases."

## User Experience

SmallShrimp should expose basic skill management commands:

1. List skills by scene, status, risk, or source.
2. Show active skill metadata and current version.
3. Read full skill content.
4. Show changelog.
5. Approve a draft skill.
6. Reject a draft skill.
7. Pin or unpin a skill.
8. Archive or restore a skill.
9. Roll back to a previous version.

Generated proposals should be readable before activation.

## Implementation Phases

### Phase 1: Markdown-First Versioned Skill Model

Keep `SKILL.md` as the required entrypoint. Add standard frontmatter parsing, optional SmallShrimp extension fields, optional `skill.yaml` support, optional version directories, changelog handling, usage tracking, and loader support for active versions.

### Phase 2: Task-to-Skill Drafting

Add post-task reflection output that can generate draft skills or update proposals.

### Phase 3: Skill Usage Feedback

Track skill selection, outcome quality, user corrections, failure points, and task verification results.

### Phase 4: Curator

Add curator logic for promotion, merge suggestions, deprecation, archival, and version update proposals.

### Phase 5: Scene Agent Integration

Connect skill ranking to scene agents and allow private scene skills.

## Testing Strategy

Tests should cover:

1. Parsing standard `SKILL.md` frontmatter with only `name` and `description` required.
2. Loading active `SKILL.md` from frontmatter `version` or optional `skill.yaml` metadata.
3. Discovering skills without loading full content.
4. Creating a new draft skill.
5. Creating a new version without mutating previous versions.
6. Rolling back active version.
7. Recording usage outcomes.
8. Applying risk policy for generated skills.
9. Curator ignoring pinned and user-authored skills.
10. Retrieval ranking using scene, triggers, confidence, and usage.

Use temporary workspace directories. Tests must not write to real user workspace data.

## Open Design Decisions

The following decisions should be made during implementation planning:

1. Whether skill version files should duplicate full `SKILL.md` content or store structured diffs.
2. Whether `usage.json` should be per-skill or centralized for faster analytics.
3. Whether generated skill proposals should be represented as files, memory events, or both.
4. How much of task trace should be stored in the skill changelog versus linked through `source_task_id`.

Default choices for the first implementation:

1. Store full `SKILL.md` per version.
2. Use per-skill `usage.json`.
3. Store generated proposals as files under the skill directory.
4. Keep changelog concise and link detailed task trace by `source_task_id`.

## Success Criteria

The design is successful when:

1. A completed task can produce a reusable draft skill.
2. Existing skills can evolve through independent versions.
3. Skill versions can be inspected and rolled back.
4. Skill matching prefers reliable and scene-appropriate skills.
5. Curator can prevent skill clutter without touching pinned or user-authored skills.
6. The system reinforces SmallShrimp's product direction: task completion, user cloning, self-evolution, and user improvement.
