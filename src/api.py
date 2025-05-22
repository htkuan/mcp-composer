from fastapi import APIRouter, Request
from typing import List
from composer import Composer
from domain.server_kit import ServerKit
from pydantic import BaseModel
from gateway import Gateway

v1_api_router = APIRouter(prefix="/api/v1")


@v1_api_router.get("/kits")
async def list_server_kits(request: Request) -> List[ServerKit]:
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
    server_kit: ServerKit


def new_gateway_response(gateway: Gateway) -> GatewayResponse:
    return GatewayResponse(
        name=gateway.name,
        gateway_endpoint=gateway.gateway_endpoint,
        server_kit=gateway.server_kit,
    )


@v1_api_router.get("/gateways")
async def list_gateways(request: Request) -> List[GatewayResponse]:
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


# Server Management Endpoints
import logging
from fastapi import HTTPException, status
from downstream_controller import DownstreamController
from domain.downstream_server import DownstreamMCPServerConfig

logger = logging.getLogger(__name__)

servers_router = APIRouter(prefix="/servers", tags=["servers"])


@servers_router.post("/", status_code=status.HTTP_201_CREATED)
async def add_new_server(config: DownstreamMCPServerConfig, request: Request):
    controller: DownstreamController = request.app.state.downstream_controller
    try:
        # Check if server already exists
        try:
            # Use config.name as per DownstreamMCPServerConfig model
            controller.get_server_by_control_name(config.name) 
            logger.warning(f"Attempted to add duplicate server: {config.name}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Server with control name '{config.name}' already exists.",
            )
        except KeyError:
            # Server does not exist, proceed to add
            pass

        await controller.add_server(config)
        logger.info(f"Server '{config.name}' added successfully.")
        return {"message": f"Server '{config.name}' added successfully."}
    except HTTPException: # Specifically catch HTTPException and re-raise
        raise
    except Exception as e:
        logger.error(f"Error adding server '{config.name}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred while adding server '{config.name}'.",
        )


@servers_router.delete("/{server_control_name}", status_code=status.HTTP_200_OK)
async def remove_existing_server(server_control_name: str, request: Request):
    controller: DownstreamController = request.app.state.downstream_controller
    try:
        # Check if server exists before attempting removal
        try:
            controller.get_server_by_control_name(server_control_name)
        except KeyError:
            logger.warning(f"Attempted to remove non-existent server: {server_control_name}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Server with control name '{server_control_name}' not found.",
            )

        await controller.remove_server(server_control_name)
        logger.info(f"Server '{server_control_name}' removed successfully.")
        return {"message": f"Server '{server_control_name}' removed successfully."}
    except HTTPException:
        raise # Re-raise HTTPException directly
    except Exception as e:
        logger.error(f"Error removing server '{server_control_name}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred while removing server '{server_control_name}'.",
        )

v1_api_router.include_router(servers_router)
