"""Verifier — optional post-turn quality check via LLM-as-judge.

Single-pass verification (no repair loop). When enabled via
AGENT.md `capabilities.verifier: true`, the agent's response is
scored against a rubric. If it fails, improvement suggestions
are returned for the agent to consider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


@dataclass
class RubricDim:
    """A single scoring dimension."""
    key: str
    weight: float = 1.0
    threshold: float = 0.5  # Hard minimum for this dimension
    description: str = ""


@dataclass
class RubricDef:
    """Rubric definition — dimensions + pass threshold."""
    dims: list[RubricDim] = field(default_factory=list)
    pass_threshold: float = 0.7  # Overall weighted average needed to pass

    @staticmethod
    def default() -> "RubricDef":
        return RubricDef(
            dims=[
                RubricDim("completeness", 0.25, 0.5, "回答是否完整覆盖了用户的问题"),
                RubricDim("accuracy", 0.25, 0.5, "信息是否准确、无明显错误"),
                RubricDim("relevance", 0.20, 0.4, "回答是否与问题高度相关"),
                RubricDim("clarity", 0.15, 0.3, "表达是否清晰易懂"),
                RubricDim("depth", 0.15, 0.3, "分析是否有足够深度"),
            ],
            pass_threshold=0.7,
        )


@dataclass
class VerificationResult:
    """Result of a verification pass."""
    passed: bool = False
    overall_score: float = 0.0
    dim_scores: dict[str, float] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    raw_response: str = ""


VERIFY_PROMPT = """你是一个回复质量评审员。请根据以下评分标准对回复进行评分。

## 评分标准
{rubric}

## 用户问题
{question}

## 待评回复
{response}

## 输出格式（严格 JSON）
```json
{{
  "scores": {{
    {dim_keys}
  }},
  "suggestions": ["改进建议1", "改进建议2"],
  "passed": true/false
}}
```

每个 score 为 0.0-1.0 的浮点数。passed 为加权平均是否 >= {pass_threshold}。
只输出 JSON，无其他文字。"""


async def verify_response(
    question: str,
    response: str,
    llm_caller: Any,
    rubric: RubricDef | None = None,
) -> VerificationResult:
    """Verify a response against a rubric using LLM-as-judge.

    Args:
        question: The original user question
        response: The agent's response to verify
        llm_caller: Object with async .chat(messages) -> dict method
        rubric: Scoring rubric (defaults to standard rubric)
    """
    if rubric is None:
        rubric = RubricDef.default()

    # Build rubric text
    rubric_lines = []
    for dim in rubric.dims:
        rubric_lines.append(f"- **{dim.key}** (权重 {dim.weight}, 下限 {dim.threshold}): {dim.description}")

    dim_keys_str = ",\n    ".join(
        f'"{dim.key}": 0.0 /* {dim.description} */' for dim in rubric.dims
    )

    prompt = VERIFY_PROMPT.format(
        rubric="\n".join(rubric_lines),
        question=question[:2000],
        response=response[:3000],
        dim_keys=dim_keys_str,
        pass_threshold=rubric.pass_threshold,
    )

    try:
        llm_response = await llm_caller.chat([
            {"role": "user", "content": prompt}
        ])
        raw = llm_response.get("content", "")
    except Exception:
        # LLM call failed — skip verification
        return VerificationResult(passed=True, overall_score=1.0)

    return _parse_verification(raw, rubric)


def _parse_verification(raw: str, rubric: RubricDef) -> VerificationResult:
    """Parse LLM verification response."""
    import json
    import re

    result = VerificationResult(raw_response=raw)

    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not json_match:
        # Can't parse — assume pass
        return VerificationResult(passed=True, overall_score=1.0)

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return VerificationResult(passed=True, overall_score=1.0)

    scores = data.get("scores", {})
    if not isinstance(scores, dict):
        return VerificationResult(passed=True, overall_score=1.0)

    # Calculate weighted average
    total_weight = 0.0
    weighted_sum = 0.0
    dim_scores: dict[str, float] = {}

    for dim in rubric.dims:
        raw_score = scores.get(dim.key, 0.5)
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.5
        score = max(0.0, min(1.0, score))
        dim_scores[dim.key] = score
        weighted_sum += score * dim.weight
        total_weight += dim.weight

    overall = weighted_sum / total_weight if total_weight > 0 else 0.0

    # Check dimension thresholds
    threshold_failures = []
    for dim in rubric.dims:
        if dim_scores.get(dim.key, 0.0) < dim.threshold:
            threshold_failures.append(dim.key)

    passed = overall >= rubric.pass_threshold and not threshold_failures

    suggestions = data.get("suggestions", [])
    if not isinstance(suggestions, list):
        suggestions = []
    if threshold_failures:
        suggestions.insert(0, f"以下维度未达最低标准: {', '.join(threshold_failures)}")

    return VerificationResult(
        passed=passed,
        overall_score=overall,
        dim_scores=dim_scores,
        suggestions=suggestions,
        raw_response=raw,
    )


def render_verification_hint(result: VerificationResult) -> str:
    """Render verification result as an LLM-facing hint."""
    if result.passed:
        return ""

    lines = ["[验证未通过] 回复质量评分："]
    for dim, score in result.dim_scores.items():
        status = "✓" if score >= 0.5 else "✗"
        lines.append(f"  {status} {dim}: {score:.2f}")
    lines.append(f"  综合: {result.overall_score:.2f}")
    if result.suggestions:
        lines.append("改进建议：")
        for s in result.suggestions[:3]:
            lines.append(f"  - {s}")
    return "\n".join(lines)
