from contextlib import asynccontextmanager
from typing import Dict, List
import anyio
from anyio.abc import TaskGroup
from domain.server_kit import ServerKit
from downstream_controller import DownstreamController
from fastapi import FastAPI
from gateway import Gateway
from config import Config
from starlette.routing import Mount


class Composer:
    def __init__(self, downstream_controller: DownstreamController, config: Config):
        self.server_kits_map: Dict[str, ServerKit] = {}
        self.downstream_controller = downstream_controller
        self.gateway_map: Dict[str, Gateway] = {}
        self._asgi_app = FastAPI()
        self.config = config
        self._task_group: TaskGroup | None = None

    @asynccontextmanager
    async def run(self):
        """Hosts the gateways' background tasks; gateways can only be added while running."""
        async with anyio.create_task_group() as tg:
            self._task_group = tg
            try:
                yield
            finally:
                tg.cancel_scope.cancel()
                self._task_group = None

    def asgi_gateway_routes(self):
        return self._asgi_app

    # APIs
    # ServerKit
    async def list_server_kits(self) -> List[ServerKit]:
        return list(self.server_kits_map.values())

    async def get_server_kit(self, name: str) -> ServerKit:
        return self.server_kits_map[name]

    def create_server_kit(
        self,
        name: str,
        enabled: bool = True,
    ) -> ServerKit:
        if (
            not self.downstream_controller
            or not self.downstream_controller.is_initialized()
        ):
            raise ValueError("Downstream controller not set or not initialized")
        server_kit = ServerKit.new_server_kit(name)
        for server, tools in self.downstream_controller.list_all_servers_tools():
            server_kit.servers_enabled[server.get_control_name()] = enabled
            server_kit.servers_tools_hierarchy_map[server.get_control_name()] = []
            for tool in tools:
                server_kit.tools_enabled[tool.control_name] = enabled
                server_kit.servers_tools_hierarchy_map[
                    server.get_control_name()
                ].append(tool.control_name)
                server_kit.tools_servers_map[tool.control_name] = (
                    server.get_control_name()
                )
        self.server_kits_map[name] = server_kit
        return server_kit

    async def disable_server_kit(self, name: str) -> ServerKit:
        server_kit = self.server_kits_map[name]
        server_kit.disable_kit()
        return server_kit

    async def enable_server_kit(self, name: str) -> ServerKit:
        server_kit = self.server_kits_map[name]
        server_kit.enable_kit()
        return server_kit

    async def disable_server(self, name: str, server_name: str) -> ServerKit:
        server_kit = self.server_kits_map[name]
        server_kit.disable_server(server_name)
        return server_kit

    async def enable_server(self, name: str, server_name: str) -> ServerKit:
        server_kit = self.server_kits_map[name]
        server_kit.enable_server(server_name)
        return server_kit

    async def disable_tool(self, name: str, tool_name: str) -> ServerKit:
        server_kit = self.server_kits_map[name]
        server_kit.disable_tool(tool_name)
        return server_kit

    async def enable_tool(self, name: str, tool_name: str) -> ServerKit:
        server_kit = self.server_kits_map[name]
        server_kit.enable_tool(tool_name)
        return server_kit

    # Gateway
    async def list_gateways(self) -> List[Gateway]:
        return list(self.gateway_map.values())

    async def get_gateway(self, name: str) -> Gateway:
        return self.gateway_map[name]

    async def add_gateway(self, server_kit: ServerKit):
        if server_kit.name in self.gateway_map:
            raise ValueError(f"Gateway {server_kit.name} already exists")
        if self._task_group is None:
            raise RuntimeError("Composer is not running")
        gateway = Gateway(
            server_kit,
            self.downstream_controller,
            self.config.mcp_composer_proxy_url,
        )
        await self._task_group.start(gateway.run)
        self.gateway_map[server_kit.name] = gateway
        self._asgi_app.mount(f"/{server_kit.name}", gateway.as_asgi_route())
        return gateway

    async def remove_gateway(self, name: str):
        if len(self.gateway_map) == 1:
            raise ValueError("Cannot remove the last gateway")
        if name not in self.gateway_map:
            raise ValueError(f"Gateway {name} does not exist")

        # Find and remove the mounted route
        route_to_remove = None
        target_path = f"/{name}"
        for route in self._asgi_app.routes:
            # Check if it's a Mount route and the path matches
            if isinstance(route, Mount) and route.path == target_path:
                route_to_remove = route
                break

        if route_to_remove:
            self._asgi_app.routes.remove(route_to_remove)
        else:
            # Optionally handle the case where the route wasn't found,
            # though this might indicate an inconsistent state.
            # Consider logging a warning here.
            pass

        # Remove the gateway from the map
        gateway = self.gateway_map[name]
        del self.gateway_map[name]
        gateway.stop()
        return gateway
