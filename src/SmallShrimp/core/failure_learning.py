"""Failure-pattern learner — turns recurring tool errors into memory notes.

Watches every turn for failed tool calls, fingerprints the failure
(tool_name + normalised error), counts across turns, and writes an
agent_note when the same fingerprint crosses a threshold.

Design:
  - Best-effort, never raises into the agent loop.
  - One count per turn (not per retry within a turn).
  - Normalises error strings (strip timestamps, IDs, line numbers).
  - Persists counters to disk so they survive restarts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_FAILURE_THRESHOLD = 3
_ERROR_FINGERPRINT_CHARS = 200

# Strip variable tokens from errors before fingerprinting
_NORMALISE_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\S*"), "<TS>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<HEX>"),
    (re.compile(r"\b[0-9a-fA-F]{8,}\b"), "<HEX>"),
    (re.compile(r"\bline \d+\b"), "line <N>"),
    (re.compile(r"\b\d+\b"), "<N>"),
]


# ── Fingerprint ─────────────────────────────────────────────

def fingerprint_error(tool_name: str, error: str | None) -> str:
    """Stable short fingerprint for (tool_name, error)."""
    raw = (error or "").strip()[:_ERROR_FINGERPRINT_CHARS]
    for pattern, replacement in _NORMALISE_RES:
        raw = pattern.sub(replacement, raw)
    return hashlib.sha1(f"{tool_name}::{raw}".encode()).hexdigest()[:12]


# ── Record ──────────────────────────────────────────────────

@dataclass
class FailureRecord:
    tool_name: str
    error_preview: str
    count: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    note_written: bool = False


# ── Learner ─────────────────────────────────────────────────

class FailureLearner:

    def __init__(
        self,
        state_path: str | None = None,
        threshold: int = DEFAULT_FAILURE_THRESHOLD,
        on_note: "callable | None" = None,
    ) -> None:
        self.threshold = threshold
        self._state_path = state_path
        self._on_note = on_note  # callback(fingerprint, record) when threshold crossed
        self._records: dict[str, FailureRecord] = {}
        self._load()

    # ── observe ─────────────────────────────────────────────

    def observe_turn(self, failures: list[dict[str, Any]]) -> list[str]:
        """Observe one turn's failures. Returns list of new agent_notes.

        failures: [{"tool_name": str, "error": str}, ...]
        Deduplicates within a turn: same fingerprint counts as 1.
        """
        notes: list[str] = []
        seen: set[str] = set()

        for f in failures:
            fp = fingerprint_error(f["tool_name"], f.get("error"))
            if fp in seen:
                continue
            seen.add(fp)
            note = self._bump(fp, f["tool_name"], f.get("error", ""))
            if note:
                notes.append(note)

        self._save()
        return notes

    def _bump(self, fp: str, tool_name: str, error: str) -> str | None:
        now = datetime.now(timezone.utc).isoformat()
        if fp not in self._records:
            self._records[fp] = FailureRecord(
                tool_name=tool_name,
                error_preview=error[:100],
                count=1,
                first_seen_at=now,
                last_seen_at=now,
            )
            return None

        rec = self._records[fp]
        rec.count += 1
        rec.last_seen_at = now

        if rec.count >= self.threshold and not rec.note_written:
            rec.note_written = True
            note = (
                f"[Failure Pattern] {tool_name} 已失败 {rec.count} 次: "
                f"{rec.error_preview[:80]}。请避免重复相同调用，考虑替代方案。"
            )
            if self._on_note:
                try:
                    self._on_note(fp, rec)
                except Exception:
                    pass
            return note

        return None

    # ── persist ─────────────────────────────────────────────

    def _load(self) -> None:
        if not self._state_path or not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            for fp, d in data.items():
                self._records[fp] = FailureRecord(**d)
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
                    "tool_name": rec.tool_name,
                    "error_preview": rec.error_preview,
                    "count": rec.count,
                    "first_seen_at": rec.first_seen_at,
                    "last_seen_at": rec.last_seen_at,
                    "note_written": rec.note_written,
                }
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
