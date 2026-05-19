"""Cron job definition loader."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from croniter import croniter

logger = logging.getLogger(__name__)


@dataclass
class CronDef:
    """Loaded cron job definition."""

    id: str
    name: str
    description: str
    agent: str
    schedule: str
    prompt: str
    one_off: bool = False

    @classmethod
    def from_file(cls, path: Path) -> "CronDef | None":
        """Parse a CRON.md file."""
        content = path.read_text(encoding="utf-8")
        pattern = r"^---\n(.*?)---\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)
        if not match:
            return None

        try:
            frontmatter = yaml.safe_load(match.group(1))
            body = match.group(2).strip()
            schedule = frontmatter["schedule"]

            if not croniter.is_valid(schedule):
                logger.warning(f"Invalid cron expression: {schedule}")
                return None

            return cls(
                id=path.parent.name,
                name=frontmatter.get("name", ""),
                description=frontmatter.get("description", ""),
                agent=frontmatter.get("agent", "pickle"),
                schedule=schedule,
                prompt=body,
                one_off=frontmatter.get("one_off", False),
            )
        except (KeyError, yaml.YAMLError) as e:
            logger.warning(f"Invalid cron file {path}: {e}")
            return None


class CronLoader:
    """Loads cron job definitions from CRON.md files."""

    def __init__(self, crons_dir: Path) -> None:
        self.crons_dir = Path(crons_dir)
        self.crons_dir.mkdir(parents=True, exist_ok=True)

    def discover_crons(self) -> list[CronDef]:
        """Scan crons directory for valid CRON.md files."""
        results = []
        if not self.crons_dir.exists():
            return results

        for d in sorted(self.crons_dir.iterdir()):
            if not d.is_dir():
                continue
            cron_file = d / "CRON.md"
            if not cron_file.exists():
                continue
            cron_def = CronDef.from_file(cron_file)
            if cron_def:
                results.append(cron_def)

        return results


def find_due_jobs(jobs: list[CronDef], now: datetime | None = None) -> list[CronDef]:
    """Find jobs that are due to run at the current minute."""
    if not jobs:
        return []

    now = now or datetime.now()
    now_minute = now.replace(second=0, microsecond=0)

    due: list[CronDef] = []
    for job in jobs:
        try:
            if croniter.match(job.schedule, now_minute):
                due.append(job)
        except Exception:
            continue

    return due
