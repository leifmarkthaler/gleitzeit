"""Base classes for event handling system."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Type, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from ..core.events import GleitzeitEvent

logger = logging.getLogger(__name__)


@dataclass
class HandlerError:
    """Track errors from event handlers."""
    handler_name: str
    event_type: str
    error: Exception
    timestamp: datetime
    event_id: Optional[str] = None


class EventHandler(ABC):
    """Base class for event handlers."""
    
    @abstractmethod
    async def handle(self, event: GleitzeitEvent) -> None:
        """Handle an event."""
        pass


class EventBus:
    """
    Event bus for coordinating system components.
    
    Always uses stateless mode with Redis/backend persistence for horizontal scaling.
    """
    
    def __init__(self, isolate_errors: bool = True, track_errors: bool = True, 
                 error_persistence = None, event_store = None, 
                 persistence = None, **kwargs):
        """
        Initialize the event bus.
        
        Args:
            isolate_errors: If True, handler errors won't affect other handlers (ignored - always True in stateless)
            track_errors: If True, keep track of handler errors for debugging (ignored - always True in stateless)
            error_persistence: Optional EventErrorPersistence for saving errors (ignored - handled by stateless)
            event_store: Optional EventStore for persisting events
            persistence: Backend persistence (Redis, InMemory, etc.)
            **kwargs: Ignored legacy parameters
        """
        self.event_store = event_store
        
        # Always use streamlined backend
        from .streamlined_event_bus import StreamlinedEventBus
        self._stateless_bus = StreamlinedEventBus(redis_client=persistence)
        logger.info("EventBus initialized (always stateless)")
    
    async def register_handler(self, event_type: str, handler, priority: int = 2, 
                              filter_expr: Optional[str] = None, once: bool = False) -> str:
        """Register an event handler for a specific event type."""
        return await self._stateless_bus.register_handler(event_type, handler, priority, filter_expr, once)
    
    def register(self, event_type: str, handler) -> None:
        """Legacy synchronous registration - delegates to async register_handler."""
        # Schedule async registration
        asyncio.create_task(self.register_handler(event_type, handler))
    
    async def unregister_handler(self, handler_id: str) -> bool:
        """Unregister a handler by ID."""
        return await self._stateless_bus.unregister_handler(handler_id)
    
    def unregister(self, event_type: str, handler: EventHandler) -> bool:
        """Legacy unregister method - not supported in stateless mode."""
        logger.warning("Unregister by handler reference not supported in stateless mode")
        return False
    
    async def emit(self, event: GleitzeitEvent) -> None:
        """Emit an event to all registered handlers."""
        # Persist event if store is configured
        if self.event_store:
            try:
                await self.event_store.save_event(event)
            except Exception as e:
                logger.warning(f"Failed to persist event {event.event_type}: {e}")
                # Don't fail emission if persistence fails
        
        # Use stateless event emission
        await self._stateless_bus.emit(event)
    
    async def get_handlers(self, event_type: str):
        """Get handlers for an event type."""
        return await self._stateless_bus.get_handlers(event_type)
    
    async def get_error_history(self, limit: Optional[int] = None):
        """Get the error history."""
        return await self._stateless_bus.get_error_history(limit)
    
    def clear_error_history(self) -> None:
        """Clear the error history - not supported in stateless mode."""
        logger.warning("Clear error history not supported in stateless mode")
    
    async def start(self) -> None:
        """Start the event bus."""
        await self._stateless_bus.start()
        logger.info("EventBus started")
    
    async def stop(self) -> None:
        """Stop the event bus and cleanup resources."""
        await self._stateless_bus.stop()
        logger.info("EventBus stopped")
    
    def get_handler_count(self, event_type: str) -> int:
        """Get the number of handlers registered for an event type - not available in stateless mode."""
        logger.debug("Handler count not available in stateless mode")
        return 0
    
    def list_event_types(self) -> List[str]:
        """List all event types with registered handlers - not available in stateless mode."""
        logger.debug("Event type listing not available in stateless mode")
        return []
    
    async def get_metrics(self, handler_id: Optional[str] = None) -> Dict[str, Any]:
        """Get event bus metrics."""
        return await self._stateless_bus.get_metrics(handler_id)
    
    # Legacy compatibility properties
    @property
    def stateless(self) -> bool:
        """Always True - EventBus is always stateless now."""
        return True
    
    @property 
    def isolate_errors(self) -> bool:
        """Always True - stateless bus always isolates errors."""
        return True
        
    @property
    def track_errors(self) -> bool:
        """Always True - stateless bus always tracks errors."""
        return True