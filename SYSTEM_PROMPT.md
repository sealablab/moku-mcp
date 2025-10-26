# MCP Server Implementation System Prompt

You are implementing a Model Context Protocol (MCP) server for Moku devices based on the provided IMPLEMENTATION_GUIDE.md.

## Context
- Project: moku-mcp - An MCP server for controlling Moku:Go FPGA test instruments
- Dependencies: mcp, moku, moku-models, loguru, zeroconf
- Architecture: Stateful session management with one active connection at a time
- Reference: The implementation guide at IMPLEMENTATION_GUIDE.md contains complete specifications

## Core Design Patterns

### 1. Session Management Pattern
Use an async context manager for safe session handling:

```python
# In src/moku_mcp/session.py
class MokuSession:
    """Context manager for automatic connection cleanup."""
    def __init__(self, device_id: str, force: bool = False):
        self.device_id = device_id
        self.force = force
        self.server = None

    async def __aenter__(self):
        self.server = MokuMCPServer.get_instance()  # Use singleton
        await self.server.attach_moku(self.device_id, self.force)
        return self.server

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.server and self.server.moku_instance:
            await self.server.release_moku()
```

This ensures devices are ALWAYS released, even on errors.

### 2. Singleton Server Pattern
The MokuMCPServer should be a singleton to maintain single connection state:

```python
class MokuMCPServer:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        if MokuMCPServer._instance is not None:
            raise RuntimeError("Use get_instance() instead")
        self.moku_instance = None
        self.connected_device = None
```

## Implementation Approach
1. Follow the guide's phases strictly (Phase 1-5 in Section 9)
2. Start with core tools before moving to configuration management
3. Use the exact patterns shown in the guide's code examples
4. Use the session context manager for any multi-step operations
5. Keep implementations simple - no premature optimization

## File Structure
```
src/moku_mcp/
├── __init__.py          # Package exports
├── server.py            # MokuMCPServer singleton class
├── tools.py             # MCP tool decorators and schemas
├── session.py           # MokuSession context manager
├── utils.py             # Cache utilities and helpers
└── __main__.py          # Entry point for stdio server
```

## Implementation Order

### Phase 0: Foundation (NEW - Do this first!)
1. Create `session.py` with MokuSession context manager
2. Create `server.py` with singleton MokuMCPServer class
3. Set up basic MCP app structure

### Phase 1: Core Tools
- discover_mokus() - Section 3.1
- attach_moku() - Section 3.2
- release_moku() - Section 3.3
- Device cache utilities - Section 4.2

### Phase 2-5: Follow guide as written

## Tool Implementation Pattern

For tools that require connection, use this pattern:

```python
@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    server = MokuMCPServer.get_instance()

    # Tools that DON'T require connection
    if name == "discover_mokus":
        result = await server.discover_mokus(**arguments)
        return [TextContent(type="text", text=json.dumps(result))]

    # Tools that DO require connection (check state)
    if name == "push_config":
        if not server.moku_instance:
            error = {
                "status": "error",
                "message": "Not connected to any device",
                "suggestion": "Call attach_moku first"
            }
            return [TextContent(type="text", text=json.dumps(error))]

        result = await server.push_config(**arguments)
        return [TextContent(type="text", text=json.dumps(result))]
```

## Error Response Format (Section 5)
Always return structured errors:
```python
{
    "status": "error",
    "message": "Human-readable error description",
    "suggestion": "Actionable next step for user",
    "details": {...}  # Optional technical details
}
```

## Code Style Guidelines
- Use async/await for all MCP tool handlers
- Type hints for all function parameters and returns
- Docstrings matching the guide's format (Args, Returns sections)
- Use loguru for logging as shown in Section 10.3
- Handle "not connected" state gracefully in every tool

## Key Constraints
1. NO persistent state except device cache (~/.moku-mcp/device_cache.json)
2. One active moku_instance at a time (singleton pattern enforces this)
3. Platform ID is always 2 for Moku:Go
4. Use MokuConfig from moku_models for all configurations
5. Context manager ensures cleanup on all exit paths

## Testing Approach
- Test context manager cleanup with mock errors:
  ```python
  async def test_session_cleanup_on_error():
      with patch('moku_mcp.server.MokuMCPServer') as mock_server:
          with pytest.raises(ValueError):
              async with MokuSession("192.168.1.100") as moku:
                  raise ValueError("Simulated error")

          # Verify release was called despite error
          mock_server.get_instance().release_moku.assert_called_once()
  ```
- Use mock Moku objects for unit tests (Section 6.3)
- Test singleton pattern prevents multiple instances

## Example: Using Context Manager in Complex Operations

When implementing tools that do multiple operations:

```python
async def deploy_and_verify(device_id: str, config: dict):
    """Example of context manager usage in a complex operation."""
    async with MokuSession(device_id) as moku:
        # All these operations are protected by automatic cleanup
        deploy_result = await moku.push_config(config)
        verify_result = await moku.get_config()
        slots_result = await moku.list_slots()

        return {
            "deployed": deploy_result,
            "verified": verify_result,
            "slots": slots_result
        }
    # Device automatically released here, even if any operation failed
```

## Reference Patterns
When implementing, refer to:
- tools/moku_go.py for CLI patterns (mentioned throughout guide)
- Section 8.2 for Moku API usage patterns
- Section 10 for common patterns and best practices

Start with Phase 0 (foundation with context manager), then proceed to Phase 1 tools.