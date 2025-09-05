"""
Gleitzeit event-driven client package.

This package provides the event-driven client implementation
with real-time WebSocket support and zero polling overhead.
"""

from .client import GleitzeitClient, ClientMode, EventMode

# Legacy alias for compatibility
EventDrivenClient = GleitzeitClient

# Export main components
__all__ = [
    'GleitzeitClient',
    'ClientMode',
    'EventMode'
]