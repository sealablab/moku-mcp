# moku-mcp

Model Context Protocol (MCP) server for Moku device control.

## Overview

This MCP server provides LLM-friendly tools for controlling Moku devices:

- **Device Discovery**: Find Moku devices on the network
- **Connection Management**: Attach/detach with graceful ownership handoff
- **Configuration Deployment**: Push `MokuConfig` models to hardware
- **Routing Control**: Configure MCC signal routing
- **Metadata Queries**: Get device info and slot status

## Architecture

**Session Model**: Stateful connection management
- `attach(device_id)` → Connect and maintain ownership
- `detach()` → Release ownership (allows iPad/CLI handoff)

**Graceful Handoff**: Supports common workflow where ownership moves between:
- Machine A (CLI) → iPad (GUI) → Machine B (LLM) → ...

**MokuConfig-Driven**: Uses `moku-models` package for type-safe configuration.

## Installation

```bash
# Clone repository
git clone https://github.com/sealablab/moku-mcp.git
cd moku-mcp

# Install with uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

## MCP Tools

### 1. discover_mokus()
Discover Moku devices on network via zeroconf.

**Returns**: List of devices with IP, name, serial number

### 2. attach_moku(device_id)
Connect to Moku device and assume ownership.

**Args**:
- `device_id` (str): IP address, device name, or serial number

**Returns**: Connection status and device metadata

### 3. release_moku()
Disconnect and release ownership.

**Returns**: Disconnect status

### 4. push_config(config)
Deploy MokuConfig to connected device.

**Args**:
- `config` (dict): MokuConfig serialized as dictionary

**Returns**: Deployment status

**Example**:
```python
config = {
    "platform": {...},
    "slots": {
        1: {
            "instrument": "CloudCompile",
            "bitstream": "path/to/bitstream.tar"
        }
    },
    "routing": [
        {"source": "Slot1OutA", "destination": "Output1"}
    ]
}
```

### 5. get_config()
Retrieve current device configuration.

**Returns**: MokuConfig as dict

### 6. set_routing(connections)
Configure MCC signal routing.

**Args**:
- `connections` (list): List of MokuConnection dicts

**Example**:
```python
connections = [
    {"source": "Input1", "destination": "Slot1InA"},
    {"source": "Slot1OutA", "destination": "Output1"}
]
```

### 7. get_device_info()
Query device metadata.

**Returns**: Dict with name, serial, IP, platform type

### 8. list_slots()
List configured instrument slots.

**Returns**: Dict of slot numbers to instrument info

## Implementation Status

🚧 **Skeleton Only** - See `IMPLEMENTATION_GUIDE.md` for implementation details.

All tool methods currently raise `NotImplementedError` with references to the implementation guide.

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests (when implemented)
pytest

# Format code
black src/
ruff check src/
```

## Dependencies

**1st Party**:
- `moku-models` - Pydantic models for Moku configuration
- `moku` - Official Moku hardware API

**3rd Party**:
- `mcp` - Model Context Protocol SDK
- `pydantic` - Data validation
- `loguru` - Logging

## Next Steps

See `IMPLEMENTATION_GUIDE.md` for:
- MCP SDK setup
- Tool implementation patterns
- Testing strategies
- Deployment workflows

## License

MIT License - see LICENSE file for details.
