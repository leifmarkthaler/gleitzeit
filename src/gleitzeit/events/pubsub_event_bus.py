"""
Complete Redis Pub/Sub Event Bus for Stateless Operation.

This replaces the entire event system with Redis Pub/Sub, eliminating
the need for any handler registration in memory or persistence.
"""

import asyncio
import logging
import json
from typing import Dict, Set, Callable, Optional, Any, List
from datetime import datetime
from contextlib import asynccontextmanager

from gleitzeit.core.events import GleitzeitEvent, EventType

logger = logging.getLogger(__name__)


class PubSubEventBus:
    """
    Complete event bus implementation using Redis Pub/Sub.
    
    This bus supports all event types and provides a drop-in replacement
    for the existing event system, but with true stateless operation.
    """
    
    def __init__(self, redis_client, event_store=None):
        """
        Initialize the Pub/Sub event bus.
        
        Args:
            redis_client: Redis client instance
            event_store: Optional EventStore for persisting events
        """
        self.redis = redis_client
        self.event_store = event_store
        self._subscribers: Dict[str, asyncio.Task] = {}
        self._handlers: Dict[str, List[Callable]] = {}
        self._running = False
        self._pubsub_instances: List[Any] = []
        
        logger.info("Initialized PubSubEventBus")
    
    async def initialize(self):
        """Initialize the event bus (for compatibility)."""
        await self.start()
    
    async def start(self):
        """Start the event bus."""
        self._running = True
        logger.info("PubSubEventBus started")
    
    async def stop(self):
        """Stop the event bus and all subscribers."""
        logger.info("Stopping PubSubEventBus...")
        self._running = False
        
        # Cancel all subscriber tasks
        for channel, task in self._subscribers.items():
            logger.debug(f"Cancelling subscriber for {channel}")
            task.cancel()
        
        # Wait for tasks to complete
        if self._subscribers:
            await asyncio.gather(*self._subscribers.values(), return_exceptions=True)
        
        # Close all pubsub instances
        for pubsub in self._pubsub_instances:
            try:
                await pubsub.close()
            except:
                pass
        
        self._subscribers.clear()
        self._handlers.clear()
        self._pubsub_instances.clear()
        logger.info("PubSubEventBus stopped")
    
    async def shutdown(self):
        """Shutdown the event bus (alias for stop)."""
        await self.stop()
    
    async def emit(self, event: GleitzeitEvent) -> None:
        """
        Emit an event to Redis Pub/Sub.
        
        Args:
            event: Event to emit
        """
        # Persist event if store is configured
        if self.event_store:
            try:
                await self.event_store.save_event(event)
            except Exception as e:
                logger.warning(f"Failed to persist event {event.event_type}: {e}")
                # Don't fail emission if persistence fails
        
        # Get channel name
        channel = self._get_channel_name(event.event_type)
        
        # Serialize event
        message = {
            'event_type': str(event.event_type.value if hasattr(event.event_type, 'value') else event.event_type),
            'data': event.data,
            'severity': str(event.severity.value if hasattr(event.severity, 'value') else event.severity),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Publish to Redis
        try:
            subscribers = await self.redis.publish(channel, json.dumps(message))
            logger.debug(f"Emitted {event.event_type} to {subscribers} subscribers")
        except Exception as e:
            logger.error(f"Failed to emit event {event.event_type}: {e}")
    
    def register(self, event_type: EventType, handler: Callable) -> None:
        """
        Register a handler for an event type (synchronous for compatibility).
        
        This starts an async task to subscribe if needed.
        
        Args:
            event_type: Event type to handle
            handler: Handler function
        """
        # Create async task for subscription
        asyncio.create_task(self._register_async(event_type, handler))
    
    async def register_handler(self, event_type: EventType, handler: Callable, **kwargs) -> None:
        """
        Register a handler for an event type (async version).
        
        Args:
            event_type: Event type to handle
            handler: Handler function
            **kwargs: Additional parameters (ignored for compatibility)
        """
        await self._register_async(event_type, handler)
    
    async def _register_async(self, event_type: EventType, handler: Callable) -> None:
        """
        Internal async registration.
        
        Args:
            event_type: Event type to handle
            handler: Handler function
        """
        channel = self._get_channel_name(event_type)
        
        # Store handler
        if channel not in self._handlers:
            self._handlers[channel] = []
        if handler not in self._handlers[channel]:
            self._handlers[channel].append(handler)
        
        # Start subscriber if not already running
        if channel not in self._subscribers or self._subscribers[channel].done():
            self._subscribers[channel] = asyncio.create_task(
                self._subscribe_channel(channel)
            )
            logger.info(f"Registered handler for {event_type}")
    
    async def _subscribe_channel(self, channel: str):
        """
        Subscribe to a Redis channel and process messages.
        
        Args:
            channel: Channel to subscribe to
        """
        pubsub = self.redis.pubsub()
        self._pubsub_instances.append(pubsub)
        
        try:
            # Subscribe
            await pubsub.subscribe(channel)
            logger.info(f"Subscribed to channel: {channel}")
            
            # Process messages
            while self._running:
                try:
                    # Get message (non-blocking with timeout)
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0
                    )
                    
                    if message and message['type'] == 'message':
                        await self._process_message(channel, message['data'])
                        
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in subscriber for {channel}: {e}")
                    await asyncio.sleep(0.1)
                    
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except:
                pass
            logger.debug(f"Unsubscribed from channel: {channel}")
    
    async def _process_message(self, channel: str, data: bytes):
        """
        Process a message from Redis.
        
        Args:
            channel: Channel the message came from
            data: Message data
        """
        try:
            # Decode message
            message = json.loads(data)
            
            # Create event
            event = GleitzeitEvent(
                event_type=message['event_type'],
                data=message.get('data', {}),
                severity=message.get('severity', 'info')
            )
            
            # Call handlers
            handlers = self._handlers.get(channel, [])
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    logger.error(f"Error in handler for {channel}: {e}", exc_info=True)
                    
        except Exception as e:
            logger.error(f"Error processing message on {channel}: {e}")
    
    def _get_channel_name(self, event_type: EventType) -> str:
        """
        Get Redis channel name for event type.
        
        Args:
            event_type: Event type
            
        Returns:
            Channel name
        """
        if hasattr(event_type, 'value'):
            return f"gleitzeit:event:{event_type.value}"
        else:
            return f"gleitzeit:event:{str(event_type).replace(':', '_')}"
    
    # Compatibility methods
    
    async def get_handlers(self, event_type: EventType) -> List[Dict]:
        """Get registered handlers (for compatibility)."""
        channel = self._get_channel_name(event_type)
        handlers = self._handlers.get(channel, [])
        return [{'handler': h} for h in handlers]
    
    async def unregister(self, event_type: EventType, handler: Callable) -> bool:
        """Unregister a handler (for compatibility)."""
        channel = self._get_channel_name(event_type)
        if channel in self._handlers and handler in self._handlers[channel]:
            self._handlers[channel].remove(handler)
            return True
        return False
    
    @asynccontextmanager
    async def transaction(self):
        """Event transaction context (no-op for Pub/Sub)."""
        yield self
    
    async def emit_batch(self, events: List[GleitzeitEvent]) -> None:
        """Emit multiple events."""
        for event in events:
            await self.emit(event)