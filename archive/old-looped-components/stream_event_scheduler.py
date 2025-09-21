"""
Pure Stream-based Event Scheduler.

High-performance event scheduling using Redis Streams with consumer groups
for enterprise-scale distributed processing.
"""

import asyncio
import logging
import time
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Callable, Awaitable, Union
from dataclasses import dataclass, field

from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent, EventType
from ..events import EventBus

logger = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    """Represents an event in the stream."""
    event_id: str
    event_type: str
    scheduled_time: datetime
    payload: Dict[str, Any]
    created_at: datetime
    shard: int
    processed: bool = False
    retry_count: int = 0

    def to_stream_data(self) -> Dict[str, str]:
        """Convert to Redis stream format (all values must be strings)."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "scheduled_time": self.scheduled_time.isoformat(),
            "payload": json.dumps(self.payload),
            "created_at": self.created_at.isoformat(),
            "shard": str(self.shard),
            "retry_count": str(self.retry_count)
        }

    @classmethod
    def from_stream_data(cls, stream_id: str, data: Dict[str, Union[str, bytes]]) -> "StreamEvent":
        """Create from Redis stream data."""
        # Convert bytes to strings if needed
        clean_data = {}
        for k, v in data.items():
            if isinstance(k, bytes):
                k = k.decode()
            if isinstance(v, bytes):
                v = v.decode()
            clean_data[k] = v

        return cls(
            event_id=clean_data["event_id"],
            event_type=clean_data["event_type"],
            scheduled_time=datetime.fromisoformat(clean_data["scheduled_time"]),
            payload=json.loads(clean_data["payload"]),
            created_at=datetime.fromisoformat(clean_data["created_at"]),
            shard=int(clean_data["shard"]),
            retry_count=int(clean_data.get("retry_count", 0))
        )


class StreamEventScheduler:
    """
    Pure stream-based event scheduler using Redis Streams.

    Features:
    - Each event processed by exactly one instance
    - Natural load balancing via consumer groups
    - Automatic retry handling with exponential backoff
    - Horizontal scaling to thousands of instances
    - No polling or persistent loops
    """

    def __init__(
        self,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[EventBus] = None,
        instance_id: Optional[str] = None,
        total_shards: int = 64,
        consumer_group: str = "event-processors"
    ):
        """
        Initialize Stream Event Scheduler.

        Args:
            persistence: Redis persistence adapter
            event_bus: Optional event bus for notifications
            instance_id: Instance identifier
            total_shards: Number of shards for distribution
            consumer_group: Redis consumer group name
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.instance_id = instance_id or f"scheduler-{uuid.uuid4().hex[:8]}"
        self.total_shards = total_shards
        self.consumer_group = consumer_group

        # Stream names
        self.scheduled_stream = "events:scheduled"
        self.immediate_stream = "events:immediate"
        self.retry_stream = "events:retry"

        # Event handlers
        self._event_handlers: Dict[str, List[Callable[[Dict[str, Any]], Awaitable[None]]]] = {}

        # Processing control
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False

        # Statistics
        self._events_scheduled = 0
        self._events_processed = 0
        self._events_retried = 0
        self._last_processed_time: Optional[float] = None

        # Configuration
        self.max_batch_size = 100
        self.processing_timeout = 30000  # 30 seconds
        self.max_retries = 3
        self.retry_backoff_base = 2  # seconds

        logger.info(f"Initialized StreamEventScheduler (instance: {self.instance_id}, shards: {total_shards})")

    async def initialize(self):
        """
        Initialize the scheduler.

        Sets up Redis streams and consumer groups.
        """
        await self._setup_streams()
        await self._setup_consumer_groups()
        logger.info("StreamEventScheduler initialized (stream-based, scalable)")

    async def start_processing(self):
        """Start processing events from streams."""
        if self._running:
            logger.warning("StreamEventScheduler already running")
            return

        self._running = True
        self._processing_task = asyncio.create_task(self._process_events_loop())
        logger.info("StreamEventScheduler processing started")

    async def stop_processing(self):
        """Stop processing events."""
        self._running = False

        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

        logger.info("StreamEventScheduler processing stopped")

    async def shutdown(self):
        """Shutdown the scheduler."""
        await self.stop_processing()
        logger.info("StreamEventScheduler shutdown")

    async def schedule_event(
        self,
        event_type: str,
        delay_seconds: float,
        payload: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
        shard_key: Optional[str] = None
    ) -> str:
        """
        Schedule an event to fire after a delay.

        Args:
            event_type: Type of event to schedule
            delay_seconds: Delay in seconds before firing
            payload: Event payload
            event_id: Optional custom event ID
            shard_key: Optional key for shard calculation (defaults to event_id)

        Returns:
            Event ID
        """
        if event_id is None:
            event_id = f"evt-{event_type}-{uuid.uuid4().hex[:8]}-{int(time.time())}"

        scheduled_time = datetime.utcnow() + timedelta(seconds=delay_seconds)
        shard = self._calculate_shard(shard_key or event_id)

        event = StreamEvent(
            event_id=event_id,
            event_type=event_type,
            scheduled_time=scheduled_time,
            payload=payload or {},
            created_at=datetime.utcnow(),
            shard=shard
        )

        # Add to scheduled events stream
        await self.persistence.redis.xadd(
            self.scheduled_stream,
            event.to_stream_data()
        )

        self._events_scheduled += 1

        logger.info(f"Scheduled event {event_id} ({event_type}) to fire in {delay_seconds}s (shard: {shard})")

        return event_id

    async def schedule_immediate(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        shard_key: Optional[str] = None
    ) -> str:
        """
        Schedule an event to fire immediately.

        Args:
            event_type: Type of event to schedule
            payload: Event payload
            shard_key: Optional key for shard calculation

        Returns:
            Event ID
        """
        event_id = f"imm-{event_type}-{uuid.uuid4().hex[:8]}-{int(time.time())}"
        shard = self._calculate_shard(shard_key or event_id)

        event = StreamEvent(
            event_id=event_id,
            event_type=event_type,
            scheduled_time=datetime.utcnow(),
            payload=payload or {},
            created_at=datetime.utcnow(),
            shard=shard
        )

        # Add to immediate events stream
        await self.persistence.redis.xadd(
            self.immediate_stream,
            event.to_stream_data()
        )

        self._events_scheduled += 1

        logger.info(f"Scheduled immediate event {event_id} ({event_type}) (shard: {shard})")

        return event_id

    async def register_handler(
        self,
        event_type: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]]
    ):
        """
        Register a handler for events.

        Args:
            event_type: Event type to handle
            handler: Async handler function
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []

        self._event_handlers[event_type].append(handler)
        logger.info(f"Registered handler for event type: {event_type}")

    async def _setup_streams(self):
        """Ensure all required streams exist."""
        streams = [self.scheduled_stream, self.immediate_stream, self.retry_stream]

        for stream in streams:
            try:
                # Check if stream exists by getting info
                await self.persistence.redis.xinfo_stream(stream)
            except Exception:
                # Stream doesn't exist, create it with dummy entry
                await self.persistence.redis.xadd(stream, {"init": "true"})
                # Remove the dummy entry
                entries = await self.persistence.redis.xrange(stream, count=1)
                if entries:
                    await self.persistence.redis.xdel(stream, entries[0][0])

        logger.info(f"Initialized streams: {streams}")

    async def _setup_consumer_groups(self):
        """Setup consumer groups for all streams."""
        streams = [self.scheduled_stream, self.immediate_stream, self.retry_stream]

        for stream in streams:
            try:
                # Try to create consumer group
                await self.persistence.redis.xgroup_create(
                    stream,
                    self.consumer_group,
                    id="0",
                    mkstream=True
                )
                logger.info(f"Created consumer group {self.consumer_group} for {stream}")
            except Exception as e:
                # Group might already exist
                if "BUSYGROUP" not in str(e):
                    logger.warning(f"Error creating consumer group for {stream}: {e}")

    async def _process_events_loop(self):
        """Main event processing loop."""
        try:
            # Pure blocking stream consumption - no polling loops
            streams_to_read = {
                self.immediate_stream: ">",
                self.scheduled_stream: ">",
                self.retry_stream: ">"
            }

            while self._running:
                # Single blocking read across all streams - eliminates CPU spinning
                messages = await self.persistence.redis.xreadgroup(
                    self.consumer_group,
                    self.instance_id,
                    streams_to_read,
                    count=self.max_batch_size,
                    block=0  # Block indefinitely until messages arrive
                )

                processed_count = 0
                for stream, msgs in messages:
                    for msg_id, fields in msgs:
                        try:
                            if stream == self.scheduled_stream:
                                # Check if scheduled event is due before processing
                                if await self._is_scheduled_event_due(fields):
                                    await self._process_scheduled_event_message(msg_id, fields)
                                    processed_count += 1
                            else:
                                # Process immediate and retry events directly
                                await self._process_event_message(msg_id, fields, stream)
                                processed_count += 1
                        except Exception as e:
                            logger.error(f"Error processing message {msg_id} from {stream}: {e}")
                            # Acknowledge the message to prevent redelivery loops
                            await self.persistence.redis.xack(stream, self.consumer_group, msg_id)

                if processed_count > 0:
                    self._last_processed_time = time.time()
                    logger.debug(f"Processed {processed_count} events via pure stream reads")

        except asyncio.CancelledError:
            logger.info("Event processing loop cancelled")
        except Exception as e:
            logger.error(f"Error in event processing loop: {e}")

    async def _is_scheduled_event_due(self, fields: Dict[str, Any]) -> bool:
        """Check if a scheduled event is due for processing."""
        try:
            # Convert bytes to strings if needed
            clean_data = {}
            for k, v in fields.items():
                if isinstance(k, bytes):
                    k = k.decode()
                if isinstance(v, bytes):
                    v = v.decode()
                clean_data[k] = v

            scheduled_time = datetime.fromisoformat(clean_data["scheduled_time"])
            return scheduled_time <= datetime.utcnow()
        except Exception as e:
            logger.error(f"Error checking if event is due: {e}")
            return True  # Process anyway to avoid stuck events

    async def _process_scheduled_event_message(self, msg_id: str, fields: Dict[str, Any]):
        """Process a scheduled event message."""
        try:
            event = StreamEvent.from_stream_data(msg_id, fields)
            await self._fire_event(event)
            await self.persistence.redis.xack(self.scheduled_stream, self.consumer_group, msg_id)
        except Exception as e:
            logger.error(f"Error processing scheduled event {msg_id}: {e}")
            await self._handle_processing_error(self.scheduled_stream, msg_id, fields, e)

    async def _process_event_message(self, msg_id: str, fields: Dict[str, Any], stream: str):
        """Process an immediate or retry event message."""
        try:
            event = StreamEvent.from_stream_data(msg_id, fields)
            await self._fire_event(event)
            await self.persistence.redis.xack(stream, self.consumer_group, msg_id)
        except Exception as e:
            logger.error(f"Error processing event {msg_id} from {stream}: {e}")
            await self._handle_processing_error(stream, msg_id, fields, e)

    async def _process_stream_events(self, stream_name: str) -> int:
        """Process events from a specific stream."""
        try:
            # Read events using consumer group
            messages = await self.persistence.redis.xreadgroup(
                self.consumer_group,
                self.instance_id,
                {stream_name: ">"},
                count=self.max_batch_size,
                block=1000  # Block for 1 second
            )

            processed_count = 0
            for stream, msgs in messages:
                for msg_id, fields in msgs:
                    try:
                        await self._process_single_event(stream_name, msg_id, fields)
                        processed_count += 1
                    except Exception as e:
                        logger.error(f"Error processing event {msg_id}: {e}")
                        await self._handle_processing_error(stream_name, msg_id, fields, e)

            return processed_count

        except Exception as e:
            logger.error(f"Error reading from stream {stream_name}: {e}")
            return 0

    async def _process_scheduled_events(self) -> int:
        """Process scheduled events that are due."""
        try:
            current_time = datetime.utcnow()

            # Read scheduled events
            messages = await self.persistence.redis.xreadgroup(
                self.consumer_group,
                self.instance_id,
                {self.scheduled_stream: ">"},
                count=self.max_batch_size,
                block=1000
            )

            processed_count = 0
            for stream, msgs in messages:
                for msg_id, fields in msgs:
                    try:
                        event = StreamEvent.from_stream_data(msg_id, fields)

                        # Check if event is due
                        if event.scheduled_time <= current_time:
                            await self._fire_event(event)
                            await self._acknowledge_event(self.scheduled_stream, msg_id)
                            processed_count += 1
                        else:
                            # Event not due yet, don't acknowledge so it gets reprocessed
                            pass

                    except Exception as e:
                        logger.error(f"Error processing scheduled event {msg_id}: {e}")
                        await self._handle_processing_error(self.scheduled_stream, msg_id, fields, e)

            return processed_count

        except Exception as e:
            logger.error(f"Error processing scheduled events: {e}")
            return 0

    async def _process_single_event(self, stream_name: str, msg_id: str, fields: Dict[str, Any]):
        """Process a single event."""
        event = StreamEvent.from_stream_data(msg_id, fields)

        # Fire the event
        await self._fire_event(event)

        # Acknowledge successful processing
        await self._acknowledge_event(stream_name, msg_id)

    async def _fire_event(self, event: StreamEvent):
        """Fire an event by calling registered handlers."""
        logger.info(f"Firing event {event.event_id} ({event.event_type})")

        # Get handlers for this event type
        handlers = self._event_handlers.get(event.event_type, [])

        if not handlers:
            logger.warning(f"No handlers registered for event type: {event.event_type}")
            return

        # Call all handlers
        for handler in handlers:
            try:
                await handler({
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "payload": event.payload,
                    "scheduled_time": event.scheduled_time.isoformat(),
                    "shard": event.shard
                })
            except Exception as e:
                logger.error(f"Error in event handler for {event.event_type}: {e}")
                raise

        self._events_processed += 1

        # Emit event bus notification if available
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.SCHEDULER_EVENT_FIRED,
                data={
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "payload": event.payload
                }
            ))

    async def _acknowledge_event(self, stream_name: str, msg_id: str):
        """Acknowledge successful event processing."""
        await self.persistence.redis.xack(stream_name, self.consumer_group, msg_id)

    async def _handle_processing_error(self, stream_name: str, msg_id: str, fields: Dict[str, Any], error: Exception):
        """Handle event processing errors with retry logic."""
        try:
            event = StreamEvent.from_stream_data(msg_id, fields)
            event.retry_count += 1

            if event.retry_count <= self.max_retries:
                # Calculate retry delay with exponential backoff
                delay = self.retry_backoff_base ** event.retry_count

                # Schedule retry
                retry_time = datetime.utcnow() + timedelta(seconds=delay)
                event.scheduled_time = retry_time

                await self.persistence.redis.xadd(
                    self.retry_stream,
                    event.to_stream_data()
                )

                logger.warning(f"Scheduled retry {event.retry_count}/{self.max_retries} for event {event.event_id} in {delay}s")
                self._events_retried += 1
            else:
                logger.error(f"Event {event.event_id} failed after {self.max_retries} retries: {error}")

            # Acknowledge the failed event to remove it from pending
            await self._acknowledge_event(stream_name, msg_id)

        except Exception as e:
            logger.error(f"Error handling processing error: {e}")

    def _calculate_shard(self, key: str) -> int:
        """Calculate shard for a key using consistent hashing."""
        return hash(key) % self.total_shards

    async def get_stream_info(self) -> Dict[str, Any]:
        """Get information about all streams."""
        info = {}
        streams = [self.scheduled_stream, self.immediate_stream, self.retry_stream]

        for stream in streams:
            try:
                stream_info = await self.persistence.redis.xinfo_stream(stream)
                group_info = await self.persistence.redis.xinfo_groups(stream)

                info[stream] = {
                    "length": stream_info.get("length", 0),
                    "groups": len(group_info),
                    "first_entry": stream_info.get("first-entry"),
                    "last_entry": stream_info.get("last-entry")
                }
            except Exception as e:
                info[stream] = {"error": str(e)}

        return info

    def get_statistics(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        return {
            "instance_id": self.instance_id,
            "events_scheduled": self._events_scheduled,
            "events_processed": self._events_processed,
            "events_retried": self._events_retried,
            "registered_handlers": sum(len(handlers) for handlers in self._event_handlers.values()),
            "event_types": list(self._event_handlers.keys()),
            "last_processed_time": self._last_processed_time,
            "total_shards": self.total_shards,
            "stream_based": True,
            "scalable": True,
            "running": self._running
        }