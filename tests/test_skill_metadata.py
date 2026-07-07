from __future__ import annotations

from pathlib import Path

import yaml

from src.SmallShrimp.core.definitions.skill_metadata import SkillMetadata


def test_skill_metadata_minimum_standard_fields(tmp_path: Path):
    metadata_path = tmp_path / "skill.yaml"
    metadata_path.write_text(
        yaml.safe_dump(
            {
                "name": "Code Review",
                "description": "Review code changes.",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    metadata = SkillMetadata.from_yaml_file(metadata_path)

    assert metadata.name == "Code Review"
    assert metadata.description == "Review code changes."
    assert metadata.id == ""
    assert metadata.triggers == []
    assert metadata.origin == "user"
    assert metadata.status == "active"
    assert metadata.created_by == "user"
    assert metadata.version is None
    assert metadata.confidence == 1.0
    assert metadata.risk_level == "low"


def test_skill_metadata_from_yaml_file_with_extensions(tmp_path: Path):
    metadata_path = tmp_path / "skill.yaml"
    metadata_path.write_text(
        yaml.safe_dump(
            {
                "id": "coding.code-review",
                "name": "Code Review",
                "description": "Review code changes.",
                "scene": "coding",
                "origin": "learned",
                "status": "active",
                "created_by": "agent",
                "version": "1.1.0",
                "confidence": 0.82,
                "risk_level": "medium",
                "triggers": ["code review", "审查代码"],
                "related_skills": ["coding.test-verification"],
                "pinned": True,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    metadata = SkillMetadata.from_yaml_file(metadata_path)

    assert metadata.id == "coding.code-review"
    assert metadata.name == "Code Review"
    assert metadata.scene == "coding"
    assert metadata.origin == "learned"
    assert metadata.status == "active"
    assert metadata.created_by == "agent"
    assert metadata.version == "1.1.0"
    assert metadata.confidence == 0.82
    assert metadata.risk_level == "medium"
    assert metadata.triggers == ["code review", "审查代码"]
    assert metadata.related_skills == ["coding.test-verification"]
    assert metadata.pinned is True


def test_skill_metadata_requires_standard_fields(tmp_path: Path):
    metadata_path = tmp_path / "skill.yaml"
    metadata_path.write_text("id: missing-fields\n", encoding="utf-8")

    try:
        SkillMetadata.from_yaml_file(metadata_path)
        assert False, "missing required fields should raise ValueError"
    except ValueError as exc:
        assert "name" in str(exc)
        assert "description" in str(exc)


def test_skill_metadata_to_dict_roundtrip():
    metadata = SkillMetadata(
        id="document.summary",
        name="Document Summary",
        description="Summarize documents.",
        triggers=["summary"],
        scene="document",
        origin="learned",
        status="draft",
        created_by="agent",
        version="0.1.0",
        confidence=0.4,
        risk_level="low",
    )

    data = metadata.to_dict()

    assert data["id"] == "document.summary"
    assert data["origin"] == "learned"
    assert data["status"] == "draft"
    assert data["version"] == "0.1.0"
    assert data["risk_level"] == "low"
    assert data["triggers"] == ["summary"]
