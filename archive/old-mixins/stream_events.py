"""
Stream events mixin providing event bus compatibility.
"""

import logging
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger(__name__)


class StreamEventsMixin:
    """
    Mixin providing event bus compatibility for stream-based system.

    This mixin handles:
    - Event emission compatibility
    - Event handler registration
    - Event bus interface adaptation
    """

    def __init__(self, **kwargs):
        """Initialize event components."""
        super().__init__(**kwargs)

    # EventBus compatibility methods
    async def emit_event(self, event):
        """
        Emit an event to streams (EventBus compatibility method).

        This method provides compatibility with EventBus interface so components
        can use StreamSystemManager as a drop-in replacement for EventBus.
        """
        try:
            if hasattr(self, 'event_bus') and self.event_bus:
                # Use the underlying event bus for emission
                await self.event_bus.emit(event)
                logger.debug(f"Emitted event {event.event_type} via event_bus")
            elif hasattr(self, 'stream_consumer') and self.stream_consumer:
                # Direct stream emission
                stream_key = self.stream_consumer._get_stream_key(event.event_type)
                event_data = {
                    "event_type": event.event_type,
                    "timestamp": event.timestamp.isoformat() if event.timestamp else "",
                    "data": event.data,
                    "source": event.source or "",
                    "correlation_id": event.correlation_id or "",
                    "severity": event.severity,
                    "metadata": event.tags or {}
                }

                if hasattr(self.persistence, 'redis'):
                    redis_client = self.persistence.redis
                    msg_id = await redis_client.xadd(stream_key, event_data)
                    logger.debug(f"Emitted event {event.event_type} to stream {stream_key}")
                    return msg_id
                else:
                    logger.warning(f"No Redis client available for event emission: {event.event_type}")
            else:
                logger.warning(f"No event emission mechanism available for event: {event.event_type}")

        except Exception as e:
            logger.error(f"Error emitting event {event.event_type}: {e}")
            raise

    async def register_handler(self, event_type: str, handler: Callable,
                             priority: int = 2, filter_expr: Optional[str] = None, once: bool = False):
        """
        Register event handler (EventBus compatibility method).

        This method provides compatibility with EventBus interface so components
        can register handlers with StreamSystemManager as a drop-in replacement for EventBus.
        """
        try:
            # Use the stream handler registration method
            if hasattr(self, 'register_stream_handler'):
                self.register_stream_handler(event_type, handler, "compatibility_layer")
                logger.info(f"Registered handler for {event_type} via compatibility layer")
            else:
                logger.warning(f"No stream handler registration available for {event_type}")

            # Return a synthetic handler ID for compatibility
            handler_id = f"{event_type}:{id(handler)}"
            return handler_id

        except Exception as e:
            logger.error(f"Error registering handler for {event_type}: {e}")
            raise

    async def unregister_handler(self, handler_id: str):
        """
        Unregister event handler (EventBus compatibility method).

        Note: This is a compatibility method. Stream-based handlers are typically
        not unregistered during runtime.
        """
        logger.debug(f"Handler unregistration requested for {handler_id} (stream-based handlers are persistent)")

    async def emit(self, event):
        """Alias for emit_event for EventBus compatibility."""
        return await self.emit_event(event)

    # Additional event utilities
    def create_event(self, event_type: str, data: Dict[str, Any], **kwargs):
        """Create an event object."""
        from ...core.events import GleitzeitEvent

        return GleitzeitEvent(
            event_type=event_type,
            data=data,
            source=kwargs.get('source', f"stream_system_manager_{self.instance_id}"),
            correlation_id=kwargs.get('correlation_id'),
            severity=kwargs.get('severity', 'info'),
            tags=kwargs.get('tags', {})
        )

    async def emit_system_event(self, event_type: str, data: Dict[str, Any], **kwargs):
        """Emit a system event with standard formatting."""
        event = self.create_event(event_type, data, **kwargs)
        await self.emit_event(event)