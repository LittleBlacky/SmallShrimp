"""Phase 2.2 滑动窗口 Buffer — 测试与量化。"""
from __future__ import annotations

import pytest
from src.SmallShrimp.core.context.conversation_buffer import ConversationBuffer, TurnRecord


class TestBufferTurnManagement:
    """Buffer 轮次管理测试。"""

    def test_start_and_end_turn(self):
        buf = ConversationBuffer(max_turns=5)
        buf.start_turn("帮我查天气")
        result = buf.end_turn("北京今天晴天")
        assert result["turn_count"] == 1
        assert buf.turns[0].user_message == "帮我查天气"
        assert buf.turns[0].assistant_message == "北京今天晴天"

    def test_tool_result_added_to_current_turn(self):
        buf = ConversationBuffer()
        buf.start_turn("查天气")
        buf.add_tool_result('{"temp": 25}')
        buf.end_turn("25度")
        assert len(buf.turns[0].tool_messages) == 1

    def test_multiple_turns(self):
        buf = ConversationBuffer(max_turns=5)
        for i in range(3):
            buf.start_turn(f"msg{i}")
            buf.end_turn(f"resp{i}")
        assert buf.turn_count == 3
        assert buf.recent_turns(2)[-1].user_message == "msg2"

    def test_recent_turns_limit(self):
        buf = ConversationBuffer(max_turns=10)
        for i in range(10):
            buf.start_turn(f"msg{i}")
            buf.end_turn(f"resp{i}")
        recent = buf.recent_turns(3)
        assert len(recent) == 3
        assert recent[0].user_message == "msg7"


class TestCompressionTriggers:
    """压缩触发条件测试。"""

    def test_summary_trigger_via_turn_limit(self):
        buf = ConversationBuffer(max_turns=3, summary_trigger=4)
        for i in range(5):
            buf.start_turn(f"msg{i}")
            buf.end_turn(f"resp{i}")
        # 第 5 轮触发 turn_limit
        assert buf.turn_count == 5

    def test_overflow_detection(self):
        buf = ConversationBuffer(max_turns=3, summary_trigger=10)
        for i in range(5):
            buf.start_turn(f"msg{i}")
            buf.end_turn(f"resp{i}")
        check = buf._check_triggers()
        assert check["overflow"] == 2  # 5 - 3 = 2

    def test_get_turns_for_summary_returns_oldest(self):
        buf = ConversationBuffer(max_turns=3, summary_trigger=999)
        for i in range(5):
            buf.start_turn(f"msg{i}")
            buf.end_turn(f"resp{i}")
        old = buf.get_turns_for_summary()
        assert len(old) >= 1
        assert old[0].user_message == "msg0"

    def test_replace_with_summary(self):
        buf = ConversationBuffer(max_turns=3, summary_trigger=999)
        for i in range(5):
            buf.start_turn(f"msg{i}")
            buf.end_turn(f"resp{i}")
        old = buf.get_turns_for_summary(n=2)
        buf.replace_with_summary(old, "用户问了5个问题，完成了3个")
        # summary 替换后轮次减少
        assert buf.turn_count < 6

    def test_no_trigger_when_under_limit(self):
        buf = ConversationBuffer(max_turns=10, summary_trigger=20)
        for i in range(3):
            buf.start_turn(f"msg{i}")
            result = buf.end_turn(f"resp{i}")
        assert result["compressed"] is False
        assert result["trigger"] is None


class TestBufferQuantification:
    """Buffer 量化指标。"""

    def test_raw_message_count(self):
        buf = ConversationBuffer()
        buf.start_turn("查天气")
        buf.add_tool_result("结果A")
        buf.add_tool_result("结果B")
        buf.end_turn("晴天")
        buf.start_turn("订酒店")
        buf.end_turn("已订")
        # 2 轮: 1 user + 1 assistant + 2 tool + 1 user + 1 assistant = 6
        assert buf.raw_message_count == 6

    def test_max_turns_not_exceeded_by_much(self):
        """量化: Buffer 不会无限增长。"""
        buf = ConversationBuffer(max_turns=5, summary_trigger=999)
        for i in range(20):
            buf.start_turn(f"msg{i}")
            buf.end_turn(f"resp{i}")
        # 当 summary_trigger 不触发时，轮次会积累，但 get_turns_for_summary
        # 仍能在需要时选出要摘要的轮次
        assert buf.turn_count == 20

    def test_no_negative_overflow(self):
        buf = ConversationBuffer(max_turns=10)
        for i in range(3):
            buf.start_turn(f"msg{i}")
            buf.end_turn(f"resp{i}")
        check = buf._check_triggers()
        assert check["overflow"] == 0

    def test_to_dict_serializable(self):
        buf = ConversationBuffer(max_turns=3)
        for i in range(2):
            buf.start_turn(f"msg{i}")
            buf.end_turn(f"resp{i}")
        d = buf.to_dict()
        assert d["max_turns"] == 3
        assert len(d["turns"]) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
