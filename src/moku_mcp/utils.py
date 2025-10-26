"""
Utility Functions

Device cache management and helper functions.
"""

import json
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from loguru import logger
from moku_models import MokuDeviceCache, MokuDeviceInfo

# Cache configuration
CACHE_DIR = Path.home() / ".moku-mcp"
CACHE_FILE = CACHE_DIR / "device_cache.json"


def load_device_cache() -> MokuDeviceCache:
    """
    Load device cache from disk.

    Returns:
        MokuDeviceCache instance (empty if cache doesn't exist)
    """
    if not CACHE_FILE.exists():
        logger.info("No device cache found, creating new one")
        return MokuDeviceCache()

    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        cache = MokuDeviceCache.from_cache_dict(data)
        logger.info(f"Loaded device cache with {len(cache.devices)} devices")
        return cache
    except Exception as e:
        logger.error(f"Failed to load device cache: {e}")
        return MokuDeviceCache()


def save_device_cache(cache: MokuDeviceCache) -> None:
    """
    Save device cache to disk.

    Args:
        cache: MokuDeviceCache to save
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache.to_cache_dict(), f, indent=2)
        logger.info(f"Saved device cache with {len(cache.devices)} devices")
    except Exception as e:
        logger.error(f"Failed to save device cache: {e}")


def update_cache_with_device(
    ip: str, name: Optional[str] = None, serial: Optional[str] = None, port: int = 80
) -> None:
    """
    Update cache with a single device.

    Args:
        ip: Device IP address
        name: Device canonical name
        serial: Device serial number
        port: Device port (default: 80)
    """
    cache = load_device_cache()

    # Find existing device or create new
    device = cache.find_by_ip(ip)
    if not device:
        device = MokuDeviceInfo(
            ip=ip,
            port=port,
            last_seen=datetime.now(timezone.utc).isoformat(),
        )
        cache.devices.append(device)

    # Update fields
    device.last_seen = datetime.now(timezone.utc).isoformat()
    if name:
        device.canonical_name = name
    if serial:
        device.serial_number = serial

    save_device_cache(cache)


def resolve_device_identifier(device_id: str) -> Optional[str]:
    """
    Resolve device identifier to IP address.

    Args:
        device_id: IP address, device name, or serial number

    Returns:
        IP address if found, None otherwise
    """
    # Check if it's already an IP address
    if "." in device_id and device_id.replace(".", "").replace(":", "").isdigit():
        return device_id

    # Try to find in cache
    cache = load_device_cache()
    device = cache.find_by_identifier(device_id)

    if device:
        logger.info(f"Resolved '{device_id}' to IP {device.ip}")
        return device.ip

    logger.warning(f"Could not resolve device identifier '{device_id}'")
    return None