from pydantic import BaseModel
from typing import Dict, Optional
from enum import Enum # Changed from StrEnum
from mcp.types import Tool
from mcp.client.sse import sse_client
from mcp import ClientSession, StdioServerParameters, stdio_client
from typing import List
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from contextlib import AsyncExitStack


class ConnectionType(str, Enum): # Changed from StrEnum
    STDIO = "stdio"
    SSE = "sse"


# 可以把 server name 變成一個 type
DownstreamMCPServerName = str
DownstreamMCPServerToolName = str


class DownstreamMCPServerConfig(BaseModel):
    name: DownstreamMCPServerName
    # stdio 類型的連接配置
    command: Optional[str] = None
    args: Optional[list] = None
    env: Optional[Dict] = None

    # sse 類型的連接配置
    url: Optional[str] = None

    def get_connection_type(self) -> ConnectionType:
        if self.command:
            return ConnectionType.STDIO
        if self.url:
            return ConnectionType.SSE
        raise ValueError("Invalid server config")


class DownstreamMCPServerTool:
    def __init__(self, server_control_name: str, tool: Tool):
        self.server_control_name = server_control_name
        self.control_name = f"{server_control_name}-{tool.name}"
        self.tool = tool

    def to_new_name_tool(self) -> Tool:
        return Tool(
            name=self.control_name,
            description=self.tool.description,
            inputSchema=self.tool.inputSchema,
        )


class DownstreamMCPServer:
    def __init__(self, config: DownstreamMCPServerConfig):
        self.config = config
        self.session: ClientSession | None = None
        self.read_stream: MemoryObjectReceiveStream | None = None
        self.write_stream: MemoryObjectSendStream | None = None

        self._control_name: str | None = None

    async def initialize(self, exit_stack: AsyncExitStack):
        connection_type = self.config.get_connection_type()

        if connection_type == ConnectionType.STDIO:
            command = self.config.command if self.config.command else ""
            params = StdioServerParameters(
                command=command,
                args=self.config.args or [],
                env=self.config.env or {},
            )
            transport = await exit_stack.enter_async_context(stdio_client(params))
            self.read_stream, self.write_stream = transport
            self.session = await exit_stack.enter_async_context(
                ClientSession(self.read_stream, self.write_stream)
            )
            await self.session.initialize()

        elif connection_type == ConnectionType.SSE:
            url = self.config.url if self.config.url else ""
            transport = await exit_stack.enter_async_context(sse_client(url))
            self.read_stream, self.write_stream = transport
            self.session = await exit_stack.enter_async_context(
                ClientSession(self.read_stream, self.write_stream)
            )
            await self.session.initialize()
        else:
            raise ValueError("Invalid server config")
        self._control_name = self.config.name

    async def shutdown(self):
        self.session = None
        self.read_stream = None
        self.write_stream = None

    def get_control_name(self) -> str:
        assert self._control_name, f"Server {self.config.name} not _control_name"
        return self._control_name

    async def list_tools(self) -> List[DownstreamMCPServerTool]:
        assert self._control_name, f"Server {self.config.name} not _control_name"

        if not self.session:
            raise ValueError("Server not initialized")

        list_tools_result = await self.session.list_tools()
        return [
            DownstreamMCPServerTool(self.get_control_name(), tool)
            for tool in list_tools_result.tools
        ]
