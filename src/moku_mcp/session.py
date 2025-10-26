"""
Moku Session Management

Context manager for safe session handling with automatic cleanup.
"""

from typing import Optional
from loguru import logger


class MokuSession:
    """
    Context manager for automatic connection cleanup.

    Ensures devices are ALWAYS released, even on errors.

    Example:
        async with MokuSession("192.168.1.100") as moku:
            # All operations are protected by automatic cleanup
            result = await moku.push_config(config)
            # Device automatically released here, even if operation failed
    """

    def __init__(self, device_id: str, force: bool = False):
        """
        Initialize session context.

        Args:
            device_id: IP address, device name, or serial number
            force: Force connection even if owned by another client
        """
        self.device_id = device_id
        self.force = force
        self.server = None

    async def __aenter__(self):
        """
        Enter context: attach to Moku device.

        Returns:
            MokuMCPServer instance with active connection
        """
        from .server import MokuMCPServer

        self.server = MokuMCPServer.get_instance()  # Use singleton

        try:
            await self.server.attach_moku(self.device_id, self.force)
            logger.info(f"Session started with device {self.device_id}")
            return self.server
        except Exception as e:
            logger.error(f"Failed to start session with {self.device_id}: {e}")
            # Ensure cleanup even if attach fails
            self.server = None
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Exit context: release Moku device.

        Always releases device, even if an exception occurred.
        """
        if self.server and self.server.moku_instance:
            try:
                await self.server.release_moku()
                logger.info(f"Session ended, device {self.device_id} released")
            except Exception as e:
                logger.error(f"Error releasing device {self.device_id}: {e}")
                # Don't re-raise to avoid masking the original exception

        # Reset server reference
        self.server = None

        # Don't suppress exceptions (return None/False)
        return False