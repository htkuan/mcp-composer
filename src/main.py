from fastapi import FastAPI
from contextlib import asynccontextmanager
import uvicorn
from downstream_controller import DownstreamController
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from composer import Composer
from config import Config, setup_logging
from api import v1_api_router

# Setup logging as early as possible
setup_logging()

config = Config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # FastAPI server start
    downstream_controller = DownstreamController(config.servers)
    await downstream_controller.initialize()
    app.state.downstream_controller = downstream_controller

    # Initialize and store in app.state after controller is ready
    # Pass config to Composer
    composer = Composer(downstream_controller, config)
    app.state.composer = composer
    server_kit = composer.create_server_kit("composer")
    await composer.add_gateway(server_kit)
    app.mount("/mcp/", app.state.composer.asgi_gateway_routes())

    yield
    # FastAPI server shutdown
    await downstream_controller.shutdown()


app = FastAPI(debug=True, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def read_root():
    return FileResponse("src/ui/index.html")


app.include_router(v1_api_router)

if __name__ == "__main__":
    # Use host and port from the config instance
    uvicorn.run(app, host=config.host, port=config.port)
