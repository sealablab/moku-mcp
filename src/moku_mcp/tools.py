"""
MCP Tool Definitions and Handlers

All MCP tools are registered and routed through this module.
"""

import json
from mcp.server import Server
from mcp.types import Tool, TextContent
from loguru import logger

from .server import MokuMCPServer

# Create the MCP app
app = Server("moku-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Register available MCP tools."""
    return [
        Tool(
            name="discover_mokus",
            description="Discover Moku devices on network via zeroconf",
            inputSchema={
                "type": "object",
                "properties": {
                    "timeout": {
                        "type": "number",
                        "description": "Discovery timeout in seconds (default: 2)",
                        "default": 2,
                    }
                },
            },
        ),
        Tool(
            name="attach_moku",
            description="Connect to Moku device and assume ownership",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "IP address, device name, or serial number",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Force connection even if owned by another client",
                        "default": False,
                    },
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="release_moku",
            description="Disconnect from Moku and release ownership",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="push_config",
            description="Deploy MokuConfig to connected device",
            inputSchema={
                "type": "object",
                "properties": {
                    "config_dict": {
                        "type": "object",
                        "description": "MokuConfig serialized as dict",
                    }
                },
                "required": ["config_dict"],
            },
        ),
        Tool(
            name="get_config",
            description="Retrieve current device configuration",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="set_routing",
            description="Configure MCC signal routing",
            inputSchema={
                "type": "object",
                "properties": {
                    "connections": {
                        "type": "array",
                        "description": "List of routing connections",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"},
                                "destination": {"type": "string"},
                            },
                            "required": ["source", "destination"],
                        },
                    }
                },
                "required": ["connections"],
            },
        ),
        Tool(
            name="get_device_info",
            description="Query device metadata (name, serial, IP, etc.)",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="list_slots",
            description="List configured instrument slots",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Route tool calls to appropriate handlers."""
    server = MokuMCPServer.get_instance()  # Use singleton pattern

    logger.info(f"Tool called: {name} with args: {arguments}")

    try:
        # Tools that DON'T require connection
        if name == "discover_mokus":
            result = await server.discover_mokus(**arguments)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "attach_moku":
            result = await server.attach_moku(**arguments)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "release_moku":
            result = await server.release_moku()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        # Tools that DO require connection (check state)
        elif name == "push_config":
            if not server.moku_instance:
                error = {
                    "status": "error",
                    "message": "Not connected to any device",
                    "suggestion": "Call attach_moku first",
                }
                return [TextContent(type="text", text=json.dumps(error, indent=2))]

            result = await server.push_config(**arguments)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_config":
            if not server.moku_instance:
                error = {
                    "status": "error",
                    "message": "Not connected to any device",
                    "suggestion": "Call attach_moku first",
                }
                return [TextContent(type="text", text=json.dumps(error, indent=2))]

            result = await server.get_config()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "set_routing":
            if not server.moku_instance:
                error = {
                    "status": "error",
                    "message": "Not connected to any device",
                    "suggestion": "Call attach_moku first",
                }
                return [TextContent(type="text", text=json.dumps(error, indent=2))]

            result = await server.set_routing(**arguments)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_device_info":
            if not server.moku_instance:
                error = {
                    "status": "error",
                    "message": "Not connected to any device",
                    "suggestion": "Call attach_moku first",
                }
                return [TextContent(type="text", text=json.dumps(error, indent=2))]

            result = await server.get_device_info()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "list_slots":
            if not server.moku_instance:
                error = {
                    "status": "error",
                    "message": "Not connected to any device",
                    "suggestion": "Call attach_moku first",
                }
                return [TextContent(type="text", text=json.dumps(error, indent=2))]

            result = await server.list_slots()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        else:
            error = {
                "status": "error",
                "message": f"Unknown tool: {name}",
                "available_tools": [
                    "discover_mokus",
                    "attach_moku",
                    "release_moku",
                    "push_config",
                    "get_config",
                    "set_routing",
                    "get_device_info",
                    "list_slots",
                ],
            }
            return [TextContent(type="text", text=json.dumps(error, indent=2))]

    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        error = {
            "status": "error",
            "message": str(e),
            "tool": name,
        }
        return [TextContent(type="text", text=json.dumps(error, indent=2))]