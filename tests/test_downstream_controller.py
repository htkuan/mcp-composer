import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.downstream_controller import DownstreamController
from src.domain.downstream_server import DownstreamMCPServerConfig, DownstreamMCPServer, DownstreamMCPServerTool


@pytest.fixture
def mock_async_exit_stack():
    return AsyncMock()

from mcp.types import Tool # Import Tool

@pytest.fixture
def mock_server_config():
    # Minimal valid config for stdio type. 'name' is the required field.
    # 'command' or 'url' is needed for get_connection_type to succeed.
    config = DownstreamMCPServerConfig(
        name="test_server_1",
        command="echo hello"  # Provide a command for stdio type
    )
    return config

@pytest.fixture
def mock_mcp_tool():
    # This is the Tool object from mcp.types
    return Tool(name="actual_tool_name", description="A mock tool", inputSchema={})

@pytest.fixture
def mock_server_tool(mock_mcp_tool): # Depends on mock_mcp_tool
    # DownstreamMCPServerTool wraps a Tool object
    # Its control_name is generated internally as server_control_name + tool.name
    server_name_for_tool = "test_server_1" 
    tool_wrapper = DownstreamMCPServerTool(
        server_control_name=server_name_for_tool, 
        tool=mock_mcp_tool
    )
    return tool_wrapper

@pytest.fixture
def downstream_controller(mock_async_exit_stack):
    # Initialize DownstreamController with an empty list of configs for these tests
    # We will add servers dynamically
    controller = DownstreamController(configs=[])
    # Replace the controller's exit_stack with our mock for testing
    controller.exit_stack = mock_async_exit_stack
    return controller

@pytest.mark.asyncio
async def test_dummy():
    # This is a placeholder test to ensure the setup is working.
    # It will be replaced with actual tests.
    assert True

@pytest.mark.asyncio
@patch('src.downstream_controller.DownstreamMCPServer', autospec=True)
async def test_add_server(MockDownstreamMCPServer, downstream_controller, mock_server_config, mock_server_tool, mock_async_exit_stack):
    # Configure the mock server instance
    mock_server_instance = MockDownstreamMCPServer.return_value
    # get_control_name should return the 'name' from the config
    mock_server_instance.get_control_name.return_value = mock_server_config.name
    mock_server_instance.list_tools = AsyncMock(return_value=[mock_server_tool])
    mock_server_instance.initialize = AsyncMock()

    await downstream_controller.add_server(mock_server_config)

    # Assertions
    mock_server_instance.initialize.assert_called_once_with(mock_async_exit_stack)
    # Use .name for map keys as per DownstreamMCPServerConfig
    assert mock_server_config.name in downstream_controller._servers_map
    assert downstream_controller._servers_map[mock_server_config.name] == mock_server_instance

    found_server_in_all_tools = any(
        s == mock_server_instance for s, _ in downstream_controller._all_servers_tools
    )
    assert found_server_in_all_tools

    found_tool_in_all_tools = any(
        mock_server_tool in tools_list for _, tools_list in downstream_controller._all_servers_tools if _ == mock_server_instance
    )
    assert found_tool_in_all_tools
    
    assert mock_server_tool.control_name in downstream_controller._tools_map
    assert downstream_controller._tools_map[mock_server_tool.control_name] == mock_server_tool


@pytest.mark.asyncio
@patch('src.downstream_controller.DownstreamMCPServer', autospec=True)
async def test_add_multiple_servers(MockDownstreamMCPServer, downstream_controller, mock_server_tool, mock_async_exit_stack):
    # Use 'name' and minimal valid fields for configs
    config1 = DownstreamMCPServerConfig(name="server1", command="echo server1")
    config2 = DownstreamMCPServerConfig(name="server2", command="echo server2")

    server_instance1 = AsyncMock(spec=DownstreamMCPServer)
    server_instance1.get_control_name.return_value = "server1"
    server_instance1.list_tools = AsyncMock(return_value=[mock_server_tool]) # Assuming same tool for simplicity
    server_instance1.initialize = AsyncMock()

    server_instance2 = AsyncMock(spec=DownstreamMCPServer)
    server_instance2.get_control_name.return_value = "server2"
    server_instance2.list_tools = AsyncMock(return_value=[]) # No tools for server2
    server_instance2.initialize = AsyncMock()

    # Make MockDownstreamMCPServer return different instances for different calls
    MockDownstreamMCPServer.side_effect = [server_instance1, server_instance2]

    await downstream_controller.add_server(config1)
    await downstream_controller.add_server(config2)

    server_instance1.initialize.assert_called_once_with(mock_async_exit_stack)
    server_instance2.initialize.assert_called_once_with(mock_async_exit_stack)

    assert "server1" in downstream_controller._servers_map
    assert downstream_controller._servers_map["server1"] == server_instance1
    assert "server2" in downstream_controller._servers_map
    assert downstream_controller._servers_map["server2"] == server_instance2
    
    assert len(downstream_controller._all_servers_tools) == 2
    assert mock_server_tool.control_name in downstream_controller._tools_map # From server1


@pytest.mark.asyncio
@patch('src.downstream_controller.DownstreamMCPServer', autospec=True)
async def test_remove_server(MockDownstreamMCPServer, downstream_controller, mock_server_config, mock_server_tool, mock_async_exit_stack):
    # Add a server first
    mock_server_instance = MockDownstreamMCPServer.return_value
    # get_control_name should return the 'name' from the config
    mock_server_instance.get_control_name.return_value = mock_server_config.name
    mock_server_instance.list_tools = AsyncMock(return_value=[mock_server_tool])
    mock_server_instance.initialize = AsyncMock()
    mock_server_instance.shutdown = AsyncMock() # Mock the shutdown method

    await downstream_controller.add_server(mock_server_config)
    
    # Ensure it's added (use .name)
    assert mock_server_config.name in downstream_controller._servers_map
    assert mock_server_tool.control_name in downstream_controller._tools_map

    # Now remove the server (use .name)
    await downstream_controller.remove_server(mock_server_config.name)

    mock_server_instance.shutdown.assert_called_once()
    assert mock_server_config.name not in downstream_controller._servers_map
    assert not any(s == mock_server_instance for s, _ in downstream_controller._all_servers_tools)
    assert mock_server_tool.control_name not in downstream_controller._tools_map


@pytest.mark.asyncio
async def test_remove_non_existent_server(downstream_controller):
    # Attempt to remove a server that hasn't been added
    non_existent_server_name = "non_existent_server"
    
    # We expect no exceptions to be raised, and the state to remain empty
    await downstream_controller.remove_server(non_existent_server_name)
    
    assert non_existent_server_name not in downstream_controller._servers_map
    assert len(downstream_controller._all_servers_tools) == 0
    assert len(downstream_controller._tools_map) == 0
    # Add specific check for logging if you implement it in the controller
    # For now, just ensure no crash and maps are empty as expected.
