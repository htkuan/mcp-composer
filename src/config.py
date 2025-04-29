import os
import json
import logging
import sys
from pathlib import Path
from typing import List

from domain.downstream_server import DownstreamMCPServerConfig
from dotenv import load_dotenv

# load .env file
load_dotenv()


# --- Logger Setup Function ---
class InfoFilter(logging.Filter):
    """Filters out log records with level ERROR or higher."""

    def filter(self, record):
        return record.levelno < logging.ERROR


def setup_logging():
    """Configures the root logger with handlers for stdout and stderr."""
    root_logger = logging.getLogger()  # Get the root logger
    root_logger.setLevel(logging.DEBUG)  # Set minimum level for root logger

    # Prevent duplicate handlers if called multiple times (optional but good practice)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Stdout handler (for DEBUG, INFO, WARNING)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)  # Process messages from DEBUG level up
    stdout_handler.addFilter(InfoFilter())  # Filter out ERROR and CRITICAL
    stdout_handler.setFormatter(formatter)

    # Stderr handler (for ERROR, CRITICAL)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)  # Process messages from ERROR level up
    stderr_handler.setFormatter(formatter)

    # Add handlers to the root logger
    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(stderr_handler)


# --- End Logger Setup Function ---

# Logger for this module (config.py)
config_logger = logging.getLogger(__name__)


class Config:
    """Manages application settings, loading MCP server configurations from a JSON file."""

    _DEFAULT_CONFIG_PATH = "./mcp_servers.json"

    def __init__(self):
        """Initializes the Config object."""
        self.config_json_path = self._get_config_path(
            "MCP_SERVERS_CONFIG_PATH", self._DEFAULT_CONFIG_PATH
        )
        self.servers: List[DownstreamMCPServerConfig] = (
            self._load_mcp_servers_config_from_json()
        )
        # Read host and port from environment variables with defaults
        self.host = os.environ.get("HOST", "0.0.0.0")
        self.port = int(os.environ.get("PORT", 8000))
        # Read MCP Composer proxy URL from environment variable
        self.mcp_composer_proxy_url = os.environ.get(
            "MCP_COMPOSER_PROXY_URL", "http://localhost:8000"
        )

    def _get_config_path(self, env_var: str, default_path: str) -> Path:
        """Determines the configuration file path to use."""
        config_path_str = os.environ.get(env_var, default_path)
        return Path(config_path_str)

    def _load_mcp_servers_config_from_json(self) -> List[DownstreamMCPServerConfig]:
        """Loads MCP server configurations from the configuration file path."""
        configs = []
        try:
            with open(self.config_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            mcp_servers = data.get("mcpServers", {})
            for name, config_data in mcp_servers.items():
                command = config_data.get("command")
                args = config_data.get("args", [])
                env = config_data.get("env")
                url = config_data.get("url")

                if not command and not url:
                    config_logger.warning(
                        f"Server '{name}' is missing both 'command' and 'url' fields and will be skipped."
                    )
                    continue

                # You could potentially read other fields like timeout, transportType here
                # if DownstreamMCPServerConfig requires them.

                c = DownstreamMCPServerConfig(
                    name=name, command=command, args=args, env=env, url=url
                )
                configs.append(c)

        except FileNotFoundError:
            config_logger.error(
                f"Configuration file not found: {self.config_json_path}"
            )
        except json.JSONDecodeError:
            config_logger.error(
                f"Failed to parse configuration file: {self.config_json_path}"
            )
        except Exception as e:
            config_logger.exception(  # Use logger.exception to include traceback
                f"An unexpected error occurred while reading the configuration file {self.config_json_path}: {e}"
            )

        return configs
