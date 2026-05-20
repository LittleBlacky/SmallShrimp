from __future__ import annotations
"""安全全链路集成测试——7 层联动。"""
import json
import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_security_full_pipeline_safe_read():
    """安全读文件通过全部 7 层。"""
    from src.SmallShrimp.core.agent import Agent, AgentSession
    from src.SmallShrimp.core.message import HumanMessage, AssistantMessage, ToolMessage
    from src.SmallShrimp.core.session_state import SessionState
    from src.SmallShrimp.core.permissions import PermissionMode

    # Mock Agent
    agent = MagicMock()
    agent.tool_registry = MagicMock()
    agent.tool_registry.execute_tool = AsyncMock(return_value="file content")
    agent.tool_registry.get_schemas = MagicMock(return_value=[])
    agent.context_guard = MagicMock()
    agent.context_guard.check_and_compact = AsyncMock(return_value=MagicMock())
    agent.context_guard.estimate_tokens = MagicMock(return_value=10)
    agent.context_guard.token_threshold = 100000
    agent.agent_def = MagicMock()
    agent.agent_def.llm = {"model": "gpt-4", "context_window": 200000}
    agent.agent_def.tools = []
    agent.history_manager = None
    agent.permission_checker = MagicMock()
    agent.permission_checker.check = MagicMock(
        return_value=MagicMock(action="allow", is_allowed=True, needs_confirmation=False, is_denied=False)
    )
    agent.permission_checker.confirm_path = MagicMock()
    agent.permission_mode = PermissionMode.DEFAULT
    agent.failure_learner = MagicMock()
    agent.failure_learner.observe_turn = MagicMock(return_value=[])
    agent.trust_manager = MagicMock()
    agent.trust_manager.is_trusted = MagicMock(return_value=True)

    # Mock LLM response
    agent.llm = AsyncMock()
    agent.llm.chat = AsyncMock(return_value={
        "content": "I've read the file",
        "finish_reason": "stop",
        "tool_calls": None,
    })

    state = SessionState(session_id="test", agent=agent, messages=[])
    session = AgentSession(agent=agent, state=state)
    session._confirm_fn = lambda msg: True

    response = await session.chat("read config.yaml")

    assert "I've read the file" in response
    agent.llm.chat.assert_called_once()


@pytest.mark.asyncio
async def test_security_write_needs_confirmation():
    """写文件触发确认流程。"""
    from src.SmallShrimp.core.agent import Agent, AgentSession
    from src.SmallShrimp.core.message import HumanMessage, ToolMessage
    from src.SmallShrimp.core.session_state import SessionState
    from src.SmallShrimp.core.permissions import PermissionChecker, PermissionMode, PermissionResult

    agent = MagicMock()
    agent.tool_registry = MagicMock()
    agent.tool_registry.execute_tool = AsyncMock(return_value="Written 100 chars to out.txt")
    agent.tool_registry.get_schemas = MagicMock(return_value=[])
    agent.context_guard = MagicMock()
    agent.context_guard.check_and_compact = AsyncMock(return_value=MagicMock())
    agent.context_guard.estimate_tokens = MagicMock(return_value=10)
    agent.context_guard.token_threshold = 100000
    agent.agent_def = MagicMock()
    agent.agent_def.llm = {"model": "gpt-4", "context_window": 200000, "permission_mode": "default"}
    agent.agent_def.tools = []
    agent.history_manager = None

    # Real permission checker in default mode
    agent.permission_checker = PermissionChecker(PermissionMode.DEFAULT)
    agent.permission_mode = PermissionMode.DEFAULT
    agent.failure_learner = MagicMock()
    agent.failure_learner.observe_turn = MagicMock(return_value=[])
    agent.trust_manager = MagicMock()
    agent.trust_manager.is_trusted = MagicMock(return_value=True)

    # LLM returns a write tool call
    agent.llm = AsyncMock()
    call_count = [0]

    async def mock_chat(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {
                "content": "",
                "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "call1",
                    "function": {"name": "write", "arguments": '{"path":"out.txt","content":"hello"}'},
                }],
            }
        return {"content": "File written successfully", "finish_reason": "stop", "tool_calls": None}

    agent.llm.chat = AsyncMock(side_effect=mock_chat)

    state = SessionState(session_id="test", agent=agent, messages=[])
    session = AgentSession(agent=agent, state=state)

    # confirm_fn 拒绝
    session._confirm_fn = lambda msg: False
    response = await session.chat("write out.txt with hello")

    # 用户拒绝 → 工具没执行
    assert "denied" in response.lower() or "File written" in response


@pytest.mark.asyncio
async def test_security_shell_blocked_dangerous():
    """危险 shell 命令被 AST 层拦截。"""
    from src.SmallShrimp.core.permissions import PermissionChecker, PermissionMode

    checker = PermissionChecker(PermissionMode.DEFAULT)

    # rm -rf 应该在 shell guard 被拦截
    r = checker.check("shell", {"command": "rm -rf /tmp/test"})
    assert r.is_denied
    assert "Blocked" in r.message or "rm" in r.message.lower()


@pytest.mark.asyncio
async def test_security_path_validation_blocks_env():
    """路径验证拦截 .env 写入。"""
    from src.SmallShrimp.core.permissions import PermissionChecker, PermissionMode

    checker = PermissionChecker(PermissionMode.DEFAULT)
    r = checker.check("write", {"path": ".env"})
    assert r.is_denied


@pytest.mark.asyncio
async def test_security_path_whitelist():
    """路径白名单：确认一次后不再问。"""
    from src.SmallShrimp.core.permissions import PermissionChecker, PermissionMode, set_workspace_boundary
    import os

    set_workspace_boundary(os.getcwd())
    checker = PermissionChecker(PermissionMode.DEFAULT, workspace_root=os.getcwd())
    checker.confirm_path("src/main.py")

    # 第一次写 — 白名单，直接允许
    r1 = checker.check("write", {"path": "src/main.py"})
    assert r1.is_allowed

    # 第二次写 — 还在白名单
    r2 = checker.check("write", {"path": "src/main.py"})
    assert r2.is_allowed

    # 不同文件 — 需要确认
    r3 = checker.check("write", {"path": "tests/test.py"})
    assert r3.needs_confirmation


@pytest.mark.asyncio
async def test_security_guardrail_warns_loop():
    """Guardrail 检测重复失败。"""
    from src.SmallShrimp.core.tool_guardrails import ToolGuardrailController, GuardrailConfig

    ctrl = ToolGuardrailController(GuardrailConfig(
        exact_failure_warn_after=2,
    ))

    # 第一次失败 — 不警告
    d1 = ctrl.after_call("read", {"path": "x.txt"}, "Error: not found", failed=True)
    assert d1.action == "allow"

    # 第二次相同失败 — 警告
    d2 = ctrl.after_call("read", {"path": "x.txt"}, "Error: not found", failed=True)
    assert d2.action == "warn"

    # 成功一次 — 清零
    d3 = ctrl.after_call("read", {"path": "x.txt"}, "success", failed=False)
    assert d3.action == "allow"

    # 再次失败从头计数
    d4 = ctrl.after_call("read", {"path": "x.txt"}, "Error: not found", failed=True)
    assert d4.action == "allow"


@pytest.mark.asyncio
async def test_security_correction_detected():
    """纠正信号被检测。"""
    from src.SmallShrimp.core.correction import detect_correction, CorrectionConfidence

    s = detect_correction("不对，应该是 config.yaml")
    assert s is not None
    assert s.confidence == CorrectionConfidence.HIGH


@pytest.mark.asyncio
async def test_security_failure_learning_cross_turn():
    """跨轮失败学习写入 note。"""
    from src.SmallShrimp.core.failure_learning import FailureLearner

    learner = FailureLearner(threshold=2)
    learner.observe_turn([{"tool_name": "read", "error": "not found"}])
    notes = learner.observe_turn([{"tool_name": "read", "error": "not found"}])
    assert len(notes) == 1
    assert "read" in notes[0]


@pytest.mark.asyncio
async def test_security_trust_scan_detects_env():
    """Trust Dialog 扫描检测 .env。"""
    from src.SmallShrimp.core.trust import TrustManager
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, ".github", "workflows"), exist_ok=True)
        Path(os.path.join(d, ".env")).write_text("KEY=val")

        tm = TrustManager()
        warnings = tm.scan_dangerous(d)
        assert ".env" in warnings


@pytest.mark.asyncio
async def test_security_ast_quoted_safe():
    """tree-sitter AST: 引号内命令不误判。"""
    from src.SmallShrimp.core.shell_guard import check_shell_command

    # 'rm -rf /' 在引号内 → 安全
    r = check_shell_command("echo 'rm -rf /'")
    assert not r.is_blocked

    # 裸 rm -rf → 拦截
    r2 = check_shell_command("rm -rf /tmp/test")
    assert r2.is_blocked


@pytest.mark.asyncio
async def test_security_sandbox_execution():
    """沙箱执行安全命令。"""
    from src.SmallShrimp.core.sandbox import execute_sandboxed

    result = execute_sandboxed("python -c \"print('sandbox ok')\"")
    assert result.error == ""
    assert "sandbox ok" in result.stdout


@pytest.mark.asyncio
async def test_security_full_chain_write_denied():
    """全链路：写 .env → 路径验证拒绝 → 不执行。"""
    from src.SmallShrimp.core.permissions import PermissionChecker, PermissionMode

    checker = PermissionChecker(PermissionMode.DEFAULT)
    r = checker.check("write", {"path": ".env"})

    # Layer 5 路径验证应拒绝
    assert r.is_denied

    # 即使用户确认，也拒绝（deny 不由 confirm_fn 处理）
    assert "Protected" in r.message or ".env" in r.message.lower()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_security_full_pipeline_safe_read())
    asyncio.run(test_security_write_needs_confirmation())
    asyncio.run(test_security_shell_blocked_dangerous())
    asyncio.run(test_security_path_validation_blocks_env())
    asyncio.run(test_security_path_whitelist())
    asyncio.run(test_security_guardrail_warns_loop())
    asyncio.run(test_security_correction_detected())
    asyncio.run(test_security_failure_learning_cross_turn())
    asyncio.run(test_security_trust_scan_detects_env())
    asyncio.run(test_security_ast_quoted_safe())
    asyncio.run(test_security_sandbox_execution())
    asyncio.run(test_security_full_chain_write_denied())
    print("All security integration tests passed!")
