from __future__ import annotations
"""Server Workers 测试。"""
import pytest
from src.SmallShrimp.server.delivery_worker import (
    DeliveryWorker,
    chunk_message,
    compute_backoff_ms,
    PLATFORM_LIMITS,
)


def test_chunk_message_single():
    """测试单条消息分割。"""
    content = "Short message"
    result = chunk_message(content, 4096)
    assert result == ["Short message"]


def test_chunk_message_multiple_paragraphs():
    """测试多段落消息分割。"""
    content = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
    result = chunk_message(content, 20)
    assert len(result) > 1


def test_chunk_message_long_paragraph():
    """测试超长段落硬分割。"""
    content = "x" * 100
    result = chunk_message(content, 30)
    assert len(result) >= 3


def test_compute_backoff_ms():
    """测试退避时间计算。"""
    # 无退避
    assert compute_backoff_ms(0) == 0
    # 第一次退避
    backoff1 = compute_backoff_ms(1)
    assert backoff1 >= 4000 and backoff1 <= 6000  # 5000 +/- 20%


def test_platform_limits():
    """测试平台消息限制。"""
    assert PLATFORM_LIMITS["telegram"] == 4096
    assert PLATFORM_LIMITS["discord"] == 2000
    assert PLATFORM_LIMITS["cli"] == float("inf")


def test_delivery_worker_init():
    """测试 DeliveryWorker 初始化。"""
    from src.SmallShrimp.core.eventbus import EventBus

    class MockContext:
        def __init__(self):
            self.eventbus = EventBus()
            self.channels = []

    context = MockContext()
    worker = DeliveryWorker(context)
    assert worker.context == context


if __name__ == "__main__":
    test_chunk_message_single()
    test_chunk_message_multiple_paragraphs()
    test_chunk_message_long_paragraph()
    test_compute_backoff_ms()
    test_platform_limits()
    test_delivery_worker_init()
    print("\nAll delivery worker tests passed!")