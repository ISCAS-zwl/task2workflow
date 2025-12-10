import json
import pathlib

def load_mcp_tools(config_folder="mcp_servers"):
    tools = {}
    folder = pathlib.Path(config_folder)

    for file in folder.glob("*.json"):
        cfg = json.loads(file.read_text())
        server = cfg["server_name"]

        for tool in cfg["tools"]:
            tools[tool] = {
                "type": "mcp",
                "server": server,
                "description": cfg.get("description", tool)
            }

    return tools
