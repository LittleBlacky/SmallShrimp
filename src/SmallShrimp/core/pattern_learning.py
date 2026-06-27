"""Pattern learner — turns operational experience into memory notes.

Replaces FailureLearner with a broader scope:
  - failure: recurring tool errors (same as before)
  - success: tools/approaches that worked well
  - preference: user habits and preferences detected from behavior
  - environment: system/env knowledge discovered during operation

Design:
  - Best-effort, never raises into the agent loop.
  - One count per turn (not per retry within a turn).
  - Normalises error strings for stable fingerprinting.
  - Persists counters to disk so they survive restarts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_SUCCESS_THRESHOLD = 2
_ERROR_FINGERPRINT_CHARS = 200

# Strip variable tokens from errors before fingerprinting
_NORMALISE_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\S*"), "<TS>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<HEX>"),
    (re.compile(r"\b[0-9a-fA-F]{8,}\b"), "<HEX>"),
    (re.compile(r"\bline \d+\b"), "line <N>"),
    (re.compile(r"\b\d+\b"), "<N>"),
]


class PatternType(str, Enum):
    FAILURE = "failure"
    SUCCESS = "success"
    PREFERENCE = "preference"
    ENVIRONMENT = "environment"


# ── Fingerprint ─────────────────────────────────────────────

def fingerprint_error(tool_name: str, error: str | None) -> str:
    """Stable short fingerprint for (tool_name, error)."""
    raw = (error or "").strip()[:_ERROR_FINGERPRINT_CHARS]
    for pattern, replacement in _NORMALISE_RES:
        raw = pattern.sub(replacement, raw)
    return hashlib.sha1(f"{tool_name}::{raw}".encode()).hexdigest()[:12]


def fingerprint_pattern(pattern_type: str, key: str) -> str:
    """Stable fingerprint for any pattern type."""
    return hashlib.sha1(f"{pattern_type}::{key}".encode()).hexdigest()[:12]


# ── Record ──────────────────────────────────────────────────

@dataclass
class PatternRecord:
    pattern_type: str          # PatternType value
    tool_name: str = ""        # relevant tool (for failure/success)
    description: str = ""      # human-readable description
    count: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    note_written: bool = False


# ── Learner ─────────────────────────────────────────────────

class PatternLearner:
    """Learns from operational experience across 4 dimensions."""

    def __init__(
        self,
        state_path: str | None = None,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        success_threshold: int = DEFAULT_SUCCESS_THRESHOLD,
        on_note: "callable | None" = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self._state_path = state_path
        self._on_note = on_note
        self._records: dict[str, PatternRecord] = {}
        self._load()

    # ── Observe turn ─────────────────────────────────────

    def observe_turn(
        self,
        failures: list[dict[str, Any]] | None = None,
        successes: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """Observe one turn's outcomes. Returns list of new notes.

        failures: [{"tool_name": str, "error": str}, ...]
        successes: [{"tool_name": str, "detail": str}, ...]
        """
        notes: list[str] = []
        seen: set[str] = set()

        # Track failures
        for f in (failures or []):
            fp = fingerprint_error(f["tool_name"], f.get("error"))
            if fp in seen:
                continue
            seen.add(fp)
            note = self._bump(
                fp, PatternType.FAILURE,
                tool_name=f["tool_name"],
                description=f.get("error", "")[:100],
            )
            if note:
                notes.append(note)

        # Track successes
        for s in (successes or []):
            fp = fingerprint_pattern("success", f"{s['tool_name']}::{s.get('detail', '')[:80]}")
            if fp in seen:
                continue
            seen.add(fp)
            note = self._bump(
                fp, PatternType.SUCCESS,
                tool_name=s["tool_name"],
                description=s.get("detail", "")[:100],
            )
            if note:
                notes.append(note)

        self._save()
        return notes

    # ── Direct observation (for preference/environment) ──

    def observe_pattern(
        self,
        pattern_type: PatternType,
        key: str,
        description: str,
    ) -> str | None:
        """Directly observe a preference or environment pattern.

        Returns a note if threshold crossed, None otherwise.
        """
        fp = fingerprint_pattern(pattern_type.value, key)
        note = self._bump(fp, pattern_type, description=description)
        self._save()
        return note

    def _bump(
        self,
        fp: str,
        pattern_type: PatternType,
        tool_name: str = "",
        description: str = "",
    ) -> str | None:
        now = datetime.now(timezone.utc).isoformat()

        if fp not in self._records:
            self._records[fp] = PatternRecord(
                pattern_type=pattern_type.value,
                tool_name=tool_name,
                description=description,
                count=1,
                first_seen_at=now,
                last_seen_at=now,
            )
            # Check if threshold is already met on first observation
            threshold = {
                PatternType.FAILURE: self.failure_threshold,
                PatternType.SUCCESS: self.success_threshold,
                PatternType.PREFERENCE: 2,
                PatternType.ENVIRONMENT: 1,
            }.get(pattern_type, self.failure_threshold)
            if threshold <= 1:
                self._records[fp].note_written = True
                return self._format_note(self._records[fp])
            return None

        rec = self._records[fp]
        rec.count += 1
        rec.last_seen_at = now

        # Threshold varies by type
        threshold = {
            PatternType.FAILURE: self.failure_threshold,
            PatternType.SUCCESS: self.success_threshold,
            PatternType.PREFERENCE: 2,
            PatternType.ENVIRONMENT: 1,
        }.get(pattern_type, self.failure_threshold)

        if rec.count >= threshold and not rec.note_written:
            rec.note_written = True
            note = self._format_note(rec)
            if self._on_note:
                try:
                    self._on_note(fp, rec)
                except Exception:
                    pass
            return note

        return None

    @staticmethod
    def _format_note(rec: PatternRecord) -> str:
        """Format a pattern record into an agent-facing note."""
        prefixes = {
            PatternType.FAILURE.value: "[失败模式]",
            PatternType.SUCCESS.value: "[成功经验]",
            PatternType.PREFERENCE.value: "[用户偏好]",
            PatternType.ENVIRONMENT.value: "[环境知识]",
        }
        prefix = prefixes.get(rec.pattern_type, "[经验]")
        tool = f" ({rec.tool_name})" if rec.tool_name else ""
        return f"{prefix}{tool} {rec.description}"

    # ── Query ────────────────────────────────────────────

    def get_patterns(self, pattern_type: PatternType | None = None) -> list[PatternRecord]:
        """Get all records, optionally filtered by type."""
        if pattern_type is None:
            return list(self._records.values())
        return [r for r in self._records.values() if r.pattern_type == pattern_type.value]

    # ── Persist ──────────────────────────────────────────

    def _load(self) -> None:
        if not self._state_path or not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            for fp, d in data.items():
                self._records[fp] = PatternRecord(**d)
        except Exception:
            pass

    def _save(self) -> None:
        if not self._state_path:
            return
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            data = {}
            for fp, rec in self._records.items():
                data[fp] = {
                    "pattern_type": rec.pattern_type,
                    "tool_name": rec.tool_name,
                    "description": rec.description,
                    "count": rec.count,
                    "first_seen_at": rec.first_seen_at,
                    "last_seen_at": rec.last_seen_at,
                    "note_written": rec.note_written,
                }
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
