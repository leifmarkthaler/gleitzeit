"""
Event system for Gleitzeit.

The event system uses ONLY the StreamlinedEventBus with Redis Streams.
This is the ONE true event pathway - no duplicates, no alternatives.
"""

from .streamlined_event_bus import StreamlinedEventBus
from .base import EventHandler, HandlerError

# Compatibility aliases
EventBus = StreamlinedEventBus
StatelessEventBus = StreamlinedEventBus

__all__ = [
    "StreamlinedEventBus",
    "EventBus",  # Alias for compatibility
    "StatelessEventBus",  # Alias for compatibility
    "EventHandler",
    "HandlerError"
]