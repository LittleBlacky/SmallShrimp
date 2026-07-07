# Product Vision

SmallShrimp is a multi-endpoint, continuously evolving personal assistant Agent.

It is not positioned as a generic agent framework. Its home field is the user's computer: files, documents, slides, spreadsheets, code projects, messages, schedules, browser context, work habits, and personal routines. Different users have different professions, task scenes, life patterns, and quality standards. SmallShrimp's long-term goal is to understand those differences deeply enough to help the user, approximate the user, improve beyond the user, and finally feed that improvement back to the user.

## Core Definition

SmallShrimp is an assistant Agent that can respond across multiple endpoints, operate the user's computer with permission, and autonomously derive specialized sub-agents for different task scenes.

Examples of task-scene agents:

- A writing agent for Word documents, reports, emails, and long-form drafts.
- A presentation agent for PPT planning, slide editing, and narrative polish.
- A spreadsheet agent for XLSX analysis, reconciliation, modeling, and reporting.
- A coding agent for local repositories, tests, refactors, and debugging.
- A personal operations agent for schedules, habits, reminders, and recurring workflows.

These agents are not separate products. They are scene-specific projections of the same evolving personal assistant, backed by shared memory, user profile, preferences, tools, and feedback loops.

## Four Stages

### Stage 1: Task Assistant

The first stage is helping users complete concrete tasks.

SmallShrimp should understand the user's request, inspect local context, call tools, operate files, run commands, interact through multiple endpoints, and produce a complete task outcome rather than only giving advice.

The emphasis is task closure: understand, plan, act, verify, and report.

### Stage 2: User Clone

The second stage is becoming increasingly familiar with the user's task scenes, profile, and preferences.

SmallShrimp should learn:

- What the user does for work and life.
- What files, projects, people, tools, and workflows matter.
- How the user prefers tasks to be completed.
- What quality bar, style, tone, format, and decision rules the user tends to apply.
- What methods repeatedly work for similar problems.

At this stage, SmallShrimp should summarize task methodology and persist it as reusable knowledge. When similar tasks appear, it should complete them faster and closer to the user's own way of working.

### Stage 3: Self-Evolution

The third stage begins after SmallShrimp can approximately replace the user for common task scenes.

At this stage, it should not merely repeat user habits. It should improve them through reflection, failure learning, workflow optimization, better tools, and accumulated methodology.

The goal is to become more efficient, more useful, and more correct than the user's previous baseline, while still respecting user intent and permission boundaries.

### Stage 4: Human Improvement Loop

The fourth stage is feeding improvement back to the user.

SmallShrimp should not only complete tasks for the user. It should help the user become better at life and work by surfacing patterns, teaching better methods, correcting recurring inefficiencies, and helping the user build stronger habits.

The relationship is symbiotic: the agent improves by learning from the human, and the human improves by receiving distilled insight from the agent.

## Harness Engineering Principles

SmallShrimp follows a harness engineering direction: the intelligence does not come only from the model. It comes from the system wrapped around the model.

The harness includes:

- Context assembly: selecting the right files, history, memories, and task-scene knowledge.
- Tool access: safely operating files, shell, web, documents, spreadsheets, code, and external services.
- Permission and safety: making computer control powerful but bounded and auditable.
- Memory: preserving user profile, task facts, preferences, recurring workflows, and lessons learned.
- Feedback loops: recording outcomes, failures, corrections, and reusable methods.
- Observability: making actions, decisions, and tool results inspectable.
- Multi-agent specialization: deriving scene-specific agents while keeping a shared user model.

The model is the reasoning core. The harness is what makes the assistant reliable, personal, useful, and capable of long-term evolution.

## Product North Star

SmallShrimp should become the assistant that understands the user's computer, work, life, preferences, and growth direction well enough to:

1. Finish tasks for the user.
2. Finish tasks the way the user would.
3. Improve the way those tasks are done.
4. Help the user become better through that improvement.

