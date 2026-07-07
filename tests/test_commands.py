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
    from src.SmallShrimp.core.runtime.message import HumanMessage

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


def test_cmd_skill_lists_markdown_skills(tmp_path, monkeypatch):
    """测试 /skill list 展示标准 Markdown-first skills。"""
    from src.SmallShrimp.core.commands.handlers import cmd_skill

    skills_dir = tmp_path / "workspace" / "skills" / "coding-review"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        """---
name: Code Review
description: Review local code changes.
version: 1.0.0
---

# Code Review
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = asyncio.run(cmd_skill(SimpleNamespace(), ["list"]))

    assert "coding-review" in result
    assert "Code Review" in result
    assert "v1.0.0" in result


def test_cmd_skill_shows_markdown_skill(tmp_path, monkeypatch):
    """测试 /skill show 加载标准 Markdown-first skill 正文。"""
    from src.SmallShrimp.core.commands.handlers import cmd_skill

    skills_dir = tmp_path / "workspace" / "skills" / "coding-review"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        """---
name: Code Review
description: Review local code changes.
---

# Code Review

Review the current diff.
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = asyncio.run(cmd_skill(SimpleNamespace(), ["show", "coding-review"]))

    assert "coding-review" in result
    assert "Code Review" in result
    assert "Review the current diff" in result


def test_cmd_skill_create_delegates_to_agent_with_skill_creator(tmp_path, monkeypatch):
    """测试 /skill create 把创建任务委托给 agent 使用 skill-creator。"""
    from src.SmallShrimp.core.commands.base import AgentTask
    from src.SmallShrimp.core.commands.handlers import CommandContext, cmd_skill
    from src.SmallShrimp.core.runtime.message import AssistantMessage, HumanMessage

    creator_dir = tmp_path / "workspace" / "skills" / "skill-creator"
    creator_dir.mkdir(parents=True)
    (creator_dir / "SKILL.md").write_text(
        """---
name: skill-creator
description: Create and iterate standard skills from user task descriptions.
---

# Skill Creator

Use draft, test prompts, evaluation, iteration, and description optimization.
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    state = SimpleNamespace(messages=[
        HumanMessage(content="刚才我们把 /skill create 改成 AgentTask 委托，而不是命令层直接写模板。"),
        AssistantMessage(content="已完成：CLI 和 server worker 都会把 AgentTask 交给当前 session.chat 执行。"),
    ])
    context = CommandContext(session=SimpleNamespace(state=state))

    result = asyncio.run(
        cmd_skill(
            context,
            ["create", "meeting-summary", "Summarize meeting notes into decisions and todos."],
        )
    )

    skill_file = tmp_path / "workspace" / "skills" / "meeting-summary" / "SKILL.md"

    assert isinstance(result, AgentTask)
    assert "skill-creator" in result.prompt
    assert "meeting-summary" in result.prompt
    assert "Summarize meeting notes into decisions and todos." in result.prompt
    assert "workspace/skills/meeting-summary/SKILL.md" in result.prompt
    assert "Recent completed-task context" in result.prompt
    assert "AgentTask 委托" in result.prompt
    assert "session.chat" in result.prompt
    assert "Do not create a generic starter skill" in result.prompt
    assert not skill_file.exists()


def test_cmd_skill_create_refuses_existing_skill(tmp_path, monkeypatch):
    """测试 /skill create 已有 skill 时不委托覆盖。"""
    from src.SmallShrimp.core.commands.handlers import cmd_skill

    skills_dir = tmp_path / "workspace" / "skills" / "meeting-summary"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        """---
name: meeting-summary
description: Existing skill.
---

# Existing
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = asyncio.run(
        cmd_skill(
            SimpleNamespace(),
            ["create", "meeting-summary", "New description should not overwrite."],
        )
    )

    content = (skills_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "已存在" in result
    assert "Existing skill" in content
    assert "New description should not overwrite" not in content


def test_chat_loop_runs_agent_task_from_command():
    """测试 CLI 收到 AgentTask 命令结果后继续交给当前 session.chat。"""
    from src.SmallShrimp.cli.chat import ChatLoop
    from src.SmallShrimp.core.commands.base import AgentTask
    from src.SmallShrimp.core.events.events import InboundEvent, OutboundEvent, CliEventSource

    class FakeBus:
        def __init__(self):
            self.events = []

        async def publish(self, event):
            self.events.append(event)

        def ack(self, event):
            self.acked = event

    class FakeSession:
        async def chat(self, prompt):
            self.prompt = prompt
            return "created by agent"

    loop = object.__new__(ChatLoop)
    loop.context = SimpleNamespace(eventbus=FakeBus())
    loop.session = FakeSession()

    event = InboundEvent(
        session_id="sess-001",
        source=CliEventSource(),
        content="/skill create meeting-summary summarize meetings",
    )

    asyncio.run(ChatLoop._publish_command_result(loop, event, AgentTask(prompt="use skill-creator")))

    assert loop.session.prompt == "use skill-creator"
    assert len(loop.context.eventbus.events) == 1
    outbound = loop.context.eventbus.events[0]
    assert isinstance(outbound, OutboundEvent)
    assert outbound.content == "created by agent"


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
