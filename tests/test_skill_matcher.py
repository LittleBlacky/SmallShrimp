from __future__ import annotations

from src.SmallShrimp.core.definitions.skill_def import SkillDef
from src.SmallShrimp.core.definitions.skill_matcher import match_skill


def test_match_skill_ignores_archived_skills():
    skills = [
        SkillDef(
            id="aaa.archived-review",
            name="Archived Review",
            description="Old",
            triggers=["review"],
            status="archived",
            confidence=1.0,
        ),
        SkillDef(
            id="zzz.active-review",
            name="Active Review",
            description="New",
            triggers=["review"],
            status="active",
            confidence=0.5,
        ),
    ]

    assert match_skill("please review this", skills) == "zzz.active-review"


def test_match_skill_ignores_deprecated_skills():
    skills = [
        SkillDef(
            id="aaa.deprecated-review",
            name="Deprecated Review",
            description="Old",
            triggers=["review"],
            status="deprecated",
            confidence=1.0,
        ),
        SkillDef(
            id="zzz.active-review",
            name="Active Review",
            description="New",
            triggers=["review"],
            status="active",
            confidence=0.5,
        ),
    ]

    assert match_skill("please review this", skills) == "zzz.active-review"


def test_match_skill_uses_confidence_as_tie_breaker():
    skills = [
        SkillDef(id="aaa-low", name="Low", description="", triggers=["review"], confidence=0.2),
        SkillDef(id="zzz-high", name="High", description="", triggers=["review"], confidence=0.9),
    ]

    assert match_skill("review this", skills) == "zzz-high"
