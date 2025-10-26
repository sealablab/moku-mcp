# Moku MCP Server Implementation Guide

Complete guide for implementing the Moku MCP server.

**Status**: Skeleton complete, awaiting implementation
**Prerequisites**: Knowledge of `moku-models` and `moku` 1st party Python libraries

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [MCP SDK Setup](#2-mcp-sdk-setup)
3. [Tool Implementation](#3-tool-implementation)
4. [State Management](#4-state-management)
5. [Error Handling](#5-error-handling)
6. [Testing Strategy](#6-testing-strategy)
7. [Deployment](#7-deployment)
8. [Reference Patterns](#8-reference-patterns)

---

## 1. Architecture Overview

### 1.1 Design Philosophy

**Stateful Session Management**:
- One active connection at a time (stored in `self.moku_instance`)
- Attach/Detach pattern for explicit ownership control
- Graceful handoff: iPad ↔ CLI ↔ LLM workflows supported

**MokuConfig-Driven**:
- All configurations use `moku_models.MokuConfig`
- Type-safe validation via Pydantic
- Single source of truth for deployment specs

**Minimal Dependencies**:
- Core: `mcp`, `moku`, `moku-models`
- Logging: `loguru` only
- No CLI frameworks (typer/rich) - pure MCP protocol

### 1.2 Component Structure

```
moku-mcp/
├── src/moku_mcp/
│   ├── __init__.py          # Package exports
│   ├── server.py            # MokuMCPServer class (main implementation)
│   ├── tools.py             # MCP tool decorators and schemas
│   ├── session.py           # Connection state management
│   └── utils.py             # Helpers (discovery, validation)
├── tests/
│   ├── test_discovery.py    # Device discovery tests
│   ├── test_session.py      # Attach/detach tests
│   └── test_config.py       # MokuConfig deployment tests
├── pyproject.toml
├── README.md
└── IMPLEMENTATION_GUIDE.md  # This file
```

---

## 2. MCP SDK Setup

### 2.1 MCP Server Initialization

The MCP SDK provides server infrastructure. Here's the recommended pattern:

```python
# src/moku_mcp/server.py
from mcp.server import Server
from mcp.types import Tool, TextContent
from loguru import logger

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
                        "description": "Discovery timeout in seconds (default: 2)"
                    }
                }
            }
        ),
        # ... (see Section 3 for all 8 tools)
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Route tool calls to appropriate handlers."""
    server = MokuMCPServer()  # Or use singleton pattern

    if name == "discover_mokus":
        result = await server.discover_mokus(**arguments)
        return [TextContent(type="text", text=str(result))]
    # ... (dispatch to other tools)
```

### 2.2 Running the Server

```python
# src/moku_mcp/__main__.py
import asyncio
from mcp.server.stdio import stdio_server
from .server import app

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

**Usage**:
```bash
# Run server via stdio (MCP standard)
python -m moku_mcp

# Or with uv
uv run python -m moku_mcp
```

---

## 3. Tool Implementation

### 3.1 discover_mokus()

**Purpose**: Find Moku devices on network via zeroconf

**Reference**: `tools/moku_go.py:120-189` (discover command)

**Implementation**:

```python
async def discover_mokus(self, timeout: int = 2):
    """
    Discover Moku devices on network.

    Args:
        timeout: Discovery timeout in seconds

    Returns:
        {
            "devices": [
                {
                    "ip": "192.168.1.100",
                    "name": "Lilo",
                    "serial": "MG106B",
                    "port": 80,
                    "last_seen": "2025-10-25T20:00:00Z"
                }
            ],
            "count": 1
        }
    """
    from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
    from moku_models import MokuDeviceInfo

    discovered = []
    zc = Zeroconf()

    def on_service_change(zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info:
                # Extract IPv4 address
                addresses = info.parsed_addresses()
                ipv4 = [addr for addr in addresses if ':' not in addr]
                ip = ipv4[0] if ipv4 else addresses[0]

                device = MokuDeviceInfo(
                    ip=ip,
                    port=info.port,
                    zeroconf_name=name,
                    last_seen=datetime.now(timezone.utc).isoformat()
                )
                discovered.append(device)

    browser = ServiceBrowser(zc, "_moku._tcp.local.", handlers=[on_service_change])
    await asyncio.sleep(timeout)
    zc.close()

    # Enrich with metadata (name, serial) via Moku API
    from moku import Moku
    for device in discovered:
        try:
            moku = Moku(ip=device.ip, force_connect=False, connect_timeout=5)
            device.canonical_name = moku.name()
            device.serial_number = moku.serial_number()
            moku.relinquish_ownership()
        except Exception as e:
            logger.warning(f"Could not get metadata for {device.ip}: {e}")

    return {
        "devices": [d.model_dump() for d in discovered],
        "count": len(discovered)
    }
```

---

### 3.2 attach_moku(device_id)

**Purpose**: Connect to Moku device and assume ownership

**Reference**: `tools/moku_go.py:218-295` (deploy command, connection logic)

**Implementation**:

```python
async def attach_moku(self, device_id: str, force: bool = False):
    """
    Attach to Moku device.

    Args:
        device_id: IP address, device name, or serial number
        force: Force connection even if owned by another client

    Returns:
        {
            "status": "connected",
            "device": {
                "ip": "192.168.1.100",
                "name": "Lilo",
                "serial": "MG106B",
                "platform": "Moku:Go"
            }
        }
    """
    from moku.instruments import MultiInstrument
    from moku_models import MokuDeviceCache

    # Resolve device_id to IP (check cache or use directly)
    # (Cache loading logic from moku_go.py:73-93)
    cache = load_device_cache()  # TODO: Implement cache loading
    device_info = cache.find_by_identifier(device_id)

    if device_info:
        ip = device_info.ip
    elif '.' in device_id and device_id.replace('.', '').isdigit():
        ip = device_id
    else:
        raise ValueError(f"Device '{device_id}' not found. Run discover_mokus first.")

    # Connect (platform_id=2 for Moku:Go)
    try:
        self.moku_instance = MultiInstrument(ip, platform_id=2, force_connect=force)
        self.connected_device = ip

        logger.info(f"Connected to Moku at {ip}")

        return {
            "status": "connected",
            "device": {
                "ip": ip,
                "name": device_info.canonical_name if device_info else "Unknown",
                "serial": device_info.serial_number if device_info else "Unknown",
                "platform": "Moku:Go"
            }
        }
    except Exception as e:
        logger.error(f"Failed to connect to {ip}: {e}")
        raise
```

---

### 3.3 release_moku()

**Purpose**: Disconnect and release ownership

**Reference**: `tools/moku_go.py:352` (relinquish_ownership)

**Implementation**:

```python
async def release_moku(self):
    """
    Release Moku ownership.

    Returns:
        {
            "status": "disconnected",
            "device": "192.168.1.100"
        }
    """
    if not self.moku_instance:
        return {"status": "not_connected"}

    try:
        self.moku_instance.relinquish_ownership()
        device = self.connected_device
        self.moku_instance = None
        self.connected_device = None

        logger.info(f"Released Moku at {device}")

        return {
            "status": "disconnected",
            "device": device
        }
    except Exception as e:
        logger.error(f"Failed to release Moku: {e}")
        raise
```

---

### 3.4 push_config(config_dict)

**Purpose**: Deploy MokuConfig to connected device

**Reference**: `tools/moku_go.py:298-340` (instrument deployment and routing)

**Implementation**:

```python
async def push_config(self, config_dict: dict):
    """
    Deploy MokuConfig to device.

    Args:
        config_dict: MokuConfig serialized as dict

    Returns:
        {
            "status": "deployed",
            "slots_configured": [1, 2],
            "routing_configured": True
        }
    """
    from moku_models import MokuConfig
    from moku.instruments import CloudCompile, Oscilloscope

    if not self.moku_instance:
        raise RuntimeError("Not connected. Call attach_moku first.")

    # Validate and parse config
    config = MokuConfig.model_validate(config_dict)

    # Validate routing
    errors = config.validate_routing()
    if errors:
        raise ValueError(f"Invalid routing: {errors}")

    deployed_slots = []

    # Deploy instruments to slots
    for slot_num, slot_config in config.slots.items():
        if slot_config.instrument == 'CloudCompile':
            if not slot_config.bitstream:
                logger.warning(f"Slot {slot_num}: No bitstream specified")
                continue

            self.moku_instance.set_instrument(
                slot_num,
                CloudCompile,
                bitstream=slot_config.bitstream
            )

            # Apply control registers if specified
            if slot_config.control_registers:
                cc = self.moku_instance.get_instrument(slot_num)
                for reg, value in slot_config.control_registers.items():
                    cc.write_register(reg, value)

            deployed_slots.append(slot_num)
            logger.info(f"Deployed CloudCompile to slot {slot_num}")

        elif slot_config.instrument == 'Oscilloscope':
            osc = self.moku_instance.set_instrument(slot_num, Oscilloscope)

            # Apply settings
            if 'timebase' in slot_config.settings:
                osc.set_timebase(*slot_config.settings['timebase'])

            deployed_slots.append(slot_num)
            logger.info(f"Deployed Oscilloscope to slot {slot_num}")

        else:
            logger.warning(f"Slot {slot_num}: {slot_config.instrument} not supported")

    # Configure routing
    routing_configured = False
    if config.routing:
        connections = [conn.to_dict() for conn in config.routing]
        self.moku_instance.set_connections(connections)
        routing_configured = True
        logger.info(f"Configured {len(connections)} routing connections")

    return {
        "status": "deployed",
        "slots_configured": deployed_slots,
        "routing_configured": routing_configured
    }
```

---

### 3.5 get_config()

**Purpose**: Retrieve current device configuration

**Implementation**:

```python
async def get_config(self):
    """
    Get current device configuration.

    Returns:
        {
            "platform": {...},
            "slots": {...},
            "routing": [...]
        }
    """
    if not self.moku_instance:
        raise RuntimeError("Not connected. Call attach_moku first.")

    # Query current state from Moku API
    # NOTE: Moku API may not provide full config retrieval
    # This is a best-effort reconstruction

    from moku_models import MokuConfig, SlotConfig, MOKU_GO_PLATFORM

    slots = {}
    # Query each slot (1-4 for Moku:Go)
    for slot_num in range(1, 5):
        try:
            instrument = self.moku_instance.get_instrument(slot_num)
            if instrument:
                slots[slot_num] = SlotConfig(
                    instrument=instrument.__class__.__name__,
                    settings={}  # TODO: Extract settings from instrument
                )
        except Exception:
            pass  # Slot not configured

    # Routing is harder to query - may need to be cached during push_config
    routing = []  # TODO: Retrieve if API supports

    config = MokuConfig(
        platform=MOKU_GO_PLATFORM.model_copy(update={"ip_address": self.connected_device}),
        slots=slots,
        routing=routing
    )

    return config.model_dump()
```

**NOTE**: The Moku API may not support full config retrieval. Consider caching the last `push_config()` payload for accurate `get_config()` responses.

---

### 3.6 set_routing(connections)

**Purpose**: Configure MCC signal routing

**Reference**: `tools/moku_go.py:331-339` (set_connections)

**Implementation**:

```python
async def set_routing(self, connections: list[dict]):
    """
    Configure signal routing.

    Args:
        connections: List of {"source": "...", "destination": "..."} dicts

    Returns:
        {
            "status": "configured",
            "connections_count": 2
        }
    """
    from moku_models import MokuConnection

    if not self.moku_instance:
        raise RuntimeError("Not connected. Call attach_moku first.")

    # Validate connections
    parsed_connections = [MokuConnection(**conn) for conn in connections]

    # Apply to hardware
    self.moku_instance.set_connections(connections)

    logger.info(f"Configured {len(connections)} routing connections")

    return {
        "status": "configured",
        "connections_count": len(connections)
    }
```

---

### 3.7 get_device_info()

**Purpose**: Query device metadata

**Reference**: `tools/moku_go.py:160-166` (metadata retrieval)

**Implementation**:

```python
async def get_device_info(self):
    """
    Get device metadata.

    Returns:
        {
            "ip": "192.168.1.100",
            "name": "Lilo",
            "serial": "MG106B",
            "platform": "Moku:Go",
            "connected": true
        }
    """
    if not self.moku_instance:
        raise RuntimeError("Not connected. Call attach_moku first.")

    from moku import Moku

    # Query via Moku API
    temp_moku = Moku(ip=self.connected_device, force_connect=False)
    info = {
        "ip": self.connected_device,
        "name": temp_moku.name(),
        "serial": temp_moku.serial_number(),
        "platform": "Moku:Go",  # Infer from platform_id
        "connected": True
    }
    temp_moku.relinquish_ownership()

    return info
```

---

### 3.8 list_slots()

**Purpose**: List configured instrument slots

**Implementation**:

```python
async def list_slots(self):
    """
    List configured slots.

    Returns:
        {
            "slots": {
                "1": {"instrument": "CloudCompile", "configured": true},
                "2": {"instrument": "Oscilloscope", "configured": true},
                "3": {"configured": false},
                "4": {"configured": false}
            }
        }
    """
    if not self.moku_instance:
        raise RuntimeError("Not connected. Call attach_moku first.")

    slots = {}

    for slot_num in range(1, 5):
        try:
            instrument = self.moku_instance.get_instrument(slot_num)
            if instrument:
                slots[str(slot_num)] = {
                    "instrument": instrument.__class__.__name__,
                    "configured": True
                }
            else:
                slots[str(slot_num)] = {"configured": False}
        except Exception:
            slots[str(slot_num)] = {"configured": False}

    return {"slots": slots}
```

---

## 4. State Management

### 4.1 Session Persistence

**Recommended Approach**: In-memory only (no persistent state)

```python
class MokuMCPServer:
    def __init__(self):
        self.connected_device: Optional[str] = None
        self.moku_instance = None  # MultiInstrument instance
        self.last_config: Optional[MokuConfig] = None  # Cache for get_config()
```

**Why No Persistence?**:
- Moku connections are ephemeral
- Ownership can be taken by other clients (iPad, CLI)
- Stateless design simplifies error recovery

### 4.2 Device Cache

**Location**: `~/.moku-mcp/device_cache.json`

**Purpose**: Speed up device name → IP resolution

**Implementation**:

```python
# src/moku_mcp/utils.py
from pathlib import Path
import json
from moku_models import MokuDeviceCache

CACHE_DIR = Path.home() / ".moku-mcp"
CACHE_FILE = CACHE_DIR / "device_cache.json"

def load_device_cache() -> MokuDeviceCache:
    """Load device cache from disk."""
    if not CACHE_FILE.exists():
        return MokuDeviceCache()

    with open(CACHE_FILE) as f:
        data = json.load(f)
    return MokuDeviceCache.from_cache_dict(data)

def save_device_cache(cache: MokuDeviceCache):
    """Save device cache to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache.to_cache_dict(), f, indent=2)
```

**Usage**: Update cache in `discover_mokus()` and `attach_moku()`.

---

## 5. Error Handling

### 5.1 Connection Errors

```python
try:
    self.moku_instance = MultiInstrument(ip, platform_id=2, force_connect=force)
except ConnectionError as e:
    logger.error(f"Connection failed: {e}")
    return {
        "status": "error",
        "message": f"Could not connect to {ip}. Device may be offline or owned by another client.",
        "suggestion": "Try with force=True to take ownership, or wait for current owner to disconnect."
    }
```

### 5.2 Validation Errors

```python
try:
    config = MokuConfig.model_validate(config_dict)
except ValidationError as e:
    logger.error(f"Invalid config: {e}")
    return {
        "status": "error",
        "message": "Invalid MokuConfig",
        "errors": e.errors()
    }
```

### 5.3 State Errors

```python
if not self.moku_instance:
    return {
        "status": "error",
        "message": "Not connected to any device. Call attach_moku first."
    }
```

---

## 6. Testing Strategy

### 6.1 Unit Tests

**Test Discovery**:
```python
# tests/test_discovery.py
import pytest
from moku_mcp import MokuMCPServer

@pytest.mark.asyncio
async def test_discover_mokus():
    server = MokuMCPServer()
    result = await server.discover_mokus(timeout=2)

    assert "devices" in result
    assert "count" in result
    assert isinstance(result["devices"], list)
```

**Test Attach/Detach**:
```python
# tests/test_session.py
@pytest.mark.asyncio
async def test_attach_release_moku():
    server = MokuMCPServer()

    # Attach
    result = await server.attach_moku("192.168.1.100")
    assert result["status"] == "connected"
    assert server.connected_device == "192.168.1.100"

    # Release
    result = await server.release_moku()
    assert result["status"] == "disconnected"
    assert server.connected_device is None
```

### 6.2 Integration Tests

**Test with Real Hardware** (requires Moku:Go on network):

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_deployment_flow():
    server = MokuMCPServer()

    # Discover
    devices = await server.discover_mokus()
    assert devices["count"] > 0

    # Attach
    device_ip = devices["devices"][0]["ip"]
    await server.attach_moku(device_ip)

    # Push config
    config = {
        "platform": {...},
        "slots": {1: {"instrument": "CloudCompile", "bitstream": "test.tar"}},
        "routing": []
    }
    result = await server.push_config(config)
    assert result["status"] == "deployed"

    # Release
    await server.release_moku()
```

### 6.3 Mock Testing

For tests without hardware, mock the `moku` library:

```python
from unittest.mock import MagicMock, patch

@pytest.mark.asyncio
async def test_attach_moku_mocked():
    server = MokuMCPServer()

    with patch('moku.instruments.MultiInstrument') as mock_mi:
        mock_instance = MagicMock()
        mock_mi.return_value = mock_instance

        result = await server.attach_moku("192.168.1.100")

        assert result["status"] == "connected"
        mock_mi.assert_called_once_with("192.168.1.100", platform_id=2, force_connect=False)
```

---

## 7. Deployment

### 7.1 Running the MCP Server

**Standalone Mode** (stdio):
```bash
# Start server (listens on stdin/stdout)
uv run python -m moku_mcp
```

**Integration with Claude Desktop** (macOS example):

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "moku": {
      "command": "uv",
      "args": ["run", "python", "-m", "moku_mcp"],
      "cwd": "/path/to/moku-mcp"
    }
  }
}
```

### 7.2 Package Installation

**From GitHub**:
```bash
uv pip install git+https://github.com/sealablab/moku-mcp.git
```

**Local Development**:
```bash
cd /path/to/moku-mcp
uv pip install -e .
```

---

## 8. Reference Patterns

### 8.1 MokuConfig Usage

**Creating a Config**:
```python
from moku_models import MokuConfig, SlotConfig, MokuConnection, MOKU_GO_PLATFORM

config = MokuConfig(
    platform=MOKU_GO_PLATFORM,
    slots={
        1: SlotConfig(
            instrument='CloudCompile',
            bitstream='path/to/bitstream.tar',
            control_registers={0: 0xE0000000}  # MCC_READY + Enable + ClkEn
        )
    },
    routing=[
        MokuConnection(source='Input1', destination='Slot1InA'),
        MokuConnection(source='Slot1OutA', destination='Output1')
    ]
)
```

**Serialization**:
```python
# To dict (for JSON/MCP)
config_dict = config.model_dump()

# From dict
config = MokuConfig.model_validate(config_dict)

# Validation
errors = config.validate_routing()
if errors:
    print(f"Invalid routing: {errors}")
```

### 8.2 Moku API Patterns

**MultiInstrument Setup**:
```python
from moku.instruments import MultiInstrument, CloudCompile

# Connect
moku = MultiInstrument("192.168.1.100", platform_id=2, force_connect=False)

# Deploy instrument
moku.set_instrument(1, CloudCompile, bitstream="path/to/bitstream.tar")

# Get instrument reference
cc = moku.get_instrument(1)
cc.write_register(0, 0xE0000000)

# Configure routing
moku.set_connections([
    {"source": "Slot1OutA", "destination": "Output1"}
])

# Release ownership
moku.relinquish_ownership()
```

**Device Discovery** (zeroconf):
```python
from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf

zc = Zeroconf()

def on_service_change(zeroconf, service_type, name, state_change):
    if state_change == ServiceStateChange.Added:
        info = zeroconf.get_service_info(service_type, name)
        # Process info...

browser = ServiceBrowser(zc, "_moku._tcp.local.", handlers=[on_service_change])
time.sleep(2)  # Or asyncio.sleep in async context
zc.close()
```

---

## 9. Next Steps

### Phase 1: Core Tools
- [ ] Implement `discover_mokus()`
- [ ] Implement `attach_moku()` / `release_moku()`
- [ ] Implement device cache utilities

### Phase 2: Configuration Management
- [ ] Implement `push_config()`
- [ ] Implement `get_config()` (with caching)
- [ ] Implement `set_routing()`

### Phase 3: Metadata & Utilities
- [ ] Implement `get_device_info()`
- [ ] Implement `list_slots()`

### Phase 4: Testing & Refinement
- [ ] Write unit tests (with mocks)
- [ ] Write integration tests (with real hardware)
- [ ] Error handling improvements
- [ ] Logging enhancements

### Phase 5: Documentation & Deployment
- [ ] Update README with usage examples
- [ ] Create deployment guide for Claude Desktop
- [ ] Publish to PyPI (optional)

---

## 10. Common Patterns Reference

### 10.1 Async/Await Best Practices

All MCP tools must be `async`:

```python
# CORRECT
async def discover_mokus(self, timeout: int = 2):
    await asyncio.sleep(timeout)  # Use asyncio primitives
    return result

# INCORRECT
def discover_mokus(self, timeout: int = 2):  # Missing async!
    time.sleep(timeout)  # Blocking!
    return result
```

### 10.2 Error Response Format

Return structured errors for LLM consumption:

```python
return {
    "status": "error",
    "message": "Human-readable error description",
    "suggestion": "Actionable next step for user",
    "details": {...}  # Optional technical details
}
```

### 10.3 Logging Best Practices

Use `loguru` for structured logging:

```python
from loguru import logger

logger.info(f"Connected to Moku at {ip}")
logger.warning(f"Slot {slot_num}: No bitstream specified")
logger.error(f"Deployment failed: {e}")
logger.debug(f"Raw config: {config_dict}")
```

---

## 11. Troubleshooting

### Issue: "Device not found"
**Cause**: Device cache is stale or device is offline
**Solution**: Run `discover_mokus()` to refresh cache

### Issue: "Connection refused"
**Cause**: Device owned by another client (iPad, CLI)
**Solution**: Use `attach_moku(force=True)` or wait for current owner to release

### Issue: "Invalid routing"
**Cause**: MokuConfig validation failed
**Solution**: Check `config.validate_routing()` errors

### Issue: "Instrument deployment failed"
**Cause**: Bitstream file not found or incompatible
**Solution**: Verify bitstream path and platform compatibility

---

## 12. Additional Resources

**Documentation**:
- [moku-models README](https://github.com/sealablab/moku-models)
- [Moku API Docs](https://moku.com/api)
- [MCP SDK Docs](https://github.com/anthropics/mcp)

**Reference Implementations**:
- `tools/moku_go.py` - CLI deployment tool (volo_vhdl repo)
- `tests/moku_platform_simulator/` - Simulation backend patterns

**Support**:
- GitHub Issues: https://github.com/sealablab/moku-mcp/issues

---

**End of Implementation Guide**

Good luck implementing! 🚀
