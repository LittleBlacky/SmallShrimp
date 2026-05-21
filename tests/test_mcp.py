from __future__ import annotations
"""MCP integration tests — official mcp SDK."""
import asyncio
import json
import pytest
from src.SmallShrimp.core.mcp import McpManager

_MOCK_SERVER = r'''
import asyncio, json, sys
async def main():
    while True:
        line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
        if not line: break
        try:
            msg = json.loads(line)
            rid, method = msg.get("id"), msg.get("method")
            if method == "initialize":
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"mock","version":"1.0"}}})+"\n")
            elif method == "tools/list":
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":{"tools":[{"name":"echo","description":"Echo","inputSchema":{"type":"object","properties":{"message":{"type":"string"}}}}]}})+"\n")
            elif method == "tools/call":
                args = msg.get("params",{}).get("arguments",{})
                sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":rid,"result":{"content":[{"type":"text","text":"echo:"+args.get("message","")}]}})+"\n")
            sys.stdout.flush()
        except Exception: pass
asyncio.run(main())
'''


@pytest.mark.asyncio
async def test_mcp_manager_discover_tools():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command="python", args=["-c", _MOCK_SERVER])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            assert len(result.tools) == 1
            assert result.tools[0].name == "echo"


@pytest.mark.asyncio
async def test_mcp_call_tool():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command="python", args=["-c", _MOCK_SERVER])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("echo", {"message": "hello"})
            assert any("echo:hello" in c.text for c in result.content if c.type == "text")


def test_mcp_parse_tool_name():
    mgr = McpManager()
    s, t = mgr._parse_mcp_name("mcp__fs__read")
    assert s == "fs" and t == "read"


def test_is_mcp_tool():
    mgr = McpManager()
    assert mgr.is_mcp_tool("mcp__x__y")
    assert not mgr.is_mcp_tool("read")


if __name__ == "__main__":
    asyncio.run(test_mcp_manager_discover_tools())
    asyncio.run(test_mcp_call_tool())
    test_mcp_parse_tool_name()
    test_is_mcp_tool()
    print("All MCP tests passed!")
