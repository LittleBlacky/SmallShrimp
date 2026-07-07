"""Regex-based skill matching — pre-filter before LLM call.

Adapted from ZLAgent's pick_skill_for_message().
"""
from __future__ import annotations

from typing import Optional, Sequence

from .skill_def import SkillDef


def match_skill(
    message_text: str,
    skills: Sequence[SkillDef],
) -> Optional[str]:
    """Pick the best-matching skill by trigger keyword overlap.

    Returns the skill id/name if a match is found, None otherwise.
    Skills are scored by: trigger hits, confidence, trigger count, and id.
    """
    if not message_text or not skills:
        return None

    text_lower = message_text.lower()
    candidates: list[tuple[int, float, int, str]] = []

    for skill in skills:
        if getattr(skill, "status", None) in ("archived", "deprecated"):
            continue
        triggers = getattr(skill, "triggers", None)
        if not triggers:
            continue
        hits = 0
        for trigger in triggers:
            if not trigger:
                continue
            if trigger.lower() in text_lower:
                hits += 1
        if hits == 0:
            continue
        skill_id = skill.id or skill.name
        confidence = float(getattr(skill, "confidence", 0.0) or 0.0)
        candidates.append((hits, confidence, len(triggers), skill_id))

    if not candidates:
        return None

    # Sort by hits desc, confidence desc, total triggers desc, then id asc.
    candidates.sort(key=lambda c: (-c[0], -c[1], -c[2], c[3]))
    return candidates[0][3]
