import logging  # Import logging

import anyio
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import (
    StreamableHTTPASGIApp,
    StreamableHTTPSessionManager,
)
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from domain.downstream_server import DownstreamMCPServer, DownstreamMCPServerTool
from domain.server_kit import ServerKit
from downstream_controller import DownstreamController

# Get logger for this module
logger = logging.getLogger(__name__)


class Gateway:
    def __init__(
        self,
        server_kit: ServerKit,
        downstream_controller: DownstreamController,
        mcp_composer_proxy_url: str,
    ):
        self.server_kit = server_kit
        self.downstream_controller = downstream_controller
        base_path = f"/mcp/{self.server_kit.name}"
        # Streamable HTTP (支援所有協定版本，包含 2026-07-28)
        self.gateway_endpoint = f"{mcp_composer_proxy_url}{base_path}/mcp"
        # 舊版 HTTP+SSE transport，給尚未支援 Streamable HTTP 的 client
        self.sse_endpoint = f"{mcp_composer_proxy_url}{base_path}/sse"
        self.server = Server(
            self.server_kit.name,
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )
        self.session_manager = StreamableHTTPSessionManager(app=self.server)
        # 相對於 gateway 掛載位置的路徑，SDK 會自動加上 root_path
        self.sse = SseServerTransport("/messages/")
        self._cancel_scope: anyio.CancelScope | None = None

    @property
    def name(self):
        return self.server_kit.name

    async def _list_tools(
        self, ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        if not self.server_kit.enabled:
            return ListToolsResult(tools=[])
        enabled_tool_names = self.server_kit.list_enabled_tool_names()
        tools = []
        for tool_name in enabled_tool_names:
            tool: DownstreamMCPServerTool = (
                self.downstream_controller.get_tool_by_control_name(tool_name)
            )
            tools.append(tool)
        return ListToolsResult(tools=[t.to_new_name_tool() for t in tools])

    async def _call_tool(
        self, ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        try:
            if not self.server_kit.enabled:
                raise ValueError("Server kit is not enabled")
            tool_name = params.name
            # 與 list_tools 一致：server 被停用時，其 tools 也不可呼叫
            if tool_name not in self.server_kit.list_enabled_tool_names():
                raise ValueError(f"Tool {tool_name} is not enabled")
            tool: DownstreamMCPServerTool = (
                self.downstream_controller.get_tool_by_control_name(tool_name)
            )
            server_control_name = tool.server_control_name
            server: DownstreamMCPServer = (
                self.downstream_controller.get_server_by_control_name(
                    server_control_name
                )
            )
            return await server.call_tool(tool.tool.name, params.arguments or {})
        except Exception as e:  # noqa: BLE001
            return CallToolResult(
                content=[TextContent(type="text", text=str(e))],
                is_error=True,
            )

    async def run(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """Runs the Streamable HTTP session manager until stop() is called."""
        with anyio.CancelScope() as cancel_scope:
            self._cancel_scope = cancel_scope
            async with self.session_manager.run():
                task_status.started()
                await anyio.sleep_forever()

    def stop(self):
        if self._cancel_scope:
            self._cancel_scope.cancel()

    def as_asgi_route(self):
        async def handle_sse(request: Request) -> Response:
            async with self.sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await self.server.run(
                    streams[0], streams[1], self.server.create_initialization_options()
                )
            # Return empty response to avoid NoneType error on client disconnect
            return Response()

        return Starlette(
            debug=True,
            routes=[
                Route("/mcp", endpoint=StreamableHTTPASGIApp(self.session_manager)),
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=self.sse.handle_post_message),
            ],
        )
