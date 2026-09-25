from pydantic import BaseModel


class ServerKit(BaseModel):
    name: str
    enabled: bool
    servers_enabled: dict[str, bool]
    tools_enabled: dict[str, bool]
    servers_tools_hierarchy_map: dict[str, list[str]]
    tools_servers_map: dict[str, str]

    @classmethod
    def new_server_kit(cls, name: str) -> "ServerKit":
        return ServerKit(
            name=name,
            enabled=True,
            servers_enabled={},
            tools_enabled={},
            servers_tools_hierarchy_map={},
            tools_servers_map={},
        )

    def list_enabled_tool_names(self) -> list[str]:
        tool_names = []
        for tool_name, enabled in self.tools_enabled.items():
            server_name = self.tools_servers_map[tool_name]
            server_enabled = self.servers_enabled[server_name]
            if not server_enabled:
                continue
            if not enabled:
                continue
            tool_names.append(tool_name)
        return tool_names

    def disable_kit(self):
        self.enabled = False

    def enable_kit(self):
        self.enabled = True

    def disable_server(self, server_name: str):
        self.servers_enabled[server_name] = False

    def enable_server(self, server_name: str):
        self.servers_enabled[server_name] = True

    def disable_tool(self, tool_name: str):
        self.tools_enabled[tool_name] = False

    def enable_tool(self, tool_name: str):
        self.tools_enabled[tool_name] = True
