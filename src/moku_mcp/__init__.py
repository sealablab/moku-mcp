"""
Moku MCP Server

Model Context Protocol (MCP) server for Moku device control.

Provides LLM-friendly tools for:
- Device discovery and connection management
- Configuration deployment (MokuConfig models)
- Multi-instrument slot management
- Signal routing configuration
- Device metadata queries

Architecture:
- Stateful session management (attach/detach pattern)
- MokuConfig-driven deployment
- Graceful ownership handoff (iPad ↔ CLI ↔ LLM workflows)
"""

__version__ = "0.1.0"

from .server import MokuMCPServer

__all__ = ["MokuMCPServer"]
