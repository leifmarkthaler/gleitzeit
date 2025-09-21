"""
Pure Stream-based Timer Manager.

High-performance timer management using Redis Streams with consumer groups
for enterprise-scale distributed timer processing.
"""

import asyncio
import logging
import time
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field

from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent, EventType
from ..events import EventBus
from ..core.models import Task, TaskStatus
from ..scheduler.stream_event_scheduler import StreamEventScheduler
from ..scheduler.consumer_group_manager import ConsumerGroupManager

logger = logging.getLogger(__name__)


@dataclass
class StreamTimer:
    """Represents a timer in the stream system."""
    timer_id: str
    workflow_id: str
    task_id: Optional[str] = None
    scheduled_time: datetime = field(default_factory=datetime.utcnow)
    duration_seconds: float = 0
    timer_type: str = "delay"  # delay, schedule, recurring
    payload: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, fired, cancelled
    created_at: datetime = field(default_factory=datetime.utcnow)
    fired_at: Optional[datetime] = None
    shard: int = 0

    def to_stream_data(self) -> Dict[str, str]:
        """Convert to Redis stream format."""
        return {
            "timer_id": self.timer_id,
            "workflow_id": self.workflow_id,
            "task_id": self.task_id or "",
            "scheduled_time": self.scheduled_time.isoformat(),
            "duration_seconds": str(self.duration_seconds),
            "timer_type": self.timer_type,
            "payload": json.dumps(self.payload),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "fired_at": self.fired_at.isoformat() if self.fired_at else "",
            "shard": str(self.shard)
        }

    @classmethod
    def from_stream_data(cls, data: Dict[str, Any]) -> "StreamTimer":
        """Create from Redis stream data."""
        # Convert bytes to strings if needed
        clean_data = {}
        for k, v in data.items():
            if isinstance(k, bytes):
                k = k.decode()
            if isinstance(v, bytes):
                v = v.decode()
            clean_data[k] = v

        # Check required fields
        if "timer_id" not in clean_data:
            raise ValueError(f"Missing required field 'timer_id' in timer data: {clean_data.keys()}")
        if "workflow_id" not in clean_data:
            raise ValueError(f"Missing required field 'workflow_id' in timer data: {clean_data.keys()}")

        return cls(
            timer_id=clean_data["timer_id"],
            workflow_id=clean_data["workflow_id"],
            task_id=clean_data.get("task_id") if clean_data.get("task_id") else None,
            scheduled_time=datetime.fromisoformat(clean_data.get("scheduled_time", datetime.utcnow().isoformat())),
            duration_seconds=float(clean_data.get("duration_seconds", 0)),
            timer_type=clean_data.get("timer_type", "delay"),
            payload=json.loads(clean_data.get("payload", "{}")),
            status=clean_data.get("status", "pending"),
            created_at=datetime.fromisoformat(clean_data.get("created_at", datetime.utcnow().isoformat())),
            fired_at=datetime.fromisoformat(clean_data["fired_at"]) if clean_data.get("fired_at") else None,
            shard=int(clean_data.get("shard", 0))
        )


class StreamTimerManager:
    """
    Pure stream-based timer manager using Redis Streams.

    Features:
    - Each timer processed by exactly one instance
    - Natural load balancing via consumer groups
    - Automatic retry handling for failed timers
    - Horizontal scaling to thousands of instances
    - Event-driven processing (no polling loops)
    """

    def __init__(
        self,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[EventBus] = None,
        instance_id: Optional[str] = None,
        total_shards: int = 64,
        consumer_group: str = "timer-processors"
    ):
        """
        Initialize Stream Timer Manager.

        Args:
            persistence: Persistence backend
            event_bus: Event bus for timer events
            instance_id: Instance identifier
            total_shards: Number of shards for distribution
            consumer_group: Redis consumer group name
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.instance_id = instance_id or f"timer-manager-{uuid.uuid4().hex[:8]}"
        self.total_shards = total_shards
        self.consumer_group = consumer_group

        # Stream names
        self.timer_stream = "timers:scheduled"
        self.timer_immediate_stream = "timers:immediate"
        self.timer_retry_stream = "timers:retry"

        # Initialize stream scheduler for timer events
        self.stream_scheduler = StreamEventScheduler(
            persistence=persistence,
            event_bus=event_bus,
            instance_id=f"{instance_id}-scheduler",
            total_shards=total_shards,
            consumer_group=f"{consumer_group}-events"
        )

        # Consumer group manager
        self.consumer_manager = ConsumerGroupManager(
            persistence=persistence,
            consumer_group=consumer_group
        )

        # Processing control
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False

        # Statistics
        self._timers_created = 0
        self._timers_fired = 0
        self._timers_cancelled = 0
        self._last_processed_time: Optional[float] = None

        # Configuration
        self.max_batch_size = 100
        self.processing_timeout = 30000  # 30 seconds
        self.max_retries = 3

        # Always distributed and event-driven
        self.distributed = True

        logger.info(f"Initialized StreamTimerManager (instance: {self.instance_id}, shards: {total_shards})")

    async def initialize(self):
        """Initialize the timer manager."""
        # Initialize stream scheduler
        await self.stream_scheduler.initialize()

        # Setup streams and consumer groups
        await self._setup_streams()

        # Start consumer group monitoring
        await self.consumer_manager.start_monitoring()

        # Register timer event handler with stream scheduler
        await self.stream_scheduler.register_handler("timer_due", self._handle_timer_event)

        logger.info("StreamTimerManager initialized (stream-based, scalable)")

    async def start_processing(self):
        """Start processing timers from streams."""
        if self._running:
            logger.warning("StreamTimerManager already running")
            return

        self._running = True

        # Start stream scheduler processing
        await self.stream_scheduler.start_processing()

        # Start timer processing
        self._processing_task = asyncio.create_task(self._process_timers_loop())

        logger.info("StreamTimerManager processing started")

    async def stop_processing(self):
        """Stop processing timers."""
        self._running = False

        # Stop stream scheduler
        await self.stream_scheduler.stop_processing()

        # Stop timer processing
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

        logger.info("StreamTimerManager processing stopped")

    async def shutdown(self):
        """Shutdown the timer manager."""
        await self.stop_processing()
        await self.consumer_manager.stop_monitoring()
        await self.stream_scheduler.shutdown()
        logger.info("StreamTimerManager shutdown")

    async def create_timer(
        self,
        workflow_id: str,
        duration_seconds: float,
        task_id: Optional[str] = None,
        timer_type: str = "delay",
        payload: Optional[Dict[str, Any]] = None
    ) -> StreamTimer:
        """
        Create a new timer.

        Args:
            workflow_id: Workflow ID
            duration_seconds: Duration in seconds
            task_id: Optional task ID
            timer_type: Type of timer (delay, schedule, recurring)
            payload: Additional data

        Returns:
            Created timer
        """
        timer_id = f"timer-{workflow_id}-{uuid.uuid4().hex[:8]}-{int(time.time())}"
        scheduled_time = datetime.utcnow() + timedelta(seconds=duration_seconds)
        shard = self._calculate_shard(workflow_id)

        timer = StreamTimer(
            timer_id=timer_id,
            workflow_id=workflow_id,
            task_id=task_id,
            scheduled_time=scheduled_time,
            duration_seconds=duration_seconds,
            timer_type=timer_type,
            payload=payload or {},
            status="pending",
            shard=shard
        )

        # Schedule timer event using stream scheduler
        await self.stream_scheduler.schedule_event(
            event_type="timer_due",
            delay_seconds=duration_seconds,
            payload={
                "timer_data": timer.to_stream_data(),
                "timer_id": timer_id,
                "workflow_id": workflow_id
            },
            shard_key=workflow_id
        )

        # Store timer metadata
        timer_key = f"timer:meta:{timer_id}"
        await self.persistence.set(timer_key, timer.to_stream_data())

        self._timers_created += 1

        logger.info(f"Created timer {timer_id} scheduled for {scheduled_time} (shard: {shard})")

        # Emit timer created event
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TIMER_CREATED,
                data={
                    "timer_id": timer_id,
                    "workflow_id": workflow_id,
                    "task_id": task_id,
                    "scheduled_time": scheduled_time.isoformat(),
                    "duration_seconds": duration_seconds
                }
            ))

        return timer

    async def cancel_timer(self, timer_id: str) -> bool:
        """
        Cancel a timer.

        Note: For stream-based timers, cancellation works by adding
        a cancellation event to be processed.

        Args:
            timer_id: Timer ID to cancel

        Returns:
            True if cancellation was scheduled
        """
        try:
            # Get timer metadata
            timer_key = f"timer:meta:{timer_id}"
            timer_data = await self.persistence.get(timer_key)

            if not timer_data:
                logger.warning(f"Timer {timer_id} not found for cancellation")
                return False

            # Update timer status
            timer_data["status"] = "cancelled"
            await self.persistence.set(timer_key, timer_data)

            # Add cancellation event to immediate stream
            await self.stream_scheduler.schedule_immediate(
                event_type="timer_cancel",
                payload={
                    "timer_id": timer_id,
                    "workflow_id": timer_data.get("workflow_id")
                }
            )

            self._timers_cancelled += 1

            logger.info(f"Scheduled cancellation for timer {timer_id}")

            # Emit cancellation event
            if self.event_bus:
                await self.event_bus.emit(GleitzeitEvent(
                    event_type=EventType.TIMER_CANCELLED,
                    data={
                        "timer_id": timer_id,
                        "workflow_id": timer_data.get("workflow_id")
                    }
                ))

            return True

        except Exception as e:
            logger.error(f"Error cancelling timer {timer_id}: {e}")
            return False

    async def _setup_streams(self):
        """Setup timer streams and consumer groups."""
        streams = [self.timer_stream, self.timer_immediate_stream, self.timer_retry_stream]

        # Initialize streams if they don't exist
        for stream in streams:
            try:
                # Try to get stream info - will fail if stream doesn't exist
                await self.persistence.redis.xinfo_stream(stream)
                logger.debug(f"Stream {stream} already exists")
            except Exception as e:
                if "no such key" in str(e).lower():
                    # Stream doesn't exist, create it with an initialization message
                    try:
                        await self.persistence.redis.xadd(
                            stream,
                            {"initialized": "true", "timestamp": str(time.time())},
                            maxlen=1  # Keep only the init message
                        )
                        logger.info(f"Created timer stream: {stream}")
                    except Exception as create_error:
                        logger.error(f"Failed to create stream {stream}: {create_error}")
                else:
                    logger.error(f"Error checking stream {stream}: {e}")

        # Now create consumer groups
        for stream in streams:
            await self.consumer_manager.ensure_consumer_group(stream, self.consumer_group)

        logger.info(f"Setup timer streams: {streams}")

    async def _process_timers_loop(self):
        """Main timer processing loop with pure blocking stream reads."""
        try:
            while self._running:
                # Block on multiple streams simultaneously - zero-polling approach
                streams = {
                    self.timer_immediate_stream: ">",
                    self.timer_retry_stream: ">"
                }

                messages = await self.persistence.redis.xreadgroup(
                    self.consumer_group,
                    self.instance_id,
                    streams,
                    count=self.max_batch_size,
                    block=0  # Block indefinitely until messages arrive
                )

                processed_count = 0
                for stream_name, msgs in messages:
                    stream_name = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
                    for msg_id, fields in msgs:
                        try:
                            await self._process_timer_message(stream_name, msg_id, fields)
                            processed_count += 1
                        except Exception as e:
                            logger.error(f"Error processing timer message {msg_id}: {e}")

                # Update statistics
                if processed_count > 0:
                    self._last_processed_time = time.time()

        except asyncio.CancelledError:
            logger.info("Timer processing loop cancelled")
        except Exception as e:
            logger.error(f"Error in timer processing loop: {e}")

    async def _process_timer_stream(self, stream_name: str) -> int:
        """Process timer events from a specific stream."""
        try:
            # Read timer events using consumer group
            messages = await self.persistence.redis.xreadgroup(
                self.consumer_group,
                self.instance_id,
                {stream_name: ">"},
                count=self.max_batch_size,
                block=1000
            )

            processed_count = 0
            for stream, msgs in messages:
                for msg_id, fields in msgs:
                    try:
                        await self._process_timer_message(stream_name, msg_id, fields)
                        processed_count += 1
                    except Exception as e:
                        logger.error(f"Error processing timer message {msg_id}: {e}")

            return processed_count

        except Exception as e:
            logger.error(f"Error reading from timer stream {stream_name}: {e}")
            return 0

    async def _process_timer_message(self, stream_name: str, msg_id: str, fields: Dict[str, Any]):
        """Process a single timer message."""
        timer = StreamTimer.from_stream_data(fields)

        # Check if timer is cancelled
        if timer.status == "cancelled":
            logger.info(f"Skipping cancelled timer {timer.timer_id}")
            await self._acknowledge_message(stream_name, msg_id)
            return

        # Fire the timer
        await self._fire_timer(timer)

        # Acknowledge successful processing
        await self._acknowledge_message(stream_name, msg_id)

    async def _handle_timer_event(self, event_data: Dict[str, Any]):
        """Handle timer events from stream scheduler."""
        timer_data = event_data.get("payload", {}).get("timer_data", {})
        timer_id = event_data.get("payload", {}).get("timer_id")

        if not timer_data:
            logger.warning(f"No timer data in event: {event_data}")
            return

        # Check if timer is still valid (not cancelled)
        timer_key = f"timer:meta:{timer_id}"
        current_timer_data = await self.persistence.get(timer_key)

        if not current_timer_data:
            logger.warning(f"Timer {timer_id} metadata not found")
            return

        if current_timer_data.get("status") == "cancelled":
            logger.info(f"Skipping cancelled timer {timer_id}")
            return

        # Create timer object and fire it
        timer = StreamTimer.from_stream_data(timer_data)
        await self._fire_timer(timer)

    async def _fire_timer(self, timer: StreamTimer):
        """Fire a timer and emit events."""
        logger.info(f"Firing timer {timer.timer_id} for workflow {timer.workflow_id}")

        # Update timer status
        timer.status = "fired"
        timer.fired_at = datetime.utcnow()

        # Update metadata
        timer_key = f"timer:meta:{timer.timer_id}"
        await self.persistence.set(timer_key, timer.to_stream_data())

        self._timers_fired += 1

        # Emit timer fired event
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TIMER_FIRED,
                data={
                    "timer_id": timer.timer_id,
                    "workflow_id": timer.workflow_id,
                    "task_id": timer.task_id,
                    "payload": timer.payload
                }
            ))

        # Handle recurring timers
        if timer.timer_type == "recurring":
            # Create next occurrence
            await self.create_timer(
                workflow_id=timer.workflow_id,
                duration_seconds=timer.duration_seconds,
                task_id=timer.task_id,
                timer_type="recurring",
                payload=timer.payload
            )

    async def _acknowledge_message(self, stream_name: str, msg_id: str):
        """Acknowledge successful message processing."""
        await self.persistence.redis.xack(stream_name, self.consumer_group, msg_id)

    def _calculate_shard(self, key: str) -> int:
        """Calculate shard for a key using consistent hashing."""
        return hash(key) % self.total_shards

    async def get_stream_info(self) -> Dict[str, Any]:
        """Get information about timer streams."""
        info = {}
        streams = [self.timer_stream, self.timer_immediate_stream, self.timer_retry_stream]

        for stream in streams:
            stream_info = await self.consumer_manager.get_stream_info(stream)
            if stream_info:
                info[stream] = {
                    "length": stream_info.length,
                    "groups": stream_info.groups,
                    "first_entry": stream_info.first_entry_id,
                    "last_entry": stream_info.last_entry_id
                }

                # Get pending summary
                pending = await self.consumer_manager.get_pending_summary(stream, self.consumer_group)
                info[stream]["pending"] = pending

        return info

    def get_statistics(self) -> Dict[str, Any]:
        """Get timer manager statistics."""
        return {
            "instance_id": self.instance_id,
            "timers_created": self._timers_created,
            "timers_fired": self._timers_fired,
            "timers_cancelled": self._timers_cancelled,
            "last_processed_time": self._last_processed_time,
            "total_shards": self.total_shards,
            "consumer_group": self.consumer_group,
            "stream_based": True,
            "scalable": True,
            "running": self._running,
            "tick_based": False,  # No longer tick-based
            "has_loops": False
        }

