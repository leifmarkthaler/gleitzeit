"""
Event system for Gleitzeit.

The event system is now always stateless, using Redis or other backends for persistence.
This enables true horizontal scaling and crash recovery.
"""

from .base import EventBus, EventHandler, HandlerError
from .stateless_bus import StatelessEventBus, HandlerConfig

__all__ = [
    "EventBus",
    "EventHandler", 
    "HandlerError",
    "StatelessEventBus",
    "HandlerConfig"
]