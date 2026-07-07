from __future__ import annotations

from dataclasses import dataclass

from ..commands.base import AgentTask


@dataclass(frozen=True)
class SkillCreatorRequest:
    """Input for building a skill-creator agent task."""

    skill_id: str
    requirement: str
    recent_context: str
    origin: str = "user"
    target_path: str | None = None
    candidate_reason: str | None = None
    confidence: str | None = None
    evidence: list[str] | None = None
    draft: bool = False


def build_skill_creator_task(request: SkillCreatorRequest) -> AgentTask:
    """Build a task that asks the current agent to use skill-creator."""
    target_path = request.target_path or f"workspace/skills/{request.skill_id}/SKILL.md"
    mode_line = "Automatic learned skill candidate" if request.origin == "learned" else "User-requested skill creation"
    evidence = "\n".join(f"- {item}" for item in request.evidence or [])
    if not evidence:
        evidence = "- No separate evidence list; use the recent completed-task context."

    draft_policy = (
        "- Do not silently enable the learned skill; create it as a draft for user review.\n"
        if request.draft
        else ""
    )

    prompt = f"""Load and follow the `skill-creator` skill.

{mode_line}
- Origin: {request.origin}
- Skill id/name: {request.skill_id}
- User requirement: {request.requirement}
- Candidate reason: {request.candidate_reason or "User explicitly requested skill creation."}
- Confidence: {request.confidence or "user-requested"}

Evidence:
{evidence}

Recent completed-task context to learn from:
{request.recent_context}

Create or update the skill package at `{target_path}` using the standard skill package convention:
- `SKILL.md` is required.
- YAML frontmatter must include only `name` and `description`.
- Add optional `scripts/`, `references/`, `assets/`, or `tests/` only when they are useful for this requirement.
- Keep `SKILL.md` concise and move long reusable context into references.
- Include realistic test prompts or validation guidance when useful.
- Do not overwrite an existing skill without explicit user confirmation.
{draft_policy}
Use the recent completed-task context as source material:
- Summarize the actual workflow, decisions, failures, fixes, validation steps, and reusable heuristics.
- Convert the observed workflow into procedural instructions another agent can reuse.
- Preserve only transferable methodology; remove incidental project details unless they are needed for triggering or execution.
- Do not create a generic starter skill when there is enough completed-task context to extract a concrete method.

Before writing files, inspect any existing skill-creator guidance available in this project or runtime skill roots, then create or update `{target_path}`.
"""
    return AgentTask(prompt=prompt)
