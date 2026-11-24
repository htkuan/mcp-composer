import logging
from collections.abc import Mapping
from typing import Any

import anyio
from mcp.server.caching import CacheHint
from mcp.server.connection import Connection
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import (
    StreamableHTTPASGIApp,
    StreamableHTTPSessionManager,
)
from mcp.server.subscriptions import (
    InMemorySubscriptionBus,
    ListenHandler,
    ToolsListChanged,
)
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from domain.downstream_server import DownstreamMCPServer, DownstreamMCPServerTool
from domain.server_kit import ServerKit
from downstream_controller import DownstreamController
from origin_validation import OriginValidationMiddleware

# Get logger for this module
logger = logging.getLogger(__name__)

# ServerKit 隨時可能在管理介面被切換，tools/list 結果不應被 client 快取（SEP-2549）
_TOOLS_LIST_CACHE_HINT = CacheHint(ttl_ms=0, scope="private")


class _GatewayServer(Server):
    """在 2025-11-25 以前的 initialize handshake 中宣告 `tools.listChanged`。

    2026-07-28 起的連線由 `subscriptions/listen` 是否有註冊來決定該旗標，
    不受 NotificationOptions 影響。
    """

    def create_initialization_options(
        self,
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
        extensions: dict[str, dict[str, Any]] | None = None,
    ) -> InitializationOptions:
        return super().create_initialization_options(
            notification_options or NotificationOptions(tools_changed=True),
            experimental_capabilities,
            extensions,
        )


class Gateway:
    def __init__(
        self,
        server_kit: ServerKit,
        downstream_controller: DownstreamController,
        mcp_composer_proxy_url: str,
        allowed_origins: list[str] | None = None,
    ):
        self.server_kit = server_kit
        self.downstream_controller = downstream_controller
        base_path = f"/mcp/{self.server_kit.name}"
        # Streamable HTTP (支援所有協定版本，包含 2026-07-28)
        self.gateway_endpoint = f"{mcp_composer_proxy_url}{base_path}/mcp"
        # 舊版 HTTP+SSE transport，2026-07-28 起正式列為 Deprecated (SEP-2596)，
        # 僅保留給尚未支援 Streamable HTTP 的 client
        self.sse_endpoint = f"{mcp_composer_proxy_url}{base_path}/sse"
        self.allowed_origins = allowed_origins

        # 2026-07-28：list_changed 只透過 subscriptions/listen 串流送出
        self._subscriptions = InMemorySubscriptionBus()
        self._listen_handler = ListenHandler(self._subscriptions)
        # 2025-11-25 以前：透過各連線的 standalone stream 送出 notifications/tools/list_changed
        self._legacy_connections: set[Connection] = set()

        self.server = _GatewayServer(
            self.server_kit.name,
            cache_hints={"tools/list": _TOOLS_LIST_CACHE_HINT},
            get_tool_input_schema=self._get_tool_input_schema,
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
            on_subscriptions_listen=self._listen_handler,
        )
        self.session_manager = StreamableHTTPSessionManager(app=self.server)
        # 相對於 gateway 掛載位置的路徑，SDK 會自動加上 root_path
        self.sse = SseServerTransport("/messages/")
        self._cancel_scope: anyio.CancelScope | None = None

    @property
    def name(self):
        return self.server_kit.name

    def _enabled_tools(self) -> list[DownstreamMCPServerTool]:
        if not self.server_kit.enabled:
            return []
        return [
            self.downstream_controller.get_tool_by_control_name(tool_name)
            for tool_name in self.server_kit.list_enabled_tool_names()
        ]

    def _get_enabled_tool(self, tool_name: str) -> DownstreamMCPServerTool | None:
        if not self.server_kit.enabled:
            return None
        # 與 tools/list 一致：server 被停用時，其 tools 也不可呼叫
        if tool_name not in self.server_kit.list_enabled_tool_names():
            return None
        return self.downstream_controller.get_tool_by_control_name(tool_name)

    def _track_legacy_connection(self, ctx: ServerRequestContext) -> None:
        """記住 2025-11-25 以前的連線，以便 tools 變動時送出 list_changed。"""
        if ctx.protocol_version in MODERN_PROTOCOL_VERSIONS:
            return
        # SDK 2.3 的 ServerRequestContext 尚未公開 connection（`ctx.session` 是 per-request proxy），
        # 因此暫時透過 ServerSession 的內部屬性取得 connection-scoped 的 Connection
        connection = getattr(ctx.session, "_connection", None)
        if (
            not isinstance(connection, Connection)
            or connection in self._legacy_connections
        ):
            return
        self._legacy_connections.add(connection)
        # 連線關閉時自動移除，避免保留已斷線的 client
        connection.exit_stack.callback(self._legacy_connections.discard, connection)

    def _get_tool_input_schema(self, tool_name: str) -> Mapping[str, Any] | None:
        """供 2026-07-28 Streamable HTTP 驗證 `Mcp-Param-*` header，免去每次 tools/call 都跑 tools/list。"""
        tool = self._get_enabled_tool(tool_name)
        return tool.tool.input_schema if tool else None

    async def _list_tools(
        self, ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        self._track_legacy_connection(ctx)
        # 依 ServerKit 中的設定順序回傳，確保結果是 deterministic 的
        return ListToolsResult(
            tools=[t.to_new_name_tool() for t in self._enabled_tools()]
        )

    async def _call_tool(
        self, ctx: ServerRequestContext, params: CallToolRequestParams
    ) -> CallToolResult:
        self._track_legacy_connection(ctx)
        tool = self._get_enabled_tool(params.name)
        if tool is None:
            # 未知或已停用的 tool 屬於 protocol error，而非 tool execution error
            raise MCPError(INVALID_PARAMS, f"Unknown tool: {params.name}")
        try:
            server: DownstreamMCPServer = (
                self.downstream_controller.get_server_by_control_name(
                    tool.server_control_name
                )
            )
            return await server.call_tool(tool.tool.name, params.arguments or {})
        except Exception as e:  # noqa: BLE001
            # 下游執行失敗以 isError 回傳，讓模型能看到錯誤並自行修正
            return CallToolResult(
                content=[TextContent(type="text", text=str(e))],
                is_error=True,
            )

    async def notify_tools_changed(self) -> None:
        """ServerKit 的啟用狀態改變時，通知已連線的 client 重新取得 tools/list。"""
        await self._subscriptions.publish(ToolsListChanged())
        for connection in list(self._legacy_connections):
            # best-effort：standalone stream 已關閉時 SDK 會直接丟棄，不會拋錯
            await connection.send_tool_list_changed()

    async def run(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """Runs the Streamable HTTP session manager until stop() is called."""
        with anyio.CancelScope() as cancel_scope:
            self._cancel_scope = cancel_scope
            async with self.session_manager.run():
                task_status.started()
                await anyio.sleep_forever()

    def stop(self):
        # 先讓 subscriptions/listen 串流以 graceful closure 結束
        self._listen_handler.close()
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

        app = Starlette(
            debug=True,
            routes=[
                Route("/mcp", endpoint=StreamableHTTPASGIApp(self.session_manager)),
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=self.sse.handle_post_message),
            ],
        )
        return OriginValidationMiddleware(app, self.allowed_origins)
