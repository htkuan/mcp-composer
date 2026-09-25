from fastapi import APIRouter, Request
from pydantic import BaseModel

from composer import Composer
from domain.server_kit import ServerKit
from gateway import Gateway

v1_api_router = APIRouter(prefix="/api/v1")


@v1_api_router.get("/kits")
async def list_server_kits(request: Request) -> list[ServerKit]:
    composer: Composer = request.app.state.composer
    return await composer.list_server_kits()


@v1_api_router.get("/kits/{name}")
async def get_server_kit(request: Request, name: str) -> ServerKit:
    composer: Composer = request.app.state.composer
    return await composer.get_server_kit(name)


@v1_api_router.post("/kits/{name}/disable")
async def disable_server_kit(request: Request, name: str) -> ServerKit:
    composer: Composer = request.app.state.composer
    return await composer.disable_server_kit(name)


@v1_api_router.post("/kits/{name}/enable")
async def enable_server_kit(request: Request, name: str) -> ServerKit:
    composer: Composer = request.app.state.composer
    return await composer.enable_server_kit(name)


@v1_api_router.post("/kits/{name}/servers/{server_name}/disable")
async def disable_server(request: Request, name: str, server_name: str) -> ServerKit:
    composer: Composer = request.app.state.composer
    return await composer.disable_server(name, server_name)


@v1_api_router.post("/kits/{name}/servers/{server_name}/enable")
async def enable_server(request: Request, name: str, server_name: str) -> ServerKit:
    composer: Composer = request.app.state.composer
    return await composer.enable_server(name, server_name)


@v1_api_router.post("/kits/{name}/tools/{tool_name}/disable")
async def disable_tool(request: Request, name: str, tool_name: str) -> ServerKit:
    composer: Composer = request.app.state.composer
    return await composer.disable_tool(name, tool_name)


@v1_api_router.post("/kits/{name}/tools/{tool_name}/enable")
async def enable_tool(request: Request, name: str, tool_name: str) -> ServerKit:
    composer: Composer = request.app.state.composer
    return await composer.enable_tool(name, tool_name)


# Gateway
class GatewayResponse(BaseModel):
    name: str
    gateway_endpoint: str
    sse_endpoint: str
    server_kit: ServerKit


def new_gateway_response(gateway: Gateway) -> GatewayResponse:
    return GatewayResponse(
        name=gateway.name,
        gateway_endpoint=gateway.gateway_endpoint,
        sse_endpoint=gateway.sse_endpoint,
        server_kit=gateway.server_kit,
    )


@v1_api_router.get("/gateways")
async def list_gateways(request: Request) -> list[GatewayResponse]:
    composer: Composer = request.app.state.composer
    gateways = await composer.list_gateways()
    return [new_gateway_response(gateway) for gateway in gateways]


@v1_api_router.get("/gateways/{name}")
async def get_gateway(request: Request, name: str) -> GatewayResponse:
    composer: Composer = request.app.state.composer
    gateway = await composer.get_gateway(name)
    return new_gateway_response(gateway)


class AddGatewayRequest(BaseModel):
    name: str
    server_kit: ServerKit


@v1_api_router.post("/gateways")
async def add_gateway(
    request: Request, add_gateway_request: AddGatewayRequest
) -> GatewayResponse:
    composer: Composer = request.app.state.composer
    server_kit: ServerKit = composer.create_server_kit(add_gateway_request.name)
    server_kit.servers_enabled = add_gateway_request.server_kit.servers_enabled
    server_kit.tools_enabled = add_gateway_request.server_kit.tools_enabled
    gateway = await composer.add_gateway(server_kit)
    return new_gateway_response(gateway)


@v1_api_router.delete("/gateways/{name}")
async def remove_gateway(request: Request, name: str) -> GatewayResponse:
    composer: Composer = request.app.state.composer
    gateway = await composer.remove_gateway(name)
    return new_gateway_response(gateway)
