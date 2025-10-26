"""
Moku MCP Server Implementation

Skeleton structure for MCP server. See IMPLEMENTATION_GUIDE.md for details.
"""

import asyncio
from typing import Optional
from datetime import datetime, timezone

from loguru import logger
from moku_models import MokuConfig, MokuDeviceInfo
from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf


class MokuMCPServer:
    """
    MCP server for Moku device control (Singleton Pattern).

    Session Model:
    - attach(device_id) → Connects and maintains ownership
    - detach() → Releases ownership (allows handoff to other clients)

    Tools:
    - discover_mokus() → List available devices on network
    - attach_moku(device_id) → Connect and assume ownership
    - release_moku() → Disconnect and release ownership
    - push_config(config: MokuConfig) → Deploy configuration
    - get_config() → Retrieve current configuration
    - set_routing(connections: list) → Configure MCC routing
    - get_device_info() → Query device metadata
    - list_slots() → Show configured slots

    Implementation: See IMPLEMENTATION_GUIDE.md
    """

    _instance = None

    @classmethod
    def get_instance(cls):
        """
        Get singleton instance of MokuMCPServer.

        Returns:
            The single MokuMCPServer instance
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        """
        Initialize MCP server (stateless at start).

        Raises:
            RuntimeError: If attempting to create multiple instances
        """
        if MokuMCPServer._instance is not None:
            raise RuntimeError("Use get_instance() instead of direct instantiation")

        self.connected_device: Optional[str] = None
        self.moku_instance = None
        self.last_config: Optional[MokuConfig] = None  # Cache for get_config()
        logger.info("MokuMCPServer singleton initialized")

    async def discover_mokus(self, timeout: int = 2):
        """
        Discover Moku devices on network via zeroconf.

        Args:
            timeout: Discovery timeout in seconds (default: 2)

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

        Implementation: See IMPLEMENTATION_GUIDE.md Section 3.1
        """
        from moku import Moku
        from .utils import update_cache_with_device

        discovered = []
        zc = Zeroconf()

        def on_service_change(zeroconf, service_type, name, state_change):
            """Handle zeroconf service discovery events."""
            if state_change == ServiceStateChange.Added:
                info = zeroconf.get_service_info(service_type, name)
                if info:
                    # Extract IPv4 address
                    addresses = info.parsed_addresses()
                    ipv4 = [addr for addr in addresses if ":" not in addr]
                    ip = ipv4[0] if ipv4 else addresses[0] if addresses else None

                    if ip:
                        device = MokuDeviceInfo(
                            ip=ip,
                            port=info.port if info.port else 80,
                            zeroconf_name=name,
                            last_seen=datetime.now(timezone.utc).isoformat(),
                        )
                        discovered.append(device)
                        logger.info(f"Discovered device at {ip}:{info.port}")

        # Start discovery
        browser = ServiceBrowser(zc, "_moku._tcp.local.", handlers=[on_service_change])

        # Wait for discovery
        await asyncio.sleep(timeout)

        # Close zeroconf
        zc.close()

        # Enrich with metadata (name, serial) via Moku API
        for device in discovered:
            try:
                moku = Moku(ip=device.ip, force_connect=False, connect_timeout=5)
                device.canonical_name = moku.name()
                device.serial_number = moku.serial_number()
                moku.relinquish_ownership()

                # Update cache with enriched info
                update_cache_with_device(
                    ip=device.ip,
                    name=device.canonical_name,
                    serial=device.serial_number,
                    port=device.port,
                )

                logger.info(
                    f"Enriched device: {device.canonical_name} ({device.serial_number}) at {device.ip}"
                )
            except Exception as e:
                logger.warning(f"Could not get metadata for {device.ip}: {e}")

        result = {"devices": [d.model_dump() for d in discovered], "count": len(discovered)}

        logger.info(f"Discovery complete: found {len(discovered)} devices")
        return result

    async def attach_moku(self, device_id: str, force: bool = False):
        """
        Connect to Moku device and assume ownership.

        Args:
            device_id: IP address, name, or serial number
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

        Implementation: See IMPLEMENTATION_GUIDE.md Section 3.2
        """
        from moku.instruments import MultiInstrument
        from .utils import resolve_device_identifier, load_device_cache

        # Check if already connected
        if self.moku_instance:
            if self.connected_device == device_id:
                return {
                    "status": "already_connected",
                    "message": f"Already connected to {device_id}",
                    "device": {"ip": self.connected_device, "platform": "Moku:Go"},
                }
            else:
                return {
                    "status": "error",
                    "message": f"Already connected to {self.connected_device}. Release first.",
                    "suggestion": "Call release_moku() before connecting to a different device",
                }

        # Resolve device_id to IP
        ip = resolve_device_identifier(device_id)
        if not ip:
            # If not in cache, check if it's a valid IP
            if "." in device_id and device_id.replace(".", "").isdigit():
                ip = device_id
            else:
                return {
                    "status": "error",
                    "message": f"Device '{device_id}' not found in cache",
                    "suggestion": "Run discover_mokus() first to find devices",
                }

        # Try to connect (platform_id=2 for Moku:Go)
        try:
            logger.info(f"Attempting to connect to {ip} (force={force})")
            self.moku_instance = MultiInstrument(ip, platform_id=2, force_connect=force)
            self.connected_device = ip

            # Get device info from cache
            cache = load_device_cache()
            device_info = cache.find_by_ip(ip)

            logger.info(f"Successfully connected to Moku at {ip}")

            return {
                "status": "connected",
                "device": {
                    "ip": ip,
                    "name": device_info.canonical_name if device_info else "Unknown",
                    "serial": device_info.serial_number if device_info else "Unknown",
                    "platform": "Moku:Go",
                },
            }

        except ConnectionError as e:
            logger.error(f"Connection failed: {e}")
            return {
                "status": "error",
                "message": f"Could not connect to {ip}. Device may be offline or owned by another client.",
                "suggestion": "Try with force=True to take ownership, or wait for current owner to disconnect.",
                "details": str(e),
            }
        except Exception as e:
            logger.error(f"Unexpected error connecting to {ip}: {e}")
            self.moku_instance = None
            self.connected_device = None
            return {
                "status": "error",
                "message": f"Failed to connect to {ip}",
                "details": str(e),
            }

    async def release_moku(self):
        """
        Disconnect from Moku and release ownership.

        Returns:
            {
                "status": "disconnected",
                "device": "192.168.1.100"
            }

        Implementation: See IMPLEMENTATION_GUIDE.md Section 3.3
        """
        if not self.moku_instance:
            return {
                "status": "not_connected",
                "message": "No active connection to release",
            }

        try:
            # Store device info before releasing
            device = self.connected_device

            # Release ownership
            self.moku_instance.relinquish_ownership()

            # Clear internal state
            self.moku_instance = None
            self.connected_device = None
            self.last_config = None

            logger.info(f"Released Moku at {device}")

            return {"status": "disconnected", "device": device}

        except Exception as e:
            logger.error(f"Failed to release Moku: {e}")
            # Clear state anyway to avoid stuck connections
            self.moku_instance = None
            self.connected_device = None
            self.last_config = None
            return {
                "status": "error",
                "message": "Error releasing device, but cleared internal state",
                "details": str(e),
            }

    async def push_config(self, config_dict: dict):
        """
        Deploy MokuConfig to connected device.

        Args:
            config_dict: MokuConfig serialized as dict

        Returns:
            {
                "status": "deployed",
                "slots_configured": [1, 2],
                "routing_configured": True
            }

        Implementation: See IMPLEMENTATION_GUIDE.md Section 3.4
        """
        from moku.instruments import CloudCompile, Oscilloscope
        from pydantic import ValidationError

        if not self.moku_instance:
            return {
                "status": "error",
                "message": "Not connected to any device",
                "suggestion": "Call attach_moku first",
            }

        # Validate and parse config
        try:
            config = MokuConfig.model_validate(config_dict)
        except ValidationError as e:
            logger.error(f"Invalid config: {e}")
            return {"status": "error", "message": "Invalid MokuConfig", "errors": e.errors()}

        # Validate routing
        errors = config.validate_routing()
        if errors:
            return {
                "status": "error",
                "message": "Invalid routing configuration",
                "errors": errors,
            }

        deployed_slots = []

        # Deploy instruments to slots
        for slot_num, slot_config in config.slots.items():
            try:
                if slot_config.instrument == "CloudCompile":
                    if not slot_config.bitstream:
                        logger.warning(f"Slot {slot_num}: No bitstream specified")
                        continue

                    logger.info(f"Deploying CloudCompile to slot {slot_num}")
                    self.moku_instance.set_instrument(
                        slot_num, CloudCompile, bitstream=slot_config.bitstream
                    )

                    # Apply control registers if specified
                    if slot_config.control_registers:
                        cc = self.moku_instance.get_instrument(slot_num)
                        for reg, value in slot_config.control_registers.items():
                            cc.write_register(reg, value)
                            logger.debug(f"Slot {slot_num}: Set register {reg} = {value:#x}")

                    deployed_slots.append(slot_num)
                    logger.info(f"Successfully deployed CloudCompile to slot {slot_num}")

                elif slot_config.instrument == "Oscilloscope":
                    logger.info(f"Deploying Oscilloscope to slot {slot_num}")
                    osc = self.moku_instance.set_instrument(slot_num, Oscilloscope)

                    # Apply settings if specified
                    if slot_config.settings and "timebase" in slot_config.settings:
                        osc.set_timebase(*slot_config.settings["timebase"])
                        logger.debug(f"Slot {slot_num}: Set timebase {slot_config.settings['timebase']}")

                    deployed_slots.append(slot_num)
                    logger.info(f"Successfully deployed Oscilloscope to slot {slot_num}")

                else:
                    logger.warning(
                        f"Slot {slot_num}: Instrument '{slot_config.instrument}' not supported yet"
                    )

            except Exception as e:
                logger.error(f"Failed to deploy slot {slot_num}: {e}")
                return {
                    "status": "error",
                    "message": f"Failed to deploy instrument to slot {slot_num}",
                    "details": str(e),
                    "slots_deployed": deployed_slots,
                }

        # Configure routing
        routing_configured = False
        if config.routing:
            try:
                # Convert routing to dict format expected by Moku API
                connections = []
                for conn in config.routing:
                    connections.append(
                        {"source": conn.source, "destination": conn.destination}
                    )

                self.moku_instance.set_connections(connections)
                routing_configured = True
                logger.info(f"Configured {len(connections)} routing connections")

            except Exception as e:
                logger.error(f"Failed to configure routing: {e}")
                return {
                    "status": "partial_success",
                    "message": "Instruments deployed but routing failed",
                    "slots_configured": deployed_slots,
                    "routing_error": str(e),
                }

        # Cache the config for get_config()
        self.last_config = config

        return {
            "status": "deployed",
            "slots_configured": deployed_slots,
            "routing_configured": routing_configured,
        }

    async def get_config(self):
        """
        Retrieve current device configuration.

        Returns:
            {
                "platform": {...},
                "slots": {...},
                "routing": [...]
            }

        Implementation: See IMPLEMENTATION_GUIDE.md Section 3.5
        """
        from moku_models import MokuConfig, SlotConfig, MOKU_GO_PLATFORM

        if not self.moku_instance:
            return {
                "status": "error",
                "message": "Not connected to any device",
                "suggestion": "Call attach_moku first",
            }

        # If we have a cached config from push_config, use it
        if self.last_config:
            logger.info("Returning cached configuration")
            return self.last_config.model_dump()

        # Otherwise, try to reconstruct config from device state
        # NOTE: The Moku API may not provide full config retrieval
        logger.info("Reconstructing config from device state (best effort)")

        slots = {}

        # Query each slot (1-4 for Moku:Go)
        for slot_num in range(1, 5):
            try:
                instrument = self.moku_instance.get_instrument(slot_num)
                if instrument:
                    slots[slot_num] = SlotConfig(
                        instrument=instrument.__class__.__name__,
                        settings={},  # TODO: Extract settings from instrument if API supports
                    )
                    logger.debug(f"Slot {slot_num}: Found {instrument.__class__.__name__}")
            except Exception:
                # Slot not configured or error accessing it
                pass

        # Routing is harder to query - the Moku API doesn't provide a way to retrieve it
        # We can only return what we cached during push_config
        routing = []
        if self.last_config and self.last_config.routing:
            routing = self.last_config.routing

        # Build config object
        platform_config = MOKU_GO_PLATFORM.model_copy(
            update={"ip_address": self.connected_device}
        )

        config = MokuConfig(platform=platform_config, slots=slots, routing=routing)

        return config.model_dump()

    async def set_routing(self, connections: list):
        """
        Configure MCC signal routing.

        Args:
            connections: List of {"source": "...", "destination": "..."} dicts

        Returns:
            {
                "status": "configured",
                "connections_count": 2
            }

        Implementation: See IMPLEMENTATION_GUIDE.md Section 3.6
        """
        from moku_models import MokuConnection
        from pydantic import ValidationError

        if not self.moku_instance:
            return {
                "status": "error",
                "message": "Not connected to any device",
                "suggestion": "Call attach_moku first",
            }

        # Validate connections
        try:
            parsed_connections = [MokuConnection(**conn) for conn in connections]
        except ValidationError as e:
            logger.error(f"Invalid connection format: {e}")
            return {
                "status": "error",
                "message": "Invalid connection format",
                "errors": e.errors(),
            }

        # Apply to hardware
        try:
            self.moku_instance.set_connections(connections)
            logger.info(f"Configured {len(connections)} routing connections")

            # Update cached config if we have one
            if self.last_config:
                self.last_config.routing = parsed_connections

            return {"status": "configured", "connections_count": len(connections)}

        except Exception as e:
            logger.error(f"Failed to configure routing: {e}")
            return {
                "status": "error",
                "message": "Failed to configure routing",
                "details": str(e),
            }

    async def get_device_info(self):
        """
        Query device metadata (name, serial, IP, etc.).

        Returns:
            {
                "ip": "192.168.1.100",
                "name": "Lilo",
                "serial": "MG106B",
                "platform": "Moku:Go",
                "connected": true
            }

        Implementation: See IMPLEMENTATION_GUIDE.md Section 3.7
        """
        from moku import Moku

        if not self.moku_instance:
            return {
                "status": "error",
                "message": "Not connected to any device",
                "suggestion": "Call attach_moku first",
            }

        try:
            # Query via Moku API
            # Create a temporary Moku instance to query metadata
            # (We need this because MultiInstrument doesn't expose these methods directly)
            temp_moku = Moku(ip=self.connected_device, force_connect=False, connect_timeout=5)

            try:
                name = temp_moku.name()
                serial = temp_moku.serial_number()
            finally:
                # Always release ownership on the temp connection
                temp_moku.relinquish_ownership()

            info = {
                "ip": self.connected_device,
                "name": name,
                "serial": serial,
                "platform": "Moku:Go",  # Inferred from platform_id=2
                "connected": True,
            }

            logger.info(f"Device info: {name} ({serial}) at {self.connected_device}")
            return info

        except Exception as e:
            logger.error(f"Failed to query device info: {e}")
            return {
                "status": "error",
                "message": "Failed to query device information",
                "details": str(e),
            }

    async def list_slots(self):
        """
        List configured instrument slots.

        Returns:
            {
                "slots": {
                    "1": {"instrument": "CloudCompile", "configured": true},
                    "2": {"instrument": "Oscilloscope", "configured": true},
                    "3": {"configured": false},
                    "4": {"configured": false}
                }
            }

        Implementation: See IMPLEMENTATION_GUIDE.md Section 3.8
        """
        if not self.moku_instance:
            return {
                "status": "error",
                "message": "Not connected to any device",
                "suggestion": "Call attach_moku first",
            }

        slots = {}

        # Query each slot (1-4 for Moku:Go)
        for slot_num in range(1, 5):
            try:
                instrument = self.moku_instance.get_instrument(slot_num)
                if instrument:
                    slots[str(slot_num)] = {
                        "instrument": instrument.__class__.__name__,
                        "configured": True,
                    }
                    logger.debug(f"Slot {slot_num}: {instrument.__class__.__name__}")
                else:
                    slots[str(slot_num)] = {"configured": False}
                    logger.debug(f"Slot {slot_num}: Empty")
            except Exception as e:
                # Slot not configured or error accessing it
                slots[str(slot_num)] = {"configured": False}
                logger.debug(f"Slot {slot_num}: Not configured or error: {e}")

        logger.info(f"Slot status: {sum(1 for s in slots.values() if s.get('configured'))} configured")
        return {"slots": slots}
