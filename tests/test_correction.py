from __future__ import annotations
"""Correction detection 测试。"""
from src.SmallShrimp.core.correction import (
    detect_correction,
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


def test_render_hint():
    signal = CorrectionSignal(
        confidence=CorrectionConfidence.HIGH,
        phrase="不对",
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
    test_render_hint()
    print("All correction detection tests passed!")
