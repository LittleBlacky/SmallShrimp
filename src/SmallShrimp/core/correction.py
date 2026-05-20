"""User-correction detector — catches high-signal teaching moments.

Two detection layers:
  1. Keyword regex (zero-cost, immediate)
  2. Structural analysis — short message after tool results (zero-cost)
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
    source: str = "keyword"  # "keyword" | "structural"


# ── Layer 1: Keyword regex ─────────────────────────────────

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
    """Layer 1: keyword-based detection."""
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
                source="keyword",
            )
    return None


# ── Layer 2: Structural analysis ───────────────────────────

# New-request patterns: if user message looks like a fresh request, it's
# probably not a correction.
_NEW_REQUEST_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"请|帮我|帮我|你能|可以|能否",
        r"\bcan you\b|\bcould you\b|\bplease\b|\bhelp\b",
        r"^读|^查|^搜|^写|^创建|^删除|^运行|^执行",
        r"^\s*(read|find|search|write|create|delete|run|execute)\b",
    ]
]

_TOOL_RESULT_MARKERS = [
    "[Lines ", "[Content snipped", "[Old result cleared",
    "[Result too large", "[Tool Loop Warning",
    "Error:", "No files found", "No matches found",
    "Written ", "Search results",
]


def detect_correction_structural(
    user_text: str,
    prev_assistant_content: str | None = None,
) -> CorrectionSignal | None:
    """Layer 2: structural heuristic — short message after tool result."""
    body = user_text.strip()
    if not body or len(body) > 200:
        return None

    # If it looks like a new request, not a correction
    for pat in _NEW_REQUEST_PATTERNS:
        if pat.search(body):
            return None

    # Check if previous turn had tool results
    if prev_assistant_content:
        has_tool_result = any(m in prev_assistant_content for m in _TOOL_RESULT_MARKERS)
        if not has_tool_result:
            return None
    else:
        return None  # No context to correct

    return CorrectionSignal(
        confidence=CorrectionConfidence.MEDIUM,
        phrase=body[:50],
        source="structural",
    )


# ── Combined detector ─────────────────────────────────────

def detect_correction_combined(
    user_text: str,
    prev_assistant_content: str | None = None,
) -> CorrectionSignal | None:
    """Run both layers. Keyword wins if both fire."""
    kw = detect_correction(user_text)
    if kw:
        return kw
    return detect_correction_structural(user_text, prev_assistant_content)


# ── Render ────────────────────────────────────────────────

def render_correction_hint(signal: CorrectionSignal) -> str:
    """Produce a hint to prepend to the user message."""
    label = "HIGH" if signal.confidence == CorrectionConfidence.HIGH else "MEDIUM"
    return (
        f"[Correction detected (confidence={label}, source={signal.source}): "
        f"user said \"{signal.phrase}\". "
        f"This is a teaching moment — review the prior exchange carefully "
        f"and update your understanding. Consider writing a memory note.]"
    )
