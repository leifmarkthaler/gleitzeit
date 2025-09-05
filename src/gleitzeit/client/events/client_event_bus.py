"""
Client-side event bus for handling local and server events.
"""

import asyncio
import logging
import weakref
from typing import Dict, List, Set, Callable, Any, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from gleitzeit.core.events import EventType, GleitzeitEvent
from .models import ClientEvent

logger = logging.getLogger(__name__)


class SubscriptionPriority(Enum):
    """Priority levels for event handlers."""
    CRITICAL = 0  # System handlers (reconnection, etc.)
    HIGH = 1      # User handlers that modify state
    NORMAL = 2    # Regular user handlers
    LOW = 3       # Logging, metrics, etc.


@dataclass
class EventSubscription:
    """Represents a subscription to an event type."""
    id: str
    event_type: Union[EventType, str]
    handler: Callable
    priority: SubscriptionPriority = SubscriptionPriority.NORMAL
    filter: Optional[Callable[[GleitzeitEvent], bool]] = None
    once: bool = False
    active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    call_count: int = 0
    last_called: Optional[datetime] = None
    error_count: int = 0
    last_error: Optional[str] = None


class EventHandler:
    """Wrapper for event handlers with metadata."""
    
    def __init__(self, 
                 handler: Callable,
                 priority: SubscriptionPriority = SubscriptionPriority.NORMAL,
                 filter: Optional[Callable] = None,
                 once: bool = False):
        """
        Initialize event handler wrapper.
        
        Args:
            handler: The actual handler function
            priority: Handler priority for execution order
            filter: Optional filter function to check if handler should run
            once: If True, handler is removed after first execution
        """
        self.handler = handler
        self.priority = priority
        self.filter = filter
        self.once = once
        self.call_count = 0
        self.error_count = 0
        
    async def __call__(self, event: GleitzeitEvent) -> Any:
        """Execute the handler."""
        if self.filter and not self.filter(event):
            return None
            
        try:
            self.call_count += 1
            result = self.handler(event)
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception as e:
            self.error_count += 1
            logger.error(f"Error in event handler: {e}")
            raise


class ClientEventBus:
    """
    Client-side event bus for managing events and subscriptions.
    
    This event bus:
    - Manages local event subscriptions
    - Handles both server and client events
    - Supports priority-based handler execution
    - Provides filtering and one-time handlers
    - Tracks handler metrics and errors
    """
    
    def __init__(self, 
                 max_queue_size: int = 10000,
                 error_handler: Optional[Callable] = None):
        """
        Initialize the client event bus.
        
        Args:
            max_queue_size: Maximum number of queued events
            error_handler: Optional global error handler
        """
        self._subscriptions: Dict[Union[EventType, str], List[EventSubscription]] = {}
        self._subscription_id_counter = 0
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False
        self._error_handler = error_handler
        self._metrics = {
            'events_received': 0,
            'events_processed': 0,
            'events_failed': 0,
            'handlers_registered': 0,
            'handlers_executed': 0,
            'handlers_failed': 0
        }
        
        # Weak references to prevent memory leaks
        self._weak_handlers: weakref.WeakValueDictionary = weakref.WeakValueDictionary()
        
    async def start(self):
        """Start the event bus processing loop."""
        if self._running:
            logger.warning("Event bus already running")
            return
            
        self._running = True
        self._processing_task = asyncio.create_task(self._process_events())
        logger.info("Client event bus started")
        
    async def stop(self):
        """Stop the event bus processing loop."""
        if not self._running:
            return
            
        self._running = False
        
        # Process remaining events
        while not self._event_queue.empty():
            try:
                event = self._event_queue.get_nowait()
                await self._dispatch_event(event)
            except asyncio.QueueEmpty:
                break
                
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
                
        logger.info("Client event bus stopped")
        
    def register(self, 
                 event_type: Union[EventType, str],
                 handler: Callable,
                 priority: SubscriptionPriority = SubscriptionPriority.NORMAL,
                 filter: Optional[Callable] = None,
                 once: bool = False) -> str:
        """
        Register an event handler.
        
        Args:
            event_type: Type of event to handle
            handler: Handler function (sync or async)
            priority: Handler execution priority
            filter: Optional filter function
            once: If True, handler runs only once
            
        Returns:
            Subscription ID for later removal
        """
        subscription_id = f"sub_{self._subscription_id_counter}"
        self._subscription_id_counter += 1
        
        subscription = EventSubscription(
            id=subscription_id,
            event_type=event_type,
            handler=handler,
            priority=priority,
            filter=filter,
            once=once
        )
        
        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []
            
        # Insert based on priority (lower priority value = higher priority)
        subscriptions = self._subscriptions[event_type]
        insert_idx = len(subscriptions)
        for i, sub in enumerate(subscriptions):
            if sub.priority.value > priority.value:
                insert_idx = i
                break
                
        subscriptions.insert(insert_idx, subscription)
        
        self._metrics['handlers_registered'] += 1
        logger.debug(f"Registered handler {subscription_id} for {event_type} with priority {priority.name}")
        
        return subscription_id
        
    def unregister(self, subscription_id: str) -> bool:
        """
        Unregister an event handler by subscription ID.
        
        Args:
            subscription_id: ID returned from register()
            
        Returns:
            True if handler was found and removed
        """
        for event_type, subscriptions in self._subscriptions.items():
            for i, sub in enumerate(subscriptions):
                if sub.id == subscription_id:
                    subscriptions.pop(i)
                    logger.debug(f"Unregistered handler {subscription_id}")
                    return True
        return False
        
    def unregister_all(self, event_type: Optional[Union[EventType, str]] = None):
        """
        Unregister all handlers for an event type or all handlers.
        
        Args:
            event_type: Optional event type to clear handlers for
        """
        if event_type:
            if event_type in self._subscriptions:
                count = len(self._subscriptions[event_type])
                self._subscriptions[event_type] = []
                logger.debug(f"Unregistered {count} handlers for {event_type}")
        else:
            total = sum(len(subs) for subs in self._subscriptions.values())
            self._subscriptions.clear()
            logger.debug(f"Unregistered all {total} handlers")
            
    async def emit(self, event: Union[GleitzeitEvent, Dict[str, Any]]) -> None:
        """
        Emit an event to all registered handlers.
        
        Args:
            event: Event to emit (GleitzeitEvent or dict)
        """
        # Convert dict to GleitzeitEvent if needed
        if isinstance(event, dict):
            event_type = event.get('event_type', 'custom')
            # Try to convert to EventType enum if possible
            try:
                event_type = EventType(event_type)
            except (ValueError, TypeError):
                # Use as string if not a valid EventType
                pass
            
            # Use ClientEvent for arbitrary event types
            event = ClientEvent(
                event_type=event_type,
                data=event.get('data', {}),
                timestamp=event.get('timestamp', datetime.utcnow())
            )
            
        self._metrics['events_received'] += 1
        
        # Queue event for processing
        try:
            await self._event_queue.put(event)
        except asyncio.QueueFull:
            logger.error(f"Event queue full, dropping event: {event.event_type}")
            self._metrics['events_failed'] += 1
            
    async def emit_sync(self, event: Union[GleitzeitEvent, Dict[str, Any]]) -> List[Any]:
        """
        Emit an event synchronously and wait for all handlers.
        
        Args:
            event: Event to emit
            
        Returns:
            List of handler results
        """
        # Convert dict to GleitzeitEvent if needed
        if isinstance(event, dict):
            event_type = event.get('event_type', 'custom')
            # Try to convert to EventType enum if possible
            try:
                event_type = EventType(event_type)
            except (ValueError, TypeError):
                # Use as string if not a valid EventType
                pass
            
            # Use ClientEvent for arbitrary event types
            event = ClientEvent(
                event_type=event_type,
                data=event.get('data', {}),
                timestamp=event.get('timestamp', datetime.utcnow())
            )
            
        return await self._dispatch_event(event)
        
    async def _process_events(self):
        """Process events from the queue."""
        while self._running:
            try:
                # Wait for event with timeout to allow checking _running
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0
                )
                await self._dispatch_event(event)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error processing event: {e}")
                self._metrics['events_failed'] += 1
                
    async def _dispatch_event(self, event: GleitzeitEvent) -> List[Any]:
        """
        Dispatch an event to all registered handlers.
        
        Args:
            event: Event to dispatch
            
        Returns:
            List of handler results
        """
        results = []
        handlers_to_remove = []
        
        # Get handlers for this event type
        subscriptions = self._subscriptions.get(event.event_type, [])
        
        # Also check for wildcard handlers
        wildcard_subs = self._subscriptions.get('*', [])
        all_subs = subscriptions + wildcard_subs
        
        for subscription in all_subs:
            if not subscription.active:
                continue
                
            try:
                # Apply filter if present
                if subscription.filter and not subscription.filter(event):
                    continue
                    
                # Execute handler
                handler_result = subscription.handler(event)
                if asyncio.iscoroutine(handler_result):
                    handler_result = await handler_result
                    
                results.append(handler_result)
                
                # Update metrics
                subscription.call_count += 1
                subscription.last_called = datetime.utcnow()
                self._metrics['handlers_executed'] += 1
                
                # Remove if one-time handler
                if subscription.once:
                    handlers_to_remove.append(subscription.id)
                    
            except Exception as e:
                subscription.error_count += 1
                subscription.last_error = str(e)
                self._metrics['handlers_failed'] += 1
                
                logger.error(f"Error in handler {subscription.id} for {event.event_type}: {e}")
                
                if self._error_handler:
                    try:
                        await self._error_handler(event, subscription, e)
                    except Exception as eh_error:
                        logger.error(f"Error in error handler: {eh_error}")
                        
        # Remove one-time handlers
        for sub_id in handlers_to_remove:
            self.unregister(sub_id)
            
        self._metrics['events_processed'] += 1
        
        return results
        
    def on(self, event_type: Union[EventType, str], 
           priority: SubscriptionPriority = SubscriptionPriority.NORMAL,
           filter: Optional[Callable] = None,
           once: bool = False):
        """
        Decorator for registering event handlers.
        
        Usage:
            @event_bus.on(EventType.TASK_COMPLETED)
            async def handle_task_complete(event):
                logger.info(f"Task {event.data['task_id']} completed")
                
        Args:
            event_type: Event type to handle
            priority: Handler priority
            filter: Optional filter function
            once: If True, handler runs only once
            
        Returns:
            Decorator function
        """
        def decorator(handler: Callable) -> Callable:
            self.register(event_type, handler, priority, filter, once)
            return handler
        return decorator
        
    def once(self, event_type: Union[EventType, str]):
        """
        Decorator for one-time event handlers.
        
        Usage:
            @event_bus.once(EventType.ENGINE_STARTED)
            async def on_engine_start(event):
                logger.info("Engine started")
                
        Args:
            event_type: Event type to handle once
            
        Returns:
            Decorator function
        """
        return self.on(event_type, once=True)
        
    def get_metrics(self) -> Dict[str, Any]:
        """Get event bus metrics."""
        return {
            **self._metrics,
            'queue_size': self._event_queue.qsize(),
            'subscription_count': sum(len(subs) for subs in self._subscriptions.values()),
            'event_types_monitored': len(self._subscriptions)
        }
        
    def get_subscriptions(self, event_type: Optional[Union[EventType, str]] = None) -> List[EventSubscription]:
        """
        Get active subscriptions.
        
        Args:
            event_type: Optional event type to filter by
            
        Returns:
            List of active subscriptions
        """
        if event_type:
            return self._subscriptions.get(event_type, []).copy()
        
        all_subs = []
        for subs in self._subscriptions.values():
            all_subs.extend(subs)
        return all_subs
        
    async def wait_for(self, 
                       event_type: Union[EventType, str],
                       filter: Optional[Callable] = None,
                       timeout: Optional[float] = None) -> Optional[GleitzeitEvent]:
        """
        Wait for a specific event to occur.
        
        Args:
            event_type: Event type to wait for
            filter: Optional filter function
            timeout: Optional timeout in seconds
            
        Returns:
            The event when it occurs, or None if timeout
        """
        future = asyncio.Future()
        
        def handler(event):
            if not filter or filter(event):
                if not future.done():
                    future.set_result(event)
                    
        sub_id = self.register(event_type, handler, once=True)
        
        try:
            if timeout:
                return await asyncio.wait_for(future, timeout)
            return await future
        except asyncio.TimeoutError:
            self.unregister(sub_id)
            return None