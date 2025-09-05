"""
Client adapters for SystemManager communication.

These adapters provide event-driven communication with the Gleitzeit SystemManager
via API (HTTP/WebSocket).
"""

from .base import BaseAdapter
from .api import APIAdapter
from .event_driven import EventDrivenAdapter

__all__ = [
    'BaseAdapter',
    'APIAdapter', 
    'EventDrivenAdapter'
]