from __future__ import annotations

from dataclasses import dataclass, field

from ..commands.base import AgentTask
from ..definitions.skill_creator_task import SkillCreatorRequest, build_skill_creator_task


@dataclass(frozen=True)
class SkillLearningCandidate:
    """A reusable workflow that may become a learned skill."""

    skill_id: str
    requirement: str
    reason: str
    confidence: str
    evidence: list[str] = field(default_factory=list)


def build_auto_skill_creator_task(
    candidate: SkillLearningCandidate,
    recent_context: str,
) -> AgentTask:
    """Build a draft-only skill-creator task from an automatic learning candidate."""
    return build_skill_creator_task(
        SkillCreatorRequest(
            skill_id=candidate.skill_id,
            requirement=candidate.requirement,
            recent_context=recent_context,
            origin="learned",
            target_path=f"workspace/skills/.drafts/{candidate.skill_id}/SKILL.md",
            candidate_reason=candidate.reason,
            confidence=candidate.confidence,
            evidence=candidate.evidence,
            draft=True,
        )
    )
