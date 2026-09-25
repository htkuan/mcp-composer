import logging
from pydantic import BaseModel
from typing import Any, Dict, Optional
from enum import StrEnum
from mcp import Client, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.types import CallToolResult, Tool
from typing import List
from contextlib import AsyncExitStack

logger = logging.getLogger(__name__)


class ConnectionType(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "http"


# 可以把 server name 變成一個 type
DownstreamMCPServerName = str
DownstreamMCPServerToolName = str


class DownstreamMCPServerConfig(BaseModel):
    name: DownstreamMCPServerName
    # 連接類型，未指定時由 command / url 推斷
    type: Optional[ConnectionType] = None

    # stdio 類型的連接配置
    command: Optional[str] = None
    args: Optional[list] = None
    env: Optional[Dict] = None

    # streamable http / sse 類型的連接配置
    url: Optional[str] = None

    def get_connection_type(self) -> ConnectionType:
        if self.type:
            return self.type
        if self.command:
            return ConnectionType.STDIO
        if self.url:
            return ConnectionType.STREAMABLE_HTTP
        raise ValueError("Invalid server config")


class DownstreamMCPServerTool:
    def __init__(self, server_control_name: str, tool: Tool):
        self.server_control_name = server_control_name
        self.control_name = f"{server_control_name}-{tool.name}"
        self.tool = tool

    def to_new_name_tool(self) -> Tool:
        # 保留 title、annotations、output_schema 等欄位，只替換名稱
        return self.tool.model_copy(update={"name": self.control_name})


class DownstreamMCPServer:
    def __init__(self, config: DownstreamMCPServerConfig):
        self.config = config
        self.client: Client | None = None

        self._control_name: str | None = None

    def _new_client(self, connection_type: ConnectionType, mode: str) -> Client:
        url = self.config.url if self.config.url else ""
        if connection_type == ConnectionType.STDIO:
            command = self.config.command if self.config.command else ""
            params = StdioServerParameters(
                command=command,
                args=self.config.args or [],
                env=self.config.env,
            )
            return Client(params, mode=mode)
        if connection_type == ConnectionType.STREAMABLE_HTTP:
            return Client(url, mode=mode)
        if connection_type == ConnectionType.SSE:
            return Client(sse_client(url), mode=mode)
        raise ValueError("Invalid server config")

    async def initialize(self, exit_stack: AsyncExitStack):
        connection_type = self.config.get_connection_type()
        connection_types = [connection_type]
        if connection_type == ConnectionType.STREAMABLE_HTTP and not self.config.type:
            # 未指定 type 時，依規範的向下相容做法退回舊版 HTTP+SSE transport
            connection_types.append(ConnectionType.SSE)

        # mode="auto" 先以最新協定 (server/discover) 協商，不支援時退回 initialize handshake；
        # 部分舊版 server 收到 server/discover 會直接中斷連線，因此再用全新連線以 "legacy" 重試
        last_error: Exception | None = None
        for candidate in connection_types:
            for mode in ("auto", "legacy"):
                try:
                    self.client = await exit_stack.enter_async_context(
                        self._new_client(candidate, mode)
                    )
                except Exception as e:  # noqa: BLE001
                    cause: BaseException = e
                    while isinstance(cause, BaseExceptionGroup):
                        cause = cause.exceptions[0]
                    logger.warning(
                        f"Failed to connect to server '{self.config.name}' via {candidate} "
                        f"({mode} mode): {cause!r}"
                    )
                    last_error = e
                    continue
                self._control_name = self.config.name
                logger.info(
                    f"Connected to server '{self.config.name}' via {candidate} "
                    f"(protocol {self.client.protocol_version})"
                )
                return
        assert last_error is not None
        raise last_error

    async def shutdown(self):
        self.client = None

    def get_control_name(self) -> str:
        assert self._control_name, f"Server {self.config.name} not _control_name"
        return self._control_name

    async def list_tools(self) -> List[DownstreamMCPServerTool]:
        assert self._control_name, f"Server {self.config.name} not _control_name"

        if not self.client:
            raise ValueError("Server not initialized")

        tools: List[Tool] = []
        cursor: str | None = None
        while True:
            list_tools_result = await self.client.list_tools(cursor=cursor)
            tools.extend(list_tools_result.tools)
            cursor = list_tools_result.next_cursor
            if not cursor:
                break
        return [
            DownstreamMCPServerTool(self.get_control_name(), tool) for tool in tools
        ]

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None
    ) -> CallToolResult:
        if not self.client:
            raise ValueError("Server session is not initialized")
        return await self.client.call_tool(tool_name, arguments)
