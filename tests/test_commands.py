from __future__ import annotations
"""命令注册表测试。"""
import asyncio
from types import SimpleNamespace

from src.SmallShrimp.core.commands.registry import CommandRegistry, register_command
from src.SmallShrimp.core.commands.base import Command


def setup_module():
    """每个测试前清空命令注册表。"""
    CommandRegistry.clear()


def teardown_module():
    """每个测试后清空命令注册表。"""
    CommandRegistry.clear()


def test_command_registry_register():
    """测试命令注册。"""
    setup_module()

    cmd = Command(
        name="test",
        description="A test command",
        usage="/test <args>",
        handler=None
    )
    CommandRegistry.register(cmd)

    assert CommandRegistry.get("test") == cmd


def test_command_registry_get():
    """测试获取命令。"""
    setup_module()

    cmd = Command(
        name="get-test",
        description="Get test",
        usage="/get-test",
        handler=None
    )
    CommandRegistry.register(cmd)

    retrieved = CommandRegistry.get("get-test")
    assert retrieved is not None
    assert retrieved.name == "get-test"

    not_found = CommandRegistry.get("nonexistent")
    assert not_found is None


def test_command_registry_list_all():
    """测试列出所有命令。"""
    setup_module()

    cmd1 = Command(name="cmd1", description="", usage="/cmd1", handler=None)
    cmd2 = Command(name="cmd2", description="", usage="/cmd2", handler=None)
    CommandRegistry.register(cmd1)
    CommandRegistry.register(cmd2)

    all_cmds = CommandRegistry.list_all()
    assert len(all_cmds) == 2


def test_command_registry_parse():
    """测试命令解析。"""
    setup_module()

    # 正常解析
    result = CommandRegistry.parse("/skill python")
    assert result is not None
    name, args = result
    assert name == "skill"
    assert args == ["python"]

    # 带多个参数
    result = CommandRegistry.parse("/test arg1 arg2 arg3")
    assert result is not None
    name, args = result
    assert name == "test"
    assert args == ["arg1", "arg2", "arg3"]

    # 无参数的命令
    result = CommandRegistry.parse("/help")
    assert result is not None
    name, args = result
    assert name == "help"
    assert args == []

    # 非命令输入
    result = CommandRegistry.parse("hello world")
    assert result is None

    # 空输入
    result = CommandRegistry.parse("")
    assert result is None


def test_register_command_decorator():
    """测试命令装饰器。"""
    setup_module()

    @register_command(name="decorated", description="Test decorated command", usage="/decorated <arg>")
    async def cmd_decorated(context, args):
        return "decorated result"

    assert hasattr(cmd_decorated, "_command_meta")
    meta = cmd_decorated._command_meta
    assert meta["name"] == "decorated"
    assert meta["description"] == "Test decorated command"
    assert meta["usage"] == "/decorated <arg>"


async def run_dispatch_test():
    """运行异步分发测试。"""
    from src.SmallShrimp.core.commands.base import Command
    from src.SmallShrimp.core.commands.registry import register_command

    # 动态注册测试命令
    @register_command(name="dispatch-test", description="Test dispatch", usage="/dispatch-test <args>")
    async def cmd_dispatch(context, args):
        return f"dispatched: {args}"

    # 分发命令
    class MockContext:
        pass

    context = MockContext()
    result = await cmd_dispatch(context, ["arg1", "arg2"])

    assert result == "dispatched: ['arg1', 'arg2']"


def test_command_registry_dispatch():
    """测试命令分发。"""
    setup_module()

    # 直接测试命令处理器
    import asyncio

    @register_command(name="dispatch-cmd", description="Test dispatch", usage="/dispatch-cmd <args>")
    async def cmd_dispatch(context, args):
        return f"dispatched: {args}"

    class MockContext:
        pass

    context = MockContext()
    result = asyncio.run(cmd_dispatch(context, ["arg1", "arg2"]))
    assert result == "dispatched: ['arg1', 'arg2']"


def test_cmd_compact_uses_context_guard_pipeline():
    """测试 /compact 走当前 ContextGuard 统一压缩入口。"""
    from src.SmallShrimp.core.commands.handlers import CommandContext, cmd_compact
    from src.SmallShrimp.core.message import HumanMessage

    class FakeGuard:
        token_threshold = 100

        def __init__(self):
            self.calls = 0

        def estimate_tokens(self, state):
            return 120 if self.calls == 0 else 40

        async def check_and_compact(self, state):
            self.calls += 1
            state.messages = state.messages[:1]
            return state

    guard = FakeGuard()
    state = SimpleNamespace(messages=[
        HumanMessage(content="first"),
        HumanMessage(content="second"),
    ])
    session = SimpleNamespace(
        state=state,
        agent=SimpleNamespace(context_guard=guard),
    )
    context = CommandContext(session=session)

    result = asyncio.run(cmd_compact(context, []))

    assert guard.calls == 1
    assert "tokens: 120 -> 40 / 100" in result
    assert "messages: 2 -> 1" in result


if __name__ == "__main__":
    setup_module()

    test_command_registry_register()
    test_command_registry_get()
    test_command_registry_list_all()
    test_command_registry_parse()
    test_register_command_decorator()
    test_command_registry_dispatch()
    test_cmd_compact_uses_context_guard_pipeline()

    print("\nAll test_commands tests passed!")
