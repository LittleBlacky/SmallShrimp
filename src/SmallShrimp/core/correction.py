"""User-correction detector — catches high-signal teaching moments.

When the user says "不对" / "actually" / "I meant", this is a prime
memory-writing trigger. The detector is stateless and deterministic.

Confidence levels:
  HIGH   — explicit correction ("you're wrong", "actually", "我意思是")
  MEDIUM — softer correction ("应该是", "should be", "不是这样")
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CorrectionConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class CorrectionSignal:
    confidence: CorrectionConfidence
    phrase: str


# Ordered: high-confidence patterns checked first (first match wins).
_CORRECTION_PATTERNS: list[tuple[str, CorrectionConfidence]] = [
    # Chinese, high
    (r"不对[，,。！!\s]?", CorrectionConfidence.HIGH),
    (r"错了[，,。！!\s]?", CorrectionConfidence.HIGH),
    (r"我意思是", CorrectionConfidence.HIGH),
    (r"我(?:刚才)?说的是", CorrectionConfidence.HIGH),
    (r"不是这样", CorrectionConfidence.HIGH),
    (r"重新(?:理解|做|来)", CorrectionConfidence.HIGH),
    # English, high
    (r"\bthat'?s\s+wrong\b", CorrectionConfidence.HIGH),
    (r"\byou'?re\s+wrong\b", CorrectionConfidence.HIGH),
    (r"\bactually[,\s]", CorrectionConfidence.HIGH),
    (r"\bI\s+meant\b", CorrectionConfidence.HIGH),
    (r"\blet\s+me\s+(?:clarify|rephrase|correct)\b", CorrectionConfidence.HIGH),
    (r"\bcorrection[:\s]", CorrectionConfidence.HIGH),
    # Chinese, medium
    (r"不是[，,。！!\s]?(?:这|那|我|你)", CorrectionConfidence.MEDIUM),
    (r"应该是", CorrectionConfidence.MEDIUM),
    (r"应该用", CorrectionConfidence.MEDIUM),
    (r"不要(?:用|这样)", CorrectionConfidence.MEDIUM),
    # English, medium
    (r"\bshould\s+be\b", CorrectionConfidence.MEDIUM),
    (r"\bnot\s+(?:that|like|the)\b", CorrectionConfidence.MEDIUM),
    (r"\bno[,\s]+it'?s\b", CorrectionConfidence.MEDIUM),
]

_COMPILED: list[tuple[re.Pattern[str], CorrectionConfidence]] = [
    (re.compile(pat, re.IGNORECASE), conf) for pat, conf in _CORRECTION_PATTERNS
]


def detect_correction(text: str) -> CorrectionSignal | None:
    """Detect if text contains a user correction. Returns first match or None."""
    if not text or not isinstance(text, str):
        return None
    body = text.strip()
    if not body or len(body) > 800:
        return None
    for pattern, confidence in _COMPILED:
        match = pattern.search(body)
        if match:
            return CorrectionSignal(
                confidence=confidence,
                phrase=match.group(0).strip(),
            )
    return None


def render_correction_hint(signal: CorrectionSignal) -> str:
    """Produce a hint to prepend to the user message."""
    label = "HIGH" if signal.confidence == CorrectionConfidence.HIGH else "MEDIUM"
    return (
        f"[Correction detected (confidence={label}): "
        f"user said \"{signal.phrase}\". "
        f"This is a teaching moment — review the prior exchange carefully "
        f"and update your understanding. Consider writing a memory note.]"
    )
