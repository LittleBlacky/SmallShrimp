from __future__ import annotations
"""Correction detection 测试。"""
from src.SmallShrimp.core.correction import (
    detect_correction,
    detect_correction_structural,
    detect_correction_combined,
    CorrectionConfidence,
    render_correction_hint,
    CorrectionSignal,
)


def test_detect_chinese_high():
    s = detect_correction("不对，这个路径是错的")
    assert s is not None
    assert s.confidence == CorrectionConfidence.HIGH


def test_detect_chinese_medium():
    s = detect_correction("应该是 /src/main.py 才对")
    assert s is not None
    assert s.confidence == CorrectionConfidence.MEDIUM


def test_detect_english_high():
    s = detect_correction("actually, the file is in src/")
    assert s is not None
    assert s.confidence == CorrectionConfidence.HIGH


def test_detect_i_meant():
    s = detect_correction("I meant the config file, not the source")
    assert s is not None
    assert s.confidence == CorrectionConfidence.HIGH


def test_no_correction_normal():
    s = detect_correction("请帮我读一下 config.yaml")
    assert s is None


def test_no_correction_long_text():
    s = detect_correction("x" * 900)
    assert s is None


def test_no_correction_empty():
    assert detect_correction("") is None
    assert detect_correction("   ") is None


# ── Structural detection tests ──────────────────────────

def test_structural_short_after_tool():
    """短消息紧跟工具结果 → 结构性纠正。"""
    s = detect_correction_structural(
        "路径不对，应该是 app.py",
        prev_assistant_content="[Lines 0-50 of 100]\nline 0: import os\n..."
    )
    assert s is not None
    assert s.source == "structural"
    assert s.confidence == CorrectionConfidence.MEDIUM


def test_structural_new_request_no_correction():
    """新请求不误判。"""
    s = detect_correction_structural(
        "请帮我读一下 config.yaml",
        prev_assistant_content="[Lines 0-50 of 100]\n..."
    )
    assert s is None


def test_structural_no_prev_tool():
    """没有工具结果的上下文不触发。"""
    s = detect_correction_structural(
        "路径不对",
        prev_assistant_content="好的，我明白了。"
    )
    assert s is None


def test_structural_long_message():
    """长消息不触发结构分析。"""
    s = detect_correction_structural(
        "x" * 250,
        prev_assistant_content="[Lines 0-50 of 100]\n..."
    )
    assert s is None


def test_combined_keyword_wins():
    """关键词优先于结构分析。"""
    s = detect_correction_combined(
        "不对，应该是 app.py",
        prev_assistant_content="[Lines 0-50 of 100]\n..."
    )
    assert s is not None
    assert s.source == "keyword"
    assert s.confidence == CorrectionConfidence.HIGH


def test_combined_structural_fallback():
    """无关键词时走结构分析。"""
    s = detect_correction_combined(
        "文件是 app.py 不是 main.py",
        prev_assistant_content="[Lines 0-50 of 100]\nfile listing..."
    )
    assert s is not None
    assert s.source == "structural"


def test_render_hint():
    signal = CorrectionSignal(
        confidence=CorrectionConfidence.HIGH,
        phrase="不对",
        source="keyword",
    )
    hint = render_correction_hint(signal)
    assert "HIGH" in hint
    assert "不对" in hint
    assert "teaching moment" in hint


if __name__ == "__main__":
    test_detect_chinese_high()
    test_detect_chinese_medium()
    test_detect_english_high()
    test_detect_i_meant()
    test_no_correction_normal()
    test_no_correction_long_text()
    test_no_correction_empty()
    test_structural_short_after_tool()
    test_structural_new_request_no_correction()
    test_structural_no_prev_tool()
    test_structural_long_message()
    test_combined_keyword_wins()
    test_combined_structural_fallback()
    test_render_hint()
    print("All correction detection tests passed!")
