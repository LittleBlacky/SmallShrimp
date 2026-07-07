# Markdown-First Versioned Skill Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first phase of SmallShrimp's skill evolution system: standard Markdown-first skills with optional SmallShrimp metadata, optional version history, usage tracking, rollback support when versions exist, and compatibility with existing flat `SKILL.md` skills.

**Architecture:** Keep `SKILL.md` as the only required skill entrypoint. Require only standard frontmatter fields `name` and `description`; treat `id`, `triggers`, `origin`, `status`, `version`, and other SmallShrimp fields as optional extensions. Keep the current `src/SmallShrimp/core/definitions` boundary, but split optional skill management concerns into small files: metadata parsing, usage tracking, and loader orchestration. Existing callers of `SkillDef`, `SkillLoader.discover_skills()`, `SkillLoader.load()`, and `create_skill_tool()` must continue to work.

**Tech Stack:** Python 3.11+, dataclasses, pathlib, yaml, pytest, `conda run -n smallshrimp`.

---

## File Structure

- Modify: `src/SmallShrimp/core/definitions/skill_def.py`
  - Keep the legacy frontmatter parser.
  - Require only `name` and `description` for standard skills.
  - Extend `SkillDef` with optional version metadata fields while preserving existing constructor compatibility.
- Create: `src/SmallShrimp/core/definitions/skill_metadata.py`
  - Define `SkillMetadata`, allowed origin/status/risk values, frontmatter/YAML parsing, and serialization.
- Create: `src/SmallShrimp/core/definitions/skill_usage.py`
  - Define usage records and helpers for `usage.json`.
- Modify: `src/SmallShrimp/core/definitions/skill_loader.py`
  - Support Markdown-first skills, optional `skill.yaml`, and optional version directories.
  - Add metadata-only discovery.
  - Add new version creation and rollback helpers.
- Modify: `src/SmallShrimp/core/definitions/skill_matcher.py`
  - Ignore archived/deprecated skills in automatic matching unless explicitly passed.
  - Prefer reliable skills using confidence and usage metadata as tie-breakers.
- Modify: `src/SmallShrimp/tools/skill_tool.py`
  - Expose current version/status in skill tool description.
  - Continue returning full active content.
- Modify: `src/SmallShrimp/core/commands/handlers.py`
  - Fix skill loader import to the layered path.
  - Add `/skill list`, `/skill show <name>`, `/skill versions <name>`, and `/skill rollback <name> <version>` command branches.
- Create: `tests/test_skill_metadata.py`
- Create: `tests/test_skill_usage.py`
- Modify: `tests/test_skill_def.py`
- Modify: `tests/test_skill_loader.py`
- Modify: `tests/test_skill_tool.py`
- Modify: `tests/test_commands.py`

## Task 1: Add Markdown-First Skill Metadata Model

**Files:**
- Create: `src/SmallShrimp/core/definitions/skill_metadata.py`
- Test: `tests/test_skill_metadata.py`

- [ ] **Step 1: Write failing metadata parsing tests**

Create `tests/test_skill_metadata.py`:

```python
from __future__ import annotations

from pathlib import Path

import yaml

from src.SmallShrimp.core.definitions.skill_metadata import SkillMetadata


def test_skill_metadata_from_yaml_file(tmp_path: Path):
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
    assert metadata.status == "active"
    assert metadata.created_by == "agent"
    assert metadata.origin == "learned"
    assert metadata.version == "1.1.0"
    assert metadata.confidence == 0.82
    assert metadata.risk_level == "medium"
    assert metadata.triggers == ["code review", "审查代码"]
    assert metadata.related_skills == ["coding.test-verification"]
    assert metadata.pinned is True


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


def test_skill_metadata_requires_core_fields(tmp_path: Path):
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
        scene="document",
        origin="learned",
        status="draft",
        created_by="agent",
        version="0.1.0",
        confidence=0.4,
        risk_level="low",
        triggers=["summary"],
    )

    data = metadata.to_dict()

    assert data["id"] == "document.summary"
    assert data["origin"] == "learned"
    assert data["status"] == "draft"
    assert data["risk_level"] == "low"
    assert data["triggers"] == ["summary"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_metadata.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `skill_metadata`.

- [ ] **Step 3: Implement metadata model**

Create `src/SmallShrimp/core/definitions/skill_metadata.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

SkillStatus = Literal["draft", "active", "deprecated", "archived"]
SkillRiskLevel = Literal["low", "medium", "high"]
SkillCreatedBy = Literal["agent", "user", "bundled"]
SkillOrigin = Literal["user", "learned", "bundled"]

REQUIRED_METADATA_FIELDS = (
    "name",
    "description",
)


@dataclass
class SkillMetadata:
    name: str
    description: str
    id: str = ""
    triggers: list[str] = field(default_factory=list)
    scene: str | None = None
    origin: SkillOrigin = "user"
    status: SkillStatus = "active"
    created_by: SkillCreatedBy = "user"
    version: str | None = None
    confidence: float = 1.0
    risk_level: SkillRiskLevel = "low"
    source_task_id: str | None = None
    pinned: bool = False
    requires_approval: bool = False
    related_skills: list[str] = field(default_factory=list)
    last_used_at: str | None = None
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    user_correction_count: int = 0

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> "SkillMetadata":
        path = Path(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillMetadata":
        missing = [field_name for field_name in REQUIRED_METADATA_FIELDS if field_name not in data]
        if missing:
            raise ValueError(f"Missing required skill metadata fields: {', '.join(missing)}")

        status = data.get("status", "active")
        if status not in ("draft", "active", "deprecated", "archived"):
            raise ValueError(f"Invalid skill status: {status}")

        risk_level = data.get("risk_level", "low")
        if risk_level not in ("low", "medium", "high"):
            raise ValueError(f"Invalid skill risk_level: {risk_level}")

        created_by = data.get("created_by", "user")
        if created_by not in ("agent", "user", "bundled"):
            raise ValueError(f"Invalid skill created_by: {created_by}")

        origin = data.get("origin", "user")
        if origin not in ("user", "learned", "bundled"):
            raise ValueError(f"Invalid skill origin: {origin}")

        triggers = data.get("triggers") or []
        if not isinstance(triggers, list):
            raise ValueError("Skill metadata triggers must be a list")

        return cls(
            name=str(data["name"]),
            description=str(data["description"]),
            id=str(data.get("id", "") or ""),
            triggers=[str(trigger) for trigger in triggers],
            scene=str(data["scene"]) if data.get("scene") is not None else None,
            origin=origin,
            status=status,
            created_by=created_by,
            version=str(data["version"]) if data.get("version") is not None else None,
            confidence=float(data.get("confidence", 1.0)),
            risk_level=risk_level,
            source_task_id=data.get("source_task_id"),
            pinned=bool(data.get("pinned", False)),
            requires_approval=bool(data.get("requires_approval", False)),
            related_skills=[str(skill) for skill in data.get("related_skills", [])],
            last_used_at=data.get("last_used_at"),
            usage_count=int(data.get("usage_count", 0)),
            success_count=int(data.get("success_count", 0)),
            failure_count=int(data.get("failure_count", 0)),
            user_correction_count=int(data.get("user_correction_count", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "scene": self.scene,
            "origin": self.origin,
            "status": self.status,
            "created_by": self.created_by,
            "version": self.version,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "source_task_id": self.source_task_id,
            "pinned": self.pinned,
            "requires_approval": self.requires_approval,
            "related_skills": list(self.related_skills),
            "last_used_at": self.last_used_at,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "user_correction_count": self.user_correction_count,
        }

    def write_yaml_file(self, path: str | Path) -> None:
        Path(path).write_text(
            yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_metadata.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/SmallShrimp/core/definitions/skill_metadata.py tests/test_skill_metadata.py
git commit -m "feat: add skill metadata model"
```

## Task 2: Extend SkillDef Without Breaking Legacy Skills

**Files:**
- Modify: `src/SmallShrimp/core/definitions/skill_def.py`
- Modify: `tests/test_skill_def.py`

- [ ] **Step 1: Write failing tests for new fields and legacy behavior**

Append to `tests/test_skill_def.py`:

```python

def test_skill_def_parses_extended_frontmatter():
    content = """---
id: coding.review
name: Code Review
description: Review code.
scene: coding
status: active
created_by: agent
version: 1.0.0
confidence: 0.9
risk_level: medium
triggers:
  - review
---

# Code Review

Review the change.
"""
    skill = SkillDef._parse(content)

    assert skill.id == "coding.review"
    assert skill.scene == "coding"
    assert skill.status == "active"
    assert skill.created_by == "agent"
    assert skill.version == "1.0.0"
    assert skill.confidence == 0.9
    assert skill.risk_level == "medium"
    assert skill.triggers == ["review"]


def test_skill_def_parses_standard_minimum_frontmatter():
    content = """---
name: Code Review
description: Review code changes.
---

# Code Review
"""
    skill = SkillDef._parse(content)

    assert skill.id == ""
    assert skill.name == "Code Review"
    assert skill.description == "Review code changes."
    assert skill.triggers is None


def test_skill_def_to_dict_includes_metadata_when_present():
    skill = SkillDef(
        id="coding.review",
        name="Code Review",
        description="Review code.",
        scene="coding",
        status="active",
        created_by="agent",
        version="1.0.0",
        confidence=0.9,
        risk_level="medium",
        triggers=["review"],
    )

    data = skill.to_dict()

    assert data["scene"] == "coding"
    assert data["status"] == "active"
    assert data["version"] == "1.0.0"
    assert data["confidence"] == 0.9
    assert data["risk_level"] == "medium"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_def.py -q
```

Expected: FAIL because `SkillDef` does not yet expose metadata fields.

- [ ] **Step 3: Update `SkillDef`**

Replace `src/SmallShrimp/core/definitions/skill_def.py` with:

```python
from __future__ import annotations

"""Skill 定义。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SkillDef:
    """Skill 定义。

    The base fields keep compatibility with legacy `SKILL.md` files. The
    metadata fields support versioned skills without forcing all callers to
    understand `skill.yaml`.
    """

    id: str
    name: str
    description: str
    content: str = ""
    triggers: list[str] | None = None
    scene: str | None = None
    status: str | None = None
    created_by: str | None = None
    version: str | None = None
    confidence: float | None = None
    risk_level: str | None = None
    source_task_id: str | None = None
    pinned: bool = False
    requires_approval: bool = False
    related_skills: list[str] | None = None
    last_used_at: str | None = None
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    user_correction_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
        }
        optional_values = {
            "triggers": self.triggers,
            "scene": self.scene,
            "status": self.status,
            "created_by": self.created_by,
            "version": self.version,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "source_task_id": self.source_task_id,
            "pinned": self.pinned,
            "requires_approval": self.requires_approval,
            "related_skills": self.related_skills,
            "last_used_at": self.last_used_at,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "user_correction_count": self.user_correction_count,
        }
        for key, value in optional_values.items():
            if value not in (None, [], ""):
                data[key] = value
        return data

    @classmethod
    def from_file(cls, path: str | Path) -> "SkillDef":
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        return cls._parse(content)

    @classmethod
    def _parse(cls, content: str) -> "SkillDef":
        if content.startswith("---"):
            parts = content.split("\n---", 1)
            if len(parts) >= 2:
                frontmatter_text = parts[0].replace("---", "").strip()
                frontmatter = yaml.safe_load(frontmatter_text) if frontmatter_text else {}
                body = parts[1].strip()
                return cls.from_parts(frontmatter or {}, body)
        return cls(id="", name="", description="", content=content.strip())

    @classmethod
    def from_parts(cls, metadata: dict[str, Any], content: str) -> "SkillDef":
        return cls(
            id=str(metadata.get("id", "") or ""),
            name=str(metadata.get("name", "") or ""),
            description=str(metadata.get("description", "") or ""),
            content=content,
            triggers=metadata.get("triggers"),
            scene=metadata.get("scene"),
            status=metadata.get("status"),
            created_by=metadata.get("created_by"),
            version=str(metadata["version"]) if metadata.get("version") is not None else None,
            confidence=float(metadata["confidence"]) if metadata.get("confidence") is not None else None,
            risk_level=metadata.get("risk_level"),
            source_task_id=metadata.get("source_task_id"),
            pinned=bool(metadata.get("pinned", False)),
            requires_approval=bool(metadata.get("requires_approval", False)),
            related_skills=metadata.get("related_skills"),
            last_used_at=metadata.get("last_used_at"),
            usage_count=int(metadata.get("usage_count", 0)),
            success_count=int(metadata.get("success_count", 0)),
            failure_count=int(metadata.get("failure_count", 0)),
            user_correction_count=int(metadata.get("user_correction_count", 0)),
        )
```

- [ ] **Step 4: Run tests**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_def.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/SmallShrimp/core/definitions/skill_def.py tests/test_skill_def.py
git commit -m "feat: extend skill definitions with metadata"
```

## Task 3: Add Skill Usage Tracking

**Files:**
- Create: `src/SmallShrimp/core/definitions/skill_usage.py`
- Test: `tests/test_skill_usage.py`

- [ ] **Step 1: Write failing usage tests**

Create `tests/test_skill_usage.py`:

```python
from __future__ import annotations

from pathlib import Path

from src.SmallShrimp.core.definitions.skill_usage import SkillUsageLog


def test_usage_log_records_success(tmp_path: Path):
    usage_path = tmp_path / "usage.json"
    log = SkillUsageLog.load(usage_path)

    log.record(version="1.0.0", outcome="success", task_id="task-1")
    log.save(usage_path)

    loaded = SkillUsageLog.load(usage_path)

    assert loaded.usage_count == 1
    assert loaded.success_count == 1
    assert loaded.failure_count == 0
    assert loaded.records[0]["version"] == "1.0.0"
    assert loaded.records[0]["task_id"] == "task-1"


def test_usage_log_records_user_correction(tmp_path: Path):
    usage_path = tmp_path / "usage.json"
    log = SkillUsageLog.load(usage_path)

    log.record(version="1.0.0", outcome="corrected", task_id="task-2")

    assert log.usage_count == 1
    assert log.success_count == 0
    assert log.failure_count == 0
    assert log.user_correction_count == 1


def test_usage_log_rejects_unknown_outcome(tmp_path: Path):
    log = SkillUsageLog.load(tmp_path / "usage.json")

    try:
        log.record(version="1.0.0", outcome="unknown")
        assert False, "unknown outcome should fail"
    except ValueError as exc:
        assert "Unknown skill usage outcome" in str(exc)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_usage.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement usage log**

Create `src/SmallShrimp/core/definitions/skill_usage.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import json

SkillUsageOutcome = Literal["success", "failure", "corrected"]


@dataclass
class SkillUsageLog:
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    user_correction_count: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "SkillUsageLog":
        path = Path(path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        return cls(
            usage_count=int(data.get("usage_count", 0)),
            success_count=int(data.get("success_count", 0)),
            failure_count=int(data.get("failure_count", 0)),
            user_correction_count=int(data.get("user_correction_count", 0)),
            records=list(data.get("records", [])),
        )

    def record(
        self,
        *,
        version: str,
        outcome: SkillUsageOutcome,
        task_id: str | None = None,
        note: str | None = None,
    ) -> None:
        if outcome not in ("success", "failure", "corrected"):
            raise ValueError(f"Unknown skill usage outcome: {outcome}")

        self.usage_count += 1
        if outcome == "success":
            self.success_count += 1
        elif outcome == "failure":
            self.failure_count += 1
        elif outcome == "corrected":
            self.user_correction_count += 1

        record = {
            "version": version,
            "outcome": outcome,
            "task_id": task_id,
            "note": note,
            "used_at": datetime.now(timezone.utc).isoformat(),
        }
        self.records.append(record)

    def to_dict(self) -> dict[str, Any]:
        return {
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "user_correction_count": self.user_correction_count,
            "records": self.records,
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_usage.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/SmallShrimp/core/definitions/skill_usage.py tests/test_skill_usage.py
git commit -m "feat: add skill usage tracking"
```

## Task 4: Load Markdown-First and Optional Versioned Skills

**Files:**
- Modify: `src/SmallShrimp/core/definitions/skill_loader.py`
- Modify: `tests/test_skill_loader.py`

- [ ] **Step 1: Write failing loader tests**

Append to `tests/test_skill_loader.py`:

```python

def create_versioned_skill_dir(parent: Path, name: str) -> Path:
    skill_dir = parent / name
    version_dir = skill_dir / "versions" / "1.1.0"
    version_dir.mkdir(parents=True)
    (version_dir / "SKILL.md").write_text("# Active Version\n\nUse this version.", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("# Stale Entrypoint\n\nDo not load this when version exists.", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        """---
id: coding.code-review
name: Code Review
description: Review code.
scene: coding
origin: learned
status: active
created_by: agent
version: 1.1.0
confidence: 0.8
risk_level: medium
triggers:
  - review
---

# Stale Entrypoint

Do not load this when version exists.
""",
        encoding="utf-8",
    )
    return skill_dir


def test_skill_loader_loads_active_version_from_frontmatter():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        create_versioned_skill_dir(skills_dir, "coding.code-review")

        loader = SkillLoader(skills_dir)
        skill = loader.load("coding.code-review")

        assert skill.id == "coding.code-review"
        assert skill.version == "1.1.0"
        assert "Active Version" in skill.content
        assert "Stale Entrypoint" not in skill.content


def test_skill_loader_discovers_metadata_without_archived_by_default():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        create_versioned_skill_dir(skills_dir, "coding.code-review")
        archived = create_versioned_skill_dir(skills_dir, "old.skill")
        (archived / "SKILL.md").write_text(
            """---
id: old.skill
name: Old Skill
description: Old.
scene: coding
origin: learned
status: archived
created_by: agent
version: 1.1.0
confidence: 0.1
risk_level: low
triggers:
  - old
---

# Old
""",
            encoding="utf-8",
        )

        loader = SkillLoader(skills_dir)
        skills = loader.discover_skills()

        assert [skill.id for skill in skills] == ["coding.code-review"]


def test_skill_loader_lists_versions():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        skill_dir = create_versioned_skill_dir(skills_dir, "coding.code-review")
        (skill_dir / "versions" / "1.0.0").mkdir()
        (skill_dir / "versions" / "1.0.0" / "SKILL.md").write_text("# Old", encoding="utf-8")

        loader = SkillLoader(skills_dir)

        assert loader.list_versions("coding.code-review") == ["1.0.0", "1.1.0"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_loader.py -q
```

Expected: FAIL because versioned loading is not implemented.

- [ ] **Step 3: Implement versioned loading**

Update `src/SmallShrimp/core/definitions/skill_loader.py`:

```python
"""Skill 加载器。"""

from __future__ import annotations

from pathlib import Path

from .skill_def import SkillDef
from .skill_metadata import SkillMetadata


class SkillLoader:
    """加载和管理 Skill 定义。"""

    def __init__(self, skills_dir: Path = Path("workspace/skills")) -> None:
        self.skills_dir = skills_dir

    def discover_skills(self, include_archived: bool = False) -> list[SkillDef]:
        """发现所有可自动使用的 Skill。

        Legacy skills without `skill.yaml` remain visible. Versioned skills
        default to excluding archived skills.
        """
        if not self.skills_dir.exists():
            return []

        skills: list[SkillDef] = []
        for skill_dir in sorted(self.skills_dir.iterdir(), key=lambda path: path.name):
            if not skill_dir.is_dir():
                continue
            try:
                skill = self._load_from_dir(skill_dir)
            except FileNotFoundError:
                continue
            if skill.status == "archived" and not include_archived:
                continue
            skills.append(skill)
        return skills

    def discover_skill_metadata(self, include_archived: bool = False) -> list[SkillMetadata]:
        if not self.skills_dir.exists():
            return []

        metadata_items: list[SkillMetadata] = []
        for skill_dir in sorted(self.skills_dir.iterdir(), key=lambda path: path.name):
            metadata_path = skill_dir / "skill.yaml"
            if not metadata_path.exists():
                continue
            metadata = SkillMetadata.from_yaml_file(metadata_path)
            if metadata.status == "archived" and not include_archived:
                continue
            metadata_items.append(metadata)
        return metadata_items

    def load(self, name: str) -> SkillDef:
        """根据目录名或 skill id 加载 Skill。"""
        direct_dir = self.skills_dir / name
        if direct_dir.exists():
            return self._load_from_dir(direct_dir)

        for metadata in self.discover_skill_metadata(include_archived=True):
            if metadata.id == name or metadata.name == name:
                return self._load_from_dir(self.skills_dir / metadata.id)

        raise FileNotFoundError(f"Skill not found: {name}")

    def list_skills(self) -> list[str]:
        if not self.skills_dir.exists():
            return []
        return [skill.id or skill.name for skill in self.discover_skills()]

    def list_versions(self, name: str) -> list[str]:
        skill_dir = self._resolve_skill_dir(name)
        versions_dir = skill_dir / "versions"
        if not versions_dir.exists():
            return []
        return sorted(path.name for path in versions_dir.iterdir() if (path / "SKILL.md").exists())

    def _resolve_skill_dir(self, name: str) -> Path:
        direct_dir = self.skills_dir / name
        if direct_dir.exists():
            return direct_dir
        for metadata in self.discover_skill_metadata(include_archived=True):
            if metadata.id == name or metadata.name == name:
                return self.skills_dir / metadata.id
        raise FileNotFoundError(f"Skill not found: {name}")

    def _load_from_dir(self, skill_dir: Path) -> SkillDef:
        legacy_file = skill_dir / "SKILL.md"
        if legacy_file.exists():
            skill = SkillDef.from_file(legacy_file)
            if skill.version:
                version_file = skill_dir / "versions" / skill.version / "SKILL.md"
                if version_file.exists():
                    skill.content = version_file.read_text(encoding="utf-8").strip()
            return skill

        metadata_path = skill_dir / "skill.yaml"
        if metadata_path.exists():
            return self._load_versioned_skill(skill_dir, metadata_path)

        raise FileNotFoundError(f"No skill definition found in {skill_dir}")

    def _load_versioned_skill(self, skill_dir: Path, metadata_path: Path) -> SkillDef:
        metadata = SkillMetadata.from_yaml_file(metadata_path)
        version = metadata.version
        version_file = skill_dir / "versions" / version / "SKILL.md" if version else skill_dir / "SKILL.md"
        if not version_file.exists():
            version_file = skill_dir / "SKILL.md"
        if not version_file.exists():
            raise FileNotFoundError(f"Skill content not found for {metadata.id} version {version}")

        content = version_file.read_text(encoding="utf-8").strip()
        data = metadata.to_dict()
        return SkillDef.from_parts(data, content)
```

- [ ] **Step 4: Run loader tests**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_loader.py -q
```

Expected: PASS.

- [ ] **Step 5: Run existing skill tests**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_def.py tests/test_skill_loader.py tests/test_skill_tool.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/SmallShrimp/core/definitions/skill_loader.py tests/test_skill_loader.py
git commit -m "feat: load versioned skills"
```

## Task 5: Add Version Creation and Rollback

**Files:**
- Modify: `src/SmallShrimp/core/definitions/skill_loader.py`
- Modify: `tests/test_skill_loader.py`

- [ ] **Step 1: Write failing version management tests**

Append to `tests/test_skill_loader.py`:

```python

def test_skill_loader_creates_new_version_without_mutating_old_version():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        create_versioned_skill_dir(skills_dir, "coding.code-review")

        loader = SkillLoader(skills_dir)
        loader.create_version(
            "coding.code-review",
            version="1.2.0",
            content="# New Version\n\nUpdated method.",
            reason="Add verification step.",
            source_task_id="task-123",
        )

        old_content = (skills_dir / "coding.code-review" / "versions" / "1.1.0" / "SKILL.md").read_text(encoding="utf-8")
        new_content = (skills_dir / "coding.code-review" / "versions" / "1.2.0" / "SKILL.md").read_text(encoding="utf-8")
        active = loader.load("coding.code-review")

        assert "Active Version" in old_content
        assert "New Version" in new_content
        assert active.version == "1.2.0"
        assert "New Version" in active.content


def test_skill_loader_rolls_back_active_version():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        create_versioned_skill_dir(skills_dir, "coding.code-review")

        loader = SkillLoader(skills_dir)
        loader.create_version(
            "coding.code-review",
            version="1.2.0",
            content="# New Version\n\nUpdated method.",
            reason="Add verification step.",
        )
        loader.rollback("coding.code-review", "1.1.0", reason="Regression in 1.2.0")

        skill = loader.load("coding.code-review")

        assert skill.version == "1.1.0"
        assert "Active Version" in skill.content


def test_skill_loader_rejects_duplicate_version():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        create_versioned_skill_dir(skills_dir, "coding.code-review")
        loader = SkillLoader(skills_dir)

        try:
            loader.create_version("coding.code-review", version="1.1.0", content="# Duplicate", reason="duplicate")
            assert False, "duplicate version should fail"
        except FileExistsError:
            pass
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_loader.py -q
```

Expected: FAIL because `create_version()` and `rollback()` do not exist.

- [ ] **Step 3: Implement version helpers**

Add these methods to `SkillLoader`:

```python
    def create_version(
        self,
        name: str,
        *,
        version: str,
        content: str,
        reason: str,
        source_task_id: str | None = None,
    ) -> SkillDef:
        skill_dir = self._resolve_skill_dir(name)
        metadata_path = skill_dir / "skill.yaml"
        if not metadata_path.exists():
            raise ValueError(f"Cannot create version for legacy skill without skill.yaml: {name}")

        metadata = SkillMetadata.from_yaml_file(metadata_path)
        version_dir = skill_dir / "versions" / version
        if version_dir.exists():
            raise FileExistsError(f"Skill version already exists: {metadata.id}@{version}")

        version_dir.mkdir(parents=True)
        (version_dir / "SKILL.md").write_text(content.strip() + "\n", encoding="utf-8")

        previous_version = metadata.version
        metadata.version = version
        if source_task_id:
            metadata.source_task_id = source_task_id
        metadata.write_yaml_file(metadata_path)

        self._append_changelog(
            skill_dir,
            title=f"Version {version}",
            lines=[
                f"- Previous version: {previous_version}",
                f"- New version: {version}",
                f"- Reason: {reason}",
                f"- Source task: {source_task_id or 'not specified'}",
            ],
        )
        return self.load(metadata.id)

    def rollback(self, name: str, version: str, *, reason: str) -> SkillDef:
        skill_dir = self._resolve_skill_dir(name)
        metadata_path = skill_dir / "skill.yaml"
        if not metadata_path.exists():
            raise ValueError(f"Cannot roll back legacy skill without skill.yaml: {name}")

        target_file = skill_dir / "versions" / version / "SKILL.md"
        if not target_file.exists():
            raise FileNotFoundError(f"Skill version not found: {name}@{version}")

        metadata = SkillMetadata.from_yaml_file(metadata_path)
        previous_version = metadata.version
        metadata.version = version
        metadata.write_yaml_file(metadata_path)

        self._append_changelog(
            skill_dir,
            title=f"Rollback to {version}",
            lines=[
                f"- Previous version: {previous_version}",
                f"- Active version: {version}",
                f"- Reason: {reason}",
            ],
        )
        return self.load(metadata.id)

    def _append_changelog(self, skill_dir: Path, *, title: str, lines: list[str]) -> None:
        changelog_path = skill_dir / "CHANGELOG.md"
        existing = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else "# Changelog\n"
        entry = "\n\n## " + title + "\n" + "\n".join(lines) + "\n"
        changelog_path.write_text(existing.rstrip() + entry, encoding="utf-8")
```

- [ ] **Step 4: Run loader tests**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_loader.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/SmallShrimp/core/definitions/skill_loader.py tests/test_skill_loader.py
git commit -m "feat: add skill version rollback"
```

## Task 6: Rank Skills With Metadata Signals

**Files:**
- Modify: `src/SmallShrimp/core/definitions/skill_matcher.py`
- Create or modify: `tests/test_skill_matcher.py`

- [ ] **Step 1: Write failing matcher tests**

Create `tests/test_skill_matcher.py` if it does not exist, or append:

```python
from __future__ import annotations

from src.SmallShrimp.core.definitions.skill_def import SkillDef
from src.SmallShrimp.core.definitions.skill_matcher import match_skill


def test_match_skill_ignores_archived_skills():
    skills = [
        SkillDef(
            id="archived.review",
            name="Archived Review",
            description="Old",
            triggers=["review"],
            status="archived",
            confidence=1.0,
        ),
        SkillDef(
            id="active.review",
            name="Active Review",
            description="New",
            triggers=["review"],
            status="active",
            confidence=0.5,
        ),
    ]

    assert match_skill("please review this", skills) == "active.review"


def test_match_skill_uses_confidence_as_tie_breaker():
    skills = [
        SkillDef(id="low", name="Low", description="", triggers=["review"], confidence=0.2),
        SkillDef(id="high", name="High", description="", triggers=["review"], confidence=0.9),
    ]

    assert match_skill("review this", skills) == "high"
```

- [ ] **Step 2: Run matcher tests**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_matcher.py -q
```

Expected: FAIL if matcher does not yet filter archived or rank confidence.

- [ ] **Step 3: Update matcher scoring**

Modify `src/SmallShrimp/core/definitions/skill_matcher.py`:

```python
"""Regex-based skill matching — pre-filter before LLM call."""

from __future__ import annotations

from typing import Optional, Sequence

from .skill_def import SkillDef


def match_skill(
    message_text: str,
    skills: Sequence[SkillDef],
) -> Optional[str]:
    """Pick the best-matching active skill by trigger keyword overlap."""
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
            if trigger and trigger.lower() in text_lower:
                hits += 1
        if hits == 0:
            continue
        skill_id = skill.id or skill.name
        confidence = float(skill.confidence or 0.0)
        candidates.append((hits, confidence, len(triggers), skill_id))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    return candidates[0][3]
```

- [ ] **Step 4: Run matcher tests**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_matcher.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/SmallShrimp/core/definitions/skill_matcher.py tests/test_skill_matcher.py
git commit -m "feat: rank matched skills with metadata"
```

## Task 7: Expose Versioned Skills Through Tool and Commands

**Files:**
- Modify: `src/SmallShrimp/tools/skill_tool.py`
- Modify: `src/SmallShrimp/core/commands/handlers.py`
- Modify: `tests/test_skill_tool.py`
- Modify: `tests/test_commands.py`

- [ ] **Step 1: Add failing tool test**

Append to `tests/test_skill_tool.py`:

```python

def test_create_skill_tool_description_includes_versioned_metadata():
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir)
        skill_dir = skills_dir / "coding.code-review"
        version_dir = skill_dir / "versions" / "1.0.0"
        version_dir.mkdir(parents=True)
        (version_dir / "SKILL.md").write_text("# Code Review", encoding="utf-8")
        (skill_dir / "skill.yaml").write_text(
            """id: coding.code-review
name: Code Review
description: Review code.
scene: coding
status: active
created_by: agent
version: 1.0.0
confidence: 0.8
risk_level: medium
triggers:
  - review
""",
            encoding="utf-8",
        )

        loader = SkillLoader(skills_dir)
        tool = create_skill_tool(loader)

        assert 'name="Code Review"' in tool.description
        assert 'version="1.0.0"' in tool.description
        assert 'status="active"' in tool.description
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_tool.py -q
```

Expected: FAIL because version/status are not in description yet.

- [ ] **Step 3: Update `skill_tool.py`**

Modify `src/SmallShrimp/tools/skill_tool.py`:

```python
"""Skill 工具。"""

from ..core.definitions.skill_loader import SkillLoader
from ..tools.decorators import tool


def create_skill_tool(skill_loader: SkillLoader):
    """工厂函数：创建 skill 工具。"""
    skills = skill_loader.discover_skills()
    skills_xml = "<skills>\n"
    for skill in skills:
        version = skill.version or "legacy"
        status = skill.status or "active"
        skills_xml += (
            f'  <skill name="{skill.name}" id="{skill.id}" '
            f'version="{version}" status="{status}">{skill.description}</skill>\n'
        )
    skills_xml += "</skills>"

    @tool(description=f"Load a skill to get its instructions. {skills_xml}")
    async def skill(skill_name: str) -> str:
        """根据名称加载并返回技能内容。"""
        try:
            skill_def = skill_loader.load(skill_name)
            return skill_def.content
        except FileNotFoundError:
            return f"Skill '{skill_name}' not found. Available skills: {skill_loader.list_skills()}"
        except Exception as e:
            return f"Error loading skill '{skill_name}': {e}"

    return skill
```

- [ ] **Step 4: Add command behavior tests**

In `tests/test_commands.py`, add focused tests for command output if command test fixtures already exist. If no reusable command fixture exists, add a direct async call test using `cmd_skill` and a temporary current working directory.

Required assertions:

```python
assert "用法: /skill <list|show|versions|rollback>" in await cmd_skill(context, [])
assert "coding.code-review" in await cmd_skill(context, ["list"])
assert "1.0.0" in await cmd_skill(context, ["versions", "coding.code-review"])
```

- [ ] **Step 5: Update `/skill` command**

Modify only the `cmd_skill` function and its import in `src/SmallShrimp/core/commands/handlers.py`:

```python
from ..definitions.skill_loader import SkillLoader
```

Replace `cmd_skill` with:

```python
@register_command(name="skill", description="管理和加载技能内容", usage="/skill <list|show|versions|rollback>")
async def cmd_skill(context: CommandContext, args: list[str]) -> str:
    """加载和管理技能命令。"""
    loader = SkillLoader()
    if not args:
        return "用法: /skill <list|show|versions|rollback> [name] [version]"

    subcmd = args[0].lower()
    if subcmd == "list":
        skills = loader.discover_skills()
        if not skills:
            return "暂无可用技能"
        lines = ["可用技能:"]
        for skill in skills:
            version = skill.version or "legacy"
            status = skill.status or "active"
            lines.append(f"  • `{skill.id or skill.name}` [{status}] v{version} - {skill.description}")
        return "\n".join(lines)

    if subcmd == "show":
        if len(args) < 2:
            return "用法: /skill show <name>"
        skill_def = loader.load(args[1])
        version = skill_def.version or "legacy"
        return f"已加载技能 [{skill_def.id or args[1]}] v{version}:\n\n{skill_def.content[:500]}..."

    if subcmd == "versions":
        if len(args) < 2:
            return "用法: /skill versions <name>"
        versions = loader.list_versions(args[1])
        if not versions:
            return f"技能 [{args[1]}] 没有版本记录"
        return "\n".join([f"技能 [{args[1]}] 版本:"] + [f"  • {version}" for version in versions])

    if subcmd == "rollback":
        if len(args) < 3:
            return "用法: /skill rollback <name> <version>"
        skill_def = loader.rollback(args[1], args[2], reason="Manual rollback from /skill command")
        return f"✓ 已回滚技能 `{skill_def.id or args[1]}` 到 v{skill_def.version}"

    try:
        skill_def = loader.load(args[0])
        return f"已加载技能 [{args[0]}]:\n\n{skill_def.content[:200]}..."
    except Exception as e:
        return f"技能 [{args[0]}] 不存在: {e}"
```

- [ ] **Step 6: Run tests**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_tool.py tests/test_commands.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/SmallShrimp/tools/skill_tool.py src/SmallShrimp/core/commands/handlers.py tests/test_skill_tool.py tests/test_commands.py
git commit -m "feat: expose versioned skills"
```

## Task 8: Final Verification

**Files:**
- No new files unless verification reveals issues.

- [ ] **Step 1: Run focused skill suite**

Run:

```powershell
conda run -n smallshrimp pytest tests/test_skill_def.py tests/test_skill_metadata.py tests/test_skill_usage.py tests/test_skill_loader.py tests/test_skill_matcher.py tests/test_skill_tool.py tests/test_commands.py -q
```

Expected: PASS.

- [ ] **Step 2: Compile package**

Run:

```powershell
conda run -n smallshrimp python -m compileall -q src\SmallShrimp
```

Expected: exit code 0.

- [ ] **Step 3: Check status**

Run:

```powershell
git status --short
```

Expected: only intentional changes for this plan remain, or no changes after commits.

- [ ] **Step 4: Commit verification fixes if needed**

If any fix was required:

```powershell
git add <changed-files>
git commit -m "fix: stabilize versioned skill model"
```

## Deferred Work

These items belong to later plans and should not be implemented in this phase:

1. Task-to-Skill draft generation after task completion.
2. Skill update proposals from task reflection.
3. Curator merge/deprecate/archive automation.
4. Scene-agent private skill overlays.
5. UI/desktop skill management screens.
6. Remote skill sharing or marketplace behavior.

## Self-Review Checklist

- Spec coverage: This plan implements Phase 1 from `docs/superpowers/specs/2026-07-07-skill-evolution-design.md`.
- Scope boundary: This plan does not implement task-to-skill generation, curator, or scene-agent overlays.
- Backward compatibility: Existing `workspace/skills/<name>/SKILL.md` skills continue to load without requiring `skill.yaml`.
- Standards compatibility: A `SKILL.md` with only `name` and `description` frontmatter is valid.
- Safety: Version history is immutable; rollback only updates the active `version`.
- Tests: All new behavior has focused pytest coverage using temporary directories.
