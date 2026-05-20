from __future__ import annotations
"""Failure learning 测试。"""
import tempfile
import os
from src.SmallShrimp.core.failure_learning import FailureLearner, fingerprint_error


def test_fingerprint_same_error():
    """相同错误生成相同指纹。"""
    fp1 = fingerprint_error("read", "File not found: /path/to/file.txt")
    fp2 = fingerprint_error("read", "File not found: /path/to/file.txt")
    assert fp1 == fp2


def test_fingerprint_different_tool():
    """不同工具不同指纹。"""
    fp1 = fingerprint_error("read", "not found")
    fp2 = fingerprint_error("grep", "not found")
    assert fp1 != fp2


def test_fingerprint_normalises_numbers():
    """数字被归一化。"""
    fp1 = fingerprint_error("read", "line 42: error")
    fp2 = fingerprint_error("read", "line 99: error")
    assert fp1 == fp2


def test_observe_single_failure_no_note():
    """单次失败不产生 note。"""
    learner = FailureLearner(threshold=3)
    notes = learner.observe_turn([{"tool_name": "read", "error": "not found"}])
    assert notes == []


def test_observe_crosses_threshold():
    """跨 3 轮同一失败产生 note。"""
    learner = FailureLearner(threshold=3)
    learner.observe_turn([{"tool_name": "read", "error": "not found"}])
    learner.observe_turn([{"tool_name": "read", "error": "not found"}])
    notes = learner.observe_turn([{"tool_name": "read", "error": "not found"}])
    assert len(notes) == 1
    assert "read" in notes[0]
    assert "3 次" in notes[0]


def test_observe_note_only_once():
    """跨阈值后不再重复写 note。"""
    learner = FailureLearner(threshold=3)
    learner.observe_turn([{"tool_name": "grep", "error": "timeout"}])
    learner.observe_turn([{"tool_name": "grep", "error": "timeout"}])
    n1 = learner.observe_turn([{"tool_name": "grep", "error": "timeout"}])
    assert len(n1) == 1
    n2 = learner.observe_turn([{"tool_name": "grep", "error": "timeout"}])
    assert n2 == []


def test_deduplicate_within_turn():
    """同一轮内相同失败只计 1 次。"""
    learner = FailureLearner(threshold=3)
    # 单轮内 5 次相同失败
    learner.observe_turn([
        {"tool_name": "read", "error": "not found"},
        {"tool_name": "read", "error": "not found"},
        {"tool_name": "read", "error": "not found"},
    ])
    # 只计 1 次
    learner.observe_turn([{"tool_name": "read", "error": "not found"}])
    notes = learner.observe_turn([{"tool_name": "read", "error": "not found"}])
    assert len(notes) == 1


def test_persist_and_load():
    """计数器持久化。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "failures.json")
        learner = FailureLearner(state_path=path, threshold=2)
        learner.observe_turn([{"tool_name": "read", "error": "not found"}])

        # 重新加载
        learner2 = FailureLearner(state_path=path, threshold=2)
        # 再失败一次就应该触发
        notes = learner2.observe_turn([{"tool_name": "read", "error": "not found"}])
        assert len(notes) == 1


if __name__ == "__main__":
    test_fingerprint_same_error()
    test_fingerprint_different_tool()
    test_fingerprint_normalises_numbers()
    test_observe_single_failure_no_note()
    test_observe_crosses_threshold()
    test_observe_note_only_once()
    test_deduplicate_within_turn()
    test_persist_and_load()
    print("All failure learning tests passed!")
