from __future__ import annotations
"""Cron 定时任务测试。"""
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock

from src.SmallShrimp.core.cron_loader import CronDef, CronLoader, find_due_jobs
from src.SmallShrimp.core.events import CronEventSource


def test_cron_def_from_file():
    """从 CRON.md 加载 CronDef。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cron_dir = Path(tmpdir) / "morning-report"
        cron_dir.mkdir()
        (cron_dir / "CRON.md").write_text("""---
name: Morning Report
description: Send daily report
agent: pickle
schedule: "0 9 * * *"
---
Send a morning report with today's schedule.
""")
        cron_def = CronDef.from_file(cron_dir / "CRON.md")
        assert cron_def is not None
        assert cron_def.name == "Morning Report"
        assert cron_def.schedule == "0 9 * * *"
        assert cron_def.agent == "pickle"
        assert "morning report" in cron_def.prompt.lower()
        assert not cron_def.one_off


def test_cron_def_one_off():
    """一次性任务标记为 one_off。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cron_dir = Path(tmpdir) / "once-task"
        cron_dir.mkdir()
        (cron_dir / "CRON.md").write_text("""---
name: Once
schedule: "0 10 * * *"
one_off: true
---
Do this once.
""")
        cron_def = CronDef.from_file(cron_dir / "CRON.md")
        assert cron_def is not None
        assert cron_def.one_off


def test_cron_loader_discover():
    """CronLoader 扫描目录发现任务。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        crons_dir = Path(tmpdir) / "crons"
        crons_dir.mkdir()

        (crons_dir / "job-a").mkdir()
        (crons_dir / "job-a" / "CRON.md").write_text("""---
name: Job A
schedule: "*/30 * * * *"
---
Task A
""")

        (crons_dir / "job-b").mkdir()
        (crons_dir / "job-b" / "CRON.md").write_text("""---
name: Job B
schedule: "0 * * * *"
---
Task B
""")

        loader = CronLoader(crons_dir)
        jobs = loader.discover_crons()
        assert len(jobs) == 2


def test_find_due_jobs():
    """find_due_jobs 匹配当前分钟。"""
    from unittest.mock import patch

    now = datetime(2024, 1, 1, 9, 0, 0)

    jobs = [
        CronDef(id="a", name="A", description="", agent="p", schedule="0 9 * * *", prompt="A"),
        CronDef(id="b", name="B", description="", agent="p", schedule="0 10 * * *", prompt="B"),
    ]

    due = find_due_jobs(jobs, now)
    assert len(due) == 1
    assert due[0].id == "a"


def test_cron_event_source():
    """CronEventSource 序列化。"""
    source = CronEventSource(cron_id="morning-report")
    assert str(source) == "cron:morning-report"
    assert source.is_cron
    assert not source.is_platform
    assert not source.is_agent


def test_cron_event_source_from_string():
    """从字符串反序列化。"""
    source = CronEventSource.from_string("cron:morning-report")
    assert source.cron_id == "morning-report"


if __name__ == "__main__":
    test_cron_def_from_file()
    test_cron_def_one_off()
    test_cron_loader_discover()
    test_find_due_jobs()
    test_cron_event_source()
    test_cron_event_source_from_string()
    print("\nAll test_cron tests passed!")
