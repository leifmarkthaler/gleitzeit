"""Base classes for event handling system."""

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
    Simple in-memory event bus for coordinating system components.
    
    Features isolated error handling to prevent one handler's failure
    from affecting others. Can optionally persist errors for traceability.
    """
    
    def __init__(self, isolate_errors: bool = True, track_errors: bool = True, 
                 error_persistence = None):
        """
        Initialize the event bus.
        
        Args:
            isolate_errors: If True, handler errors won't affect other handlers
            track_errors: If True, keep track of handler errors for debugging
            error_persistence: Optional EventErrorPersistence for saving errors
        """
        self._handlers: Dict[str, List[EventHandler]] = {}
        self.isolate_errors = isolate_errors
        self.track_errors = track_errors
        self.handler_errors: List[HandlerError] = []
        self.max_error_history = 100  # Keep last 100 errors
        self.error_persistence = error_persistence
    
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
            if self.isolate_errors:
                # Use gather with return_exceptions to isolate errors
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Track successes and failures
                successes = 0
                failures = 0
                
                for i, result in enumerate(results):
                    handler = handlers[i]
                    handler_name = handler.__class__.__name__ if hasattr(handler, '__class__') else str(handler)
                    
                    if isinstance(result, Exception):
                        failures += 1
                        logger.error(f"Handler {handler_name} failed for event {event_type}: {result}")
                        
                        # Track the error if enabled
                        if self.track_errors:
                            error_record = HandlerError(
                                handler_name=handler_name,
                                event_type=event_type,
                                error=result,
                                timestamp=datetime.now(),
                                event_id=getattr(event, 'event_id', None)
                            )
                            self.handler_errors.append(error_record)
                            
                            # Trim error history if it gets too large
                            if len(self.handler_errors) > self.max_error_history:
                                self.handler_errors = self.handler_errors[-self.max_error_history:]
                            
                            # Persist the error if persistence is available
                            if self.error_persistence:
                                try:
                                    import asyncio
                                    # Save error to persistence
                                    asyncio.create_task(
                                        self.error_persistence.save_error(
                                            handler_name=handler_name,
                                            event_type=event_type,
                                            error=result,
                                            event_id=getattr(event, 'event_id', None),
                                            metadata={
                                                'handler_class': handler.__class__.__name__ if hasattr(handler, '__class__') else None,
                                                'event_data': getattr(event, 'data', None)
                                            }
                                        )
                                    )
                                except Exception as persist_err:
                                    logger.warning(f"Failed to persist event error: {persist_err}")
                    else:
                        successes += 1
                
                logger.debug(f"Event {event_type} processed: {successes} succeeded, {failures} failed")
            else:
                # Original behavior - one failure affects all
                try:
                    await asyncio.gather(*tasks)
                    logger.debug(f"Successfully processed event {event_type} with {len(tasks)} handlers")
                except Exception as e:
                    logger.error(f"Error processing event {event_type}: {e}")
                    raise  # Re-raise to maintain original behavior when not isolating
    
    def get_handler_count(self, event_type: str) -> int:
        """Get the number of handlers registered for an event type."""
        return len(self._handlers.get(event_type, []))
    
    def list_event_types(self) -> List[str]:
        """List all event types with registered handlers."""
        return list(self._handlers.keys())
    
    def get_error_history(self, limit: Optional[int] = None) -> List[HandlerError]:
        """
        Get the error history.
        
        Args:
            limit: Maximum number of errors to return (most recent first)
            
        Returns:
            List of HandlerError records
        """
        if not self.track_errors:
            return []
        
        errors = list(reversed(self.handler_errors))  # Most recent first
        if limit:
            return errors[:limit]
        return errors
    
    def get_error_stats(self) -> Dict[str, Any]:
        """
        Get statistics about handler errors.
        
        Returns:
            Dictionary with error statistics
        """
        if not self.track_errors or not self.handler_errors:
            return {
                "total_errors": 0,
                "handlers_with_errors": [],
                "event_types_with_errors": []
            }
        
        handler_counts = {}
        event_type_counts = {}
        
        for error in self.handler_errors:
            handler_counts[error.handler_name] = handler_counts.get(error.handler_name, 0) + 1
            event_type_counts[error.event_type] = event_type_counts.get(error.event_type, 0) + 1
        
        return {
            "total_errors": len(self.handler_errors),
            "handlers_with_errors": sorted(
                [(h, c) for h, c in handler_counts.items()],
                key=lambda x: x[1],
                reverse=True
            ),
            "event_types_with_errors": sorted(
                [(e, c) for e, c in event_type_counts.items()],
                key=lambda x: x[1],
                reverse=True
            ),
            "oldest_error": self.handler_errors[0].timestamp if self.handler_errors else None,
            "newest_error": self.handler_errors[-1].timestamp if self.handler_errors else None
        }
    
    def clear_error_history(self) -> None:
        """Clear the error history."""
        self.handler_errors.clear()