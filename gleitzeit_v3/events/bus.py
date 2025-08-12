"""
Event Bus for Gleitzeit V3

Provides a high-level abstraction over Socket.IO for event-driven communication.
Handles event routing, filtering, validation, and persistence.
"""

import asyncio
import logging
from typing import Dict, List, Callable, Optional, Any, Set, TYPE_CHECKING
from datetime import datetime, timedelta
import json

import socketio

from .schemas import EventEnvelope, EventType, EventSeverity, EventFilter

if TYPE_CHECKING:
    from .store import EventStore

logger = logging.getLogger(__name__)



EventHandler = Callable[[EventEnvelope], Any]


class EventBus:
    """
    Event bus built on Socket.IO for distributed event communication.
    
    Features:
    - Event validation and schema checking
    - Event filtering and routing
    - Event persistence and replay
    - Dead letter queue for failed events
    - Event metrics and monitoring
    """
    
    def __init__(
        self,
        component_id: str,
        socketio_url: str = "http://localhost:8000",
        event_store: Optional['EventStore'] = None,
        enable_persistence: bool = True,
        max_retry_attempts: int = 3
    ):
        self.component_id = component_id
        self.socketio_url = socketio_url
        self.event_store = event_store
        self.enable_persistence = enable_persistence
        self.max_retry_attempts = max_retry_attempts
        
        # Socket.IO client
        self.sio = socketio.AsyncClient()
        self.connected = False
        self.registered = False
        
        # Event handling
        self.handlers: Dict[str, List[tuple[EventFilter, EventHandler]]] = {}
        self.global_handlers: List[tuple[EventFilter, EventHandler]] = []
        
        # Event tracking
        self.sequence_counter = 0
        self.pending_events: Dict[str, EventEnvelope] = {}  # event_id -> event
        self.failed_events: List[EventEnvelope] = []  # Dead letter queue
        
        # Metrics
        self.events_published = 0
        self.events_received = 0
        self.events_failed = 0
        
        self._setup_socketio_handlers()
        
        logger.info(f"EventBus initialized for component: {component_id}")
    
    def _setup_socketio_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info(f"🔗 EventBus connected to {self.socketio_url}")
            
            # Register component with event system
            await self.sio.emit('component:register', {
                'component_id': self.component_id,
                'component_type': 'event_participant',
                'capabilities': ['event_publisher', 'event_subscriber']
            })
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            self.registered = False
            logger.warning(f"🔌 EventBus disconnected from {self.socketio_url}")
        
        @self.sio.on('component:registered')
        async def component_registered(data):
            self.registered = True
            logger.info(f"✅ EventBus registered: {data}")
        
        @self.sio.on('event:dispatch')
        async def event_dispatch(data):
            """Handle incoming events from other components"""
            await self._handle_incoming_event(data)
        
        @self.sio.on('event:ack')
        async def event_ack(data):
            """Handle event acknowledgments"""
            event_id = data.get('event_id')
            if event_id in self.pending_events:
                del self.pending_events[event_id]
                logger.debug(f"Event acknowledged: {event_id}")
    
    async def start(self):
        """Start the event bus"""
        try:
            await self.sio.connect(self.socketio_url)
            
            # Wait for registration
            max_wait = 10
            wait_time = 0
            while not self.registered and wait_time < max_wait:
                await asyncio.sleep(0.5)
                wait_time += 0.5
            
            if not self.registered:
                raise Exception("Failed to register with event system")
            
            logger.info(f"🚀 EventBus started for {self.component_id}")
            
        except Exception as e:
            logger.error(f"Failed to start EventBus: {e}")
            raise
    
    async def stop(self):
        """Stop the event bus"""
        try:
            if self.connected:
                await self.sio.disconnect()
            logger.info(f"🛑 EventBus stopped for {self.component_id}")
        except Exception as e:
            logger.error(f"Error stopping EventBus: {e}")
    
    def subscribe(
        self,
        handler: EventHandler,
        event_filter: Optional[EventFilter] = None,
        event_types: Optional[List[EventType]] = None
    ):
        """
        Subscribe to events with optional filtering
        
        Args:
            handler: Function to call when matching events arrive
            event_filter: Complex filter for events
            event_types: Simple list of event types to listen for
        """
        if event_filter is None and event_types:
            event_filter = EventFilter(event_types=set(event_types))
        elif event_filter is None:
            event_filter = EventFilter()  # Match all events
        
        if event_types:
            # Subscribe to specific event types
            for event_type in event_types:
                if event_type.value not in self.handlers:
                    self.handlers[event_type.value] = []
                self.handlers[event_type.value].append((event_filter, handler))
        else:
            # Global subscription (all events)
            self.global_handlers.append((event_filter, handler))
        
        logger.debug(f"Subscribed to events: {event_types or 'ALL'}")
    
    async def publish(self, event: EventEnvelope, target_components: Optional[List[str]] = None):
        """
        Publish an event to the event bus
        
        Args:
            event: Event to publish
            target_components: Optional list of specific components to send to
        """
        try:
            # Set sequence number
            self.sequence_counter += 1
            event.sequence_number = self.sequence_counter
            
            # Persist event if enabled
            if self.enable_persistence and self.event_store:
                await self.event_store.store_event(event)
            
            # Prepare event data
            event_data = {
                'event': event.dict(),
                'source_component': self.component_id,
                'target_components': target_components,
                'timestamp': event.timestamp.isoformat()
            }
            
            # Track pending event
            self.pending_events[event.event_id] = event
            
            # Only emit to Socket.IO if not using mock URL
            if not self.socketio_url.startswith("mock://"):
                # Emit to Socket.IO
                await self.sio.emit('event:publish', event_data)
            else:
                # For mock mode, directly handle as incoming event for local testing
                await self._handle_incoming_event(event_data)
            
            self.events_published += 1
            logger.debug(f"Published event: {event.event_type} ({event.event_id})")
            
            # Set timeout for acknowledgment (skip for mock)
            if not self.socketio_url.startswith("mock://"):
                asyncio.create_task(self._handle_event_timeout(event.event_id))
            else:
                # For mock, immediately acknowledge
                if event.event_id in self.pending_events:
                    del self.pending_events[event.event_id]
            
        except Exception as e:
            logger.error(f"Failed to publish event {event.event_id}: {e}")
            self.events_failed += 1
            self.failed_events.append(event)
            raise
    
    async def _handle_incoming_event(self, data: Dict[str, Any]):
        """Handle events received from other components"""
        try:
            event_data = data.get('event', {})
            event = EventEnvelope(**event_data)
            
            self.events_received += 1
            
            # Send acknowledgment (only for real Socket.IO connections)
            if not self.socketio_url.startswith("mock://"):
                await self.sio.emit('event:ack', {
                    'event_id': event.event_id,
                    'receiver_component': self.component_id
                })
            
            # Find matching handlers
            matching_handlers = []
            
            # Check specific event type handlers
            if event.event_type.value in self.handlers:
                for event_filter, handler in self.handlers[event.event_type.value]:
                    if event_filter.matches(event):
                        matching_handlers.append(handler)
            
            # Check global handlers
            for event_filter, handler in self.global_handlers:
                if event_filter.matches(event):
                    matching_handlers.append(handler)
            
            # Execute handlers
            if matching_handlers:
                logger.debug(f"Executing {len(matching_handlers)} handlers for {event.event_type}")
                await asyncio.gather(*[
                    self._safe_execute_handler(handler, event) 
                    for handler in matching_handlers
                ], return_exceptions=True)
            else:
                logger.debug(f"No handlers found for event: {event.event_type}")
            
        except Exception as e:
            logger.error(f"Error handling incoming event: {e}")
            self.events_failed += 1
    
    async def _safe_execute_handler(self, handler: EventHandler, event: EventEnvelope):
        """Safely execute an event handler with error handling"""
        try:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Event handler failed for {event.event_type} ({event.event_id}): {e}")
            # Could emit an audit event here about handler failure
    
    async def _handle_event_timeout(self, event_id: str, timeout_seconds: float = 30.0):
        """Handle event acknowledgment timeouts"""
        await asyncio.sleep(timeout_seconds)
        
        if event_id in self.pending_events:
            event = self.pending_events.pop(event_id)
            logger.warning(f"Event timeout: {event.event_type} ({event_id})")
            
            # Could retry or move to dead letter queue
            if len([e for e in self.failed_events if e.event_id == event_id]) < self.max_retry_attempts:
                logger.info(f"Retrying event: {event_id}")
                await self.publish(event)
            else:
                logger.error(f"Event moved to dead letter queue: {event_id}")
                self.failed_events.append(event)
    
    async def replay_events(
        self,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        event_filter: Optional[EventFilter] = None
    ) -> List[EventEnvelope]:
        """Replay events from the event store"""
        if not self.event_store:
            raise ValueError("Event store not configured")
        
        return await self.event_store.get_events(
            start_time=start_time,
            end_time=end_time,
            event_filter=event_filter
        )
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get event bus metrics"""
        return {
            'component_id': self.component_id,
            'connected': self.connected,
            'registered': self.registered,
            'events_published': self.events_published,
            'events_received': self.events_received,
            'events_failed': self.events_failed,
            'pending_events': len(self.pending_events),
            'failed_events': len(self.failed_events),
            'sequence_counter': self.sequence_counter,
            'handler_count': sum(len(handlers) for handlers in self.handlers.values()) + len(self.global_handlers)
        }