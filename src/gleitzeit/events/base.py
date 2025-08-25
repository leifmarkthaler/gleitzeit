"""Base classes for event handling system."""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Type, Optional
from ..core.events import GleitzeitEvent

logger = logging.getLogger(__name__)


class EventHandler(ABC):
    """Base class for event handlers."""
    
    @abstractmethod
    async def handle(self, event: GleitzeitEvent) -> None:
        """Handle an event."""
        pass


class EventBus:
    """Simple in-memory event bus for coordinating system components."""
    
    def __init__(self):
        self._handlers: Dict[str, List[EventHandler]] = {}
    
    def register(self, event_type: str, handler) -> None:
        """Register an event handler for a specific event type.
        Handler can be either an EventHandler object or an async callable."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        handler_name = handler.__class__.__name__ if hasattr(handler, '__class__') else handler.__name__
        logger.debug(f"Registered handler {handler_name} for event type {event_type}")
    
    def unregister(self, event_type: str, handler: EventHandler) -> bool:
        """Unregister an event handler."""
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
                logger.debug(f"Unregistered handler {handler.__class__.__name__} for event type {event_type}")
                return True
            except ValueError:
                pass
        return False
    
    async def emit(self, event: GleitzeitEvent) -> None:
        """Emit an event to all registered handlers."""
        event_type = event.event_type
        handlers = self._handlers.get(event_type, [])
        
        if not handlers:
            logger.debug(f"No handlers registered for event type {event_type}")
            return
        
        logger.debug(f"Emitting event {event_type} to {len(handlers)} handlers")
        for handler in handlers:
            handler_name = handler.__class__.__name__ if hasattr(handler, '__class__') else handler.__name__
            logger.debug(f"Handler {handler_name} will process {event_type}")
        
        # Execute all handlers concurrently
        import asyncio
        tasks = []
        for handler in handlers:
            try:
                # Check if handler is an EventHandler object or a callable
                if hasattr(handler, 'handle'):
                    # It's an EventHandler object
                    task = asyncio.create_task(handler.handle(event))
                elif asyncio.iscoroutinefunction(handler):
                    # It's an async function
                    task = asyncio.create_task(handler(event))
                else:
                    logger.error(f"Handler {handler} is not an EventHandler or async function")
                    continue
                tasks.append(task)
            except Exception as e:
                handler_name = handler.__class__.__name__ if hasattr(handler, '__class__') else str(handler)
                logger.error(f"Failed to create task for handler {handler_name}: {e}")
        
        if tasks:
            # Wait for all handlers to complete
            try:
                await asyncio.gather(*tasks)
                logger.debug(f"Successfully processed event {event_type} with {len(tasks)} handlers")
            except Exception as e:
                logger.error(f"Error processing event {event_type}: {e}")
                # Continue processing other events even if some handlers fail
    
    def get_handler_count(self, event_type: str) -> int:
        """Get the number of handlers registered for an event type."""
        return len(self._handlers.get(event_type, []))
    
    def list_event_types(self) -> List[str]:
        """List all event types with registered handlers."""
        return list(self._handlers.keys())