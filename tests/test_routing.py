from __future__ import annotations
"""多 Agent 路由测试。"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from src.SmallShrimp.core.routing import Binding, RoutingTable


def test_binding_exact_match_tier():
    """精确匹配 tier=0。"""
    b = Binding(agent="pickle", value="platform-telegram:12345")
    assert b.tier == 0
    assert b.pattern.match("platform-telegram:12345")
    assert not b.pattern.match("platform-telegram:99999")


def test_binding_regex_tier():
    """正则匹配 tier=1。"""
    b = Binding(agent="pickle", value=r"platform-telegram:\d+")
    assert b.tier == 1
    assert b.pattern.match("platform-telegram:12345")
    assert not b.pattern.match("platform-discord:abc")


def test_binding_wildcard_tier():
    """通配符 tier=2。"""
    b = Binding(agent="pickle", value="platform-telegram:.*")
    assert b.tier == 2
    assert b.pattern.match("platform-telegram:12345")
    assert b.pattern.match("platform-telegram:anything")


def test_routing_table_resolve_exact_first():
    """精确匹配优先于通配符。"""
    context = MagicMock()
    context.config.data = {
        "routing": {
            "bindings": [
                {"agent": "wildcard_agent", "value": "platform-telegram:.*"},
                {"agent": "specific_agent", "value": "platform-telegram:12345"},
            ]
        }
    }
    context.config.default_agent = "pickle"

    table = RoutingTable(context)

    # Exact match should win over wildcard (lower tier = more specific)
    result = table.resolve("platform-telegram:12345")
    assert result == "specific_agent"

    # Unmatched falls back to wildcard
    result = table.resolve("platform-telegram:99999")
    assert result == "wildcard_agent"


def test_routing_table_resolve_default():
    """无匹配时回退到 default_agent。"""
    context = MagicMock()
    context.config.data = {"routing": {"bindings": []}}
    context.config.default_agent = "pickle"

    table = RoutingTable(context)
    result = table.resolve("platform-unknown:abc")
    assert result == "pickle"


def test_routing_table_persist_binding():
    """persist_binding 将路由规则写入 runtime 配置。"""
    context = MagicMock()
    context.config.data = {"routing": {"bindings": []}}
    context.config.set_runtime = MagicMock()

    table = RoutingTable(context)
    table.persist_binding("platform-discord:.*", "discord_bot")

    context.config.set_runtime.assert_called_once()
    args = context.config.set_runtime.call_args[0]
    assert args[0] == "routing.bindings"


def test_routing_table_get_bindings():
    """get_bindings 返回已加载的绑定。"""
    context = MagicMock()
    context.config.data = {
        "routing": {
            "bindings": [
                {"agent": "pickle", "value": "platform-cli:.*"},
            ]
        }
    }
    context.config.default_agent = "pickle"

    table = RoutingTable(context)
    bindings = table.get_bindings()
    assert len(bindings) == 1
    assert bindings[0].agent == "pickle"


if __name__ == "__main__":
    test_binding_exact_match_tier()
    test_binding_regex_tier()
    test_binding_wildcard_tier()
    test_routing_table_resolve_exact_first()
    test_routing_table_resolve_default()
    test_routing_table_persist_binding()
    test_routing_table_get_bindings()
    print("\nAll test_routing tests passed!")
