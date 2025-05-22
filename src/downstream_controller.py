from domain.downstream_server import (
    DownstreamMCPServerConfig,
    DownstreamMCPServer,
    DownstreamMCPServerTool,
)
from typing import Dict, List, Tuple
import asyncio
from contextlib import AsyncExitStack


class DownstreamController:
    def __init__(self, configs: List[DownstreamMCPServerConfig]):
        self._all_servers_tools: List[
            Tuple[DownstreamMCPServer, List[DownstreamMCPServerTool]]
        ] = []
        self._servers_map: Dict[str, DownstreamMCPServer] = {}
        self._tools_map: Dict[str, DownstreamMCPServerTool] = {}
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
    ) -> List[Tuple[DownstreamMCPServer, List[DownstreamMCPServerTool]]]:
        return self._all_servers_tools

    def get_tool_by_control_name(
        self, tool_control_name: str
    ) -> DownstreamMCPServerTool:
        return self._tools_map[tool_control_name]

    def get_server_by_control_name(
        self, server_control_name: str
    ) -> DownstreamMCPServer:
        return self._servers_map[server_control_name]

    async def add_server(self, config: DownstreamMCPServerConfig):
        """Adds a new downstream server to the controller."""
        async with self._asyncio_lock:
            # TODO: Add logging
            # print(f"Adding server: {config.control_name}") 
            server = DownstreamMCPServer(config)
            await server.initialize(self.exit_stack)
            self._servers_map[server.get_control_name()] = server
            tools = await server.list_tools()
            self._all_servers_tools.append((server, tools))
            for tool in tools:
                self._tools_map[tool.control_name] = tool
            # print(f"Server {config.control_name} added successfully.")

    async def remove_server(self, server_control_name: str):
        """Removes a downstream server from the controller."""
        async with self._asyncio_lock:
            # TODO: Add logging
            # print(f"Removing server: {server_control_name}")
            if server_control_name not in self._servers_map:
                # print(f"Server {server_control_name} not found.")
                return

            server = self._servers_map.pop(server_control_name)
            await server.shutdown()

            # Remove server and its tools from self._all_servers_tools
            self._all_servers_tools = [
                (s, t) for s, t in self._all_servers_tools if s != server
            ]

            # Remove tools associated with this server from self._tools_map
            # Assuming tools are unique to the server, or handled if not.
            # This needs to be done carefully if tool names can overlap across servers.
            # For now, assuming tool_control_name is globally unique as per current structure.
            tools_to_remove = await server.list_tools() # Re-list or store them initially
            for tool in tools_to_remove:
                if tool.control_name in self._tools_map:
                    del self._tools_map[tool.control_name]
            # print(f"Server {server_control_name} removed successfully.")
