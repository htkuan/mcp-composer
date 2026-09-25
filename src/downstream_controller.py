import asyncio
from contextlib import AsyncExitStack

from domain.downstream_server import (
    DownstreamMCPServer,
    DownstreamMCPServerConfig,
    DownstreamMCPServerTool,
)


class DownstreamController:
    def __init__(self, configs: list[DownstreamMCPServerConfig]):
        self._all_servers_tools: list[
            tuple[DownstreamMCPServer, list[DownstreamMCPServerTool]]
        ] = []
        self._servers_map: dict[str, DownstreamMCPServer] = {}
        self._tools_map: dict[str, DownstreamMCPServerTool] = {}
        self._asyncio_lock = asyncio.Lock()
        self.configs = configs
        self.exit_stack = AsyncExitStack()
        self._initialized = False

    async def initialize(self):
        async with self._asyncio_lock:
            for config in self.configs:
                await self.register_downstream_mcp_server(config)
            self._initialized = True

    def is_initialized(self) -> bool:
        return self._initialized

    async def shutdown(self):
        async with self._asyncio_lock:
            for server, _ in self._all_servers_tools:
                await server.shutdown()
            await self.exit_stack.aclose()

    async def register_downstream_mcp_server(self, config: DownstreamMCPServerConfig):
        server = DownstreamMCPServer(config)
        await server.initialize(self.exit_stack)
        self._servers_map[server.get_control_name()] = server
        tools = await server.list_tools()
        self._all_servers_tools.append((server, tools))
        for tool in tools:
            self._tools_map[tool.control_name] = tool

    def list_all_servers_tools(
        self,
    ) -> list[tuple[DownstreamMCPServer, list[DownstreamMCPServerTool]]]:
        return self._all_servers_tools

    def get_tool_by_control_name(
        self, tool_control_name: str
    ) -> DownstreamMCPServerTool:
        return self._tools_map[tool_control_name]

    def get_server_by_control_name(
        self, server_control_name: str
    ) -> DownstreamMCPServer:
        return self._servers_map[server_control_name]
