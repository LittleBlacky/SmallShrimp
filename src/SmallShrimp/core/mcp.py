"""MCP Client — Model Context Protocol via official mcp SDK.

Supports both stdio and SSE transports.

Config from workspace/config.user.yaml:
  mcp_servers:
    filesystem:
      command: npx
      args: [-y, @modelcontextprotocol/server-filesystem, /path]
    remote_db:
      transport: sse
      url: https://db-mcp.example.com/sse
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


@dataclass
class McpToolInfo:
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    server_name: str = ""


class McpManager:

    def __init__(self):
        self._servers: dict[str, dict] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._transports: dict[str, tuple] = {}
        self._tools: list[McpToolInfo] = []
        self._initialized = False

    def configure(self, servers: dict[str, dict]) -> None:
        self._servers = servers

    async def connect_all(self) -> None:
        if self._initialized:
            return
        for name, cfg in self._servers.items():
            try:
                logger.info(f"[mcp] connecting to {name}...")
                if cfg.get("transport") == "sse":
                    await self._connect_sse(name, cfg)
                else:
                    await self._connect_stdio(name, cfg)

                session = self._sessions[name]
                result = await session.list_tools()
                for t in result.tools:
                    mcp_name = f"mcp__{name}__{t.name}"
                    schema = t.inputSchema if hasattr(t, 'inputSchema') else {}
                    self._tools.append(McpToolInfo(
                        name=mcp_name,
                        description=t.description or f"MCP tool: {t.name}",
                        input_schema=schema,
                        server_name=name,
                    ))
                logger.info(f"[mcp] {name}: {len(result.tools)} tools")
            except Exception as e:
                logger.warning(f"[mcp] {name} failed: {e}")
        self._initialized = True

    async def _connect_stdio(self, name: str, cfg: dict) -> None:
        params = StdioServerParameters(
            command=cfg["command"],
            args=cfg.get("args", []),
            env=cfg.get("env") or None,
        )
        self._transports[name] = stdio_client(params)
        read, write = await self._transports[name].__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        self._sessions[name] = session

    async def _connect_sse(self, name: str, cfg: dict) -> None:
        from mcp.client.sse import sse_client
        self._transports[name] = sse_client(cfg["url"])
        read, write = await self._transports[name].__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        self._sessions[name] = session

    def get_tool_definitions(self) -> list[dict]:
        return [{"name": t.name, "description": t.description,
                 "input_schema": t.input_schema} for t in self._tools]

    def is_mcp_tool(self, name: str) -> bool:
        return name.startswith("mcp__")

    def _parse_mcp_name(self, full_name: str) -> tuple[str, str]:
        parts = full_name.split("__", 2)
        if len(parts) >= 3:
            return parts[1], parts[2]
        raise ValueError(f"Invalid MCP tool name: {full_name}")

    async def call_tool(self, full_name: str, args: dict) -> str:
        server_name, tool_name = self._parse_mcp_name(full_name)
        session = self._sessions.get(server_name)
        if not session:
            return f"Error: MCP server '{server_name}' not found"
        result = await session.call_tool(tool_name, args)
        if result.content:
            return "\n".join(c.text for c in result.content if c.type == "text")
        return ""

    async def close_all(self) -> None:
        for session in self._sessions.values():
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
        for transport in self._transports.values():
            try:
                await transport.__aexit__(None, None, None)
            except Exception:
                pass


def make_mcp_tool(mcp_manager: McpManager, tool_name: str, description: str, mcp_def: dict):
    """Create a Tool that routes calls to MCP manager. Used by Agent to register MCP tools."""
    from ..tools.base import Tool, ToolResult

    class McpTool(Tool):
        @property
        def name(self) -> str:
            return tool_name

        @property
        def description(self) -> str:
            return description

        def get_parameters(self) -> dict:
            return mcp_def.get("input_schema", {})

        async def execute(self, **kwargs):
            try:
                result = await mcp_manager.call_tool(tool_name, kwargs)
                return ToolResult(success=True, content=result)
            except Exception as e:
                return ToolResult(success=False, content="", error=str(e))

        async def call(self, **kwargs):
            return await self.execute(**kwargs)

    return McpTool()


async def register_mcp_tools(mcp_manager: McpManager, tool_registry) -> None:
    """Connect MCP servers and register discovered tools into the registry."""
    if not mcp_manager._initialized:
        await mcp_manager.connect_all()
    for mcp_def in mcp_manager.get_tool_definitions():
        tool_registry.register(
            make_mcp_tool(mcp_manager, mcp_def["name"], mcp_def["name"], mcp_def)
        )
        self._sessions.clear()
        self._transports.clear()
