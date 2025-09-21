"""
Redis Event-Driven Scheduler for Stateless Architecture.

Uses Redis pub/sub and keyspace notifications to trigger processing
without any persistent loops in application instances.
"""

import asyncio
import logging
import time
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Callable, Awaitable
from dataclasses import dataclass
import uuid

from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent, EventType
from ..events import EventBus

logger = logging.getLogger(__name__)


@dataclass
class ScheduledEvent:
    """Represents a scheduled event in Redis."""
    event_id: str
    event_type: str
    scheduled_time: datetime
    payload: Dict[str, Any]
    created_at: datetime
    fired: bool = False


class RedisEventScheduler:
    """
    Pure Redis event-driven scheduler.

    Key features:
    - NO internal loops or timers
    - Uses Redis keyspace notifications for expiring events
    - Uses Redis pub/sub for immediate scheduling
    - All instances listen to same Redis events
    - Stateless and horizontally scalable
    """

    def __init__(
        self,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[EventBus] = None,
        instance_id: Optional[str] = None
    ):
        """
        Initialize Redis Event Scheduler.

        Args:
            persistence: Redis persistence adapter
            event_bus: Optional event bus for notifications
            instance_id: Instance identifier
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.instance_id = instance_id or f"scheduler-{uuid.uuid4().hex[:8]}"

        # Event handlers
        self._event_handlers: Dict[str, List[Callable[[Dict[str, Any]], Awaitable[None]]]] = {}

        # Redis pub/sub client
        self._pubsub = None
        self._subscription_task: Optional[asyncio.Task] = None

        # Statistics
        self._events_processed = 0
        self._events_scheduled = 0

        logger.info(f"Initialized RedisEventScheduler (instance: {self.instance_id})")

    async def initialize(self):
        """
        Initialize the scheduler.

        Sets up Redis keyspace notifications and pub/sub subscriptions.
        """
        # Enable Redis keyspace notifications for expiring keys
        await self._enable_keyspace_notifications()

        # Set up pub/sub subscriptions
        await self._setup_subscriptions()

        logger.info("RedisEventScheduler initialized (event-driven, no loops)")

    async def shutdown(self):
        """Shutdown the scheduler."""
        if self._subscription_task:
            self._subscription_task.cancel()
            try:
                await self._subscription_task
            except asyncio.CancelledError:
                pass

        if self._pubsub:
            await self._pubsub.close()

        logger.info("RedisEventScheduler shutdown")

    async def schedule_event(
        self,
        event_type: str,
        delay_seconds: float,
        payload: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None
    ) -> str:
        """
        Schedule an event to fire after a delay.

        Uses Redis key expiration to trigger the event.

        Args:
            event_type: Type of event to schedule
            delay_seconds: Delay in seconds before firing
            payload: Event payload
            event_id: Optional custom event ID

        Returns:
            Event ID
        """
        if event_id is None:
            event_id = f"sched-{event_type}-{uuid.uuid4().hex[:8]}-{int(time.time())}"

        scheduled_time = datetime.utcnow() + timedelta(seconds=delay_seconds)

        event = ScheduledEvent(
            event_id=event_id,
            event_type=event_type,
            scheduled_time=scheduled_time,
            payload=payload or {},
            created_at=datetime.utcnow()
        )

        # Store event details
        event_key = f"scheduler:event:{event_id}"
        await self.persistence.set(event_key, event.__dict__)

        # Create expiring trigger key - when this expires, it triggers the event
        trigger_key = f"scheduler:trigger:{event_id}"
        await self.persistence.redis.setex(trigger_key, int(delay_seconds), event_id)

        self._events_scheduled += 1

        logger.info(f"Scheduled event {event_id} ({event_type}) to fire in {delay_seconds}s")

        return event_id

    async def schedule_immediate(
        self,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Schedule an event to fire immediately via pub/sub.

        Args:
            event_type: Type of event to schedule
            payload: Event payload

        Returns:
            Event ID
        """
        event_id = f"immed-{event_type}-{uuid.uuid4().hex[:8]}-{int(time.time())}"

        event_data = {
            "event_id": event_id,
            "event_type": event_type,
            "payload": payload or {},
            "timestamp": datetime.utcnow().isoformat()
        }

        # Publish immediately via Redis pub/sub
        channel = "scheduler:immediate"
        await self.persistence.redis.publish(channel, json.dumps(event_data))

        self._events_scheduled += 1

        logger.info(f"Scheduled immediate event {event_id} ({event_type})")

        return event_id

    async def register_handler(
        self,
        event_type: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]]
    ):
        """
        Register a handler for scheduled events.

        Args:
            event_type: Event type to handle
            handler: Async handler function
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []

        self._event_handlers[event_type].append(handler)
        logger.info(f"Registered handler for event type: {event_type}")

    async def cancel_event(self, event_id: str) -> bool:
        """
        Cancel a scheduled event.

        Args:
            event_id: Event ID to cancel

        Returns:
            True if cancelled successfully
        """
        try:
            # Remove trigger key to prevent firing
            trigger_key = f"scheduler:trigger:{event_id}"
            removed = await self.persistence.redis.delete(trigger_key)

            # Mark event as cancelled
            event_key = f"scheduler:event:{event_id}"
            event_data = await self.persistence.get(event_key)
            if event_data:
                event_data["cancelled"] = True
                await self.persistence.set(event_key, event_data)

            logger.info(f"Cancelled scheduled event {event_id}")
            return removed > 0

        except Exception as e:
            logger.error(f"Error cancelling event {event_id}: {e}")
            return False

    async def _enable_keyspace_notifications(self):
        """Enable Redis keyspace notifications for expired keys."""
        try:
            # Enable keyspace notifications for expired events
            await self.persistence.redis.config_set("notify-keyspace-events", "Ex")
            logger.info("Enabled Redis keyspace notifications for expired keys")
        except Exception as e:
            logger.warning(f"Could not enable keyspace notifications: {e}")

    async def _setup_subscriptions(self):
        """Set up Redis pub/sub subscriptions."""
        try:
            self._pubsub = self.persistence.redis.pubsub()

            # Subscribe to keyspace notifications for expired trigger keys
            pattern = f"__keyevent@{self.persistence.redis.connection_pool.connection_kwargs.get('db', 0)}__:expired"
            await self._pubsub.psubscribe(pattern)

            # Subscribe to immediate events
            await self._pubsub.subscribe("scheduler:immediate")

            # Start subscription task
            self._subscription_task = asyncio.create_task(self._process_subscriptions())

            logger.info("Set up Redis pub/sub subscriptions for scheduler")

        except Exception as e:
            logger.error(f"Error setting up subscriptions: {e}")

    async def _process_subscriptions(self):
        """Process incoming Redis pub/sub messages."""
        try:
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    await self._handle_message(message)
                elif message["type"] == "pmessage":
                    await self._handle_pattern_message(message)

        except asyncio.CancelledError:
            logger.info("Subscription processing cancelled")
        except Exception as e:
            logger.error(f"Error processing subscriptions: {e}")

    async def _handle_message(self, message: Dict[str, Any]):
        """Handle direct pub/sub messages (immediate events)."""
        try:
            channel = message["channel"].decode() if isinstance(message["channel"], bytes) else message["channel"]
            data = message["data"].decode() if isinstance(message["data"], bytes) else message["data"]

            if channel == "scheduler:immediate":
                event_data = json.loads(data)
                await self._fire_event(event_data)

        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def _handle_pattern_message(self, message: Dict[str, Any]):
        """Handle pattern-matched messages (expired keys)."""
        try:
            channel = message["channel"].decode() if isinstance(message["channel"], bytes) else message["channel"]
            data = message["data"].decode() if isinstance(message["data"], bytes) else message["data"]

            # Check if this is an expired trigger key
            if channel.endswith(":expired") and data.startswith("scheduler:trigger:"):
                event_id = data.split(":")[-1]  # Extract event ID from trigger key
                await self._handle_expired_trigger(event_id)

        except Exception as e:
            logger.error(f"Error handling pattern message: {e}")

    async def _handle_expired_trigger(self, event_id: str):
        """Handle an expired trigger key by firing the associated event."""
        try:
            # Get event details
            event_key = f"scheduler:event:{event_id}"
            event_data = await self.persistence.get(event_key)

            if not event_data:
                logger.warning(f"No event data found for expired trigger: {event_id}")
                return

            if event_data.get("cancelled"):
                logger.info(f"Skipping cancelled event: {event_id}")
                return

            if event_data.get("fired"):
                logger.warning(f"Event {event_id} already fired, skipping")
                return

            # Mark as fired
            event_data["fired"] = True
            event_data["fired_at"] = datetime.utcnow().isoformat()
            await self.persistence.set(event_key, event_data)

            # Fire the event
            await self._fire_event({
                "event_id": event_id,
                "event_type": event_data["event_type"],
                "payload": event_data["payload"],
                "scheduled_time": event_data["scheduled_time"],
                "fired_at": event_data["fired_at"]
            })

        except Exception as e:
            logger.error(f"Error handling expired trigger {event_id}: {e}")

    async def _fire_event(self, event_data: Dict[str, Any]):
        """Fire an event by calling registered handlers."""
        event_type = event_data["event_type"]
        event_id = event_data["event_id"]

        logger.info(f"Firing scheduled event {event_id} ({event_type})")

        # Get handlers for this event type
        handlers = self._event_handlers.get(event_type, [])

        if not handlers:
            logger.warning(f"No handlers registered for event type: {event_type}")
            return

        # Call all handlers
        for handler in handlers:
            try:
                await handler(event_data)
            except Exception as e:
                logger.error(f"Error in event handler for {event_type}: {e}")

        self._events_processed += 1

        # Emit event bus notification if available
        if self.event_bus:
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.SCHEDULER_EVENT_FIRED,
                data=event_data
            ))

    def get_statistics(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        return {
            "instance_id": self.instance_id,
            "events_scheduled": self._events_scheduled,
            "events_processed": self._events_processed,
            "registered_handlers": sum(len(handlers) for handlers in self._event_handlers.values()),
            "event_types": list(self._event_handlers.keys()),
            "stateless": True,
            "event_driven": True
        }


class TickScheduler:
    """
    Convenience wrapper for scheduling regular tick events.

    Uses RedisEventScheduler to create tick events that trigger
    stateless component processing.
    """

    def __init__(self, redis_scheduler: RedisEventScheduler):
        """
        Initialize TickScheduler.

        Args:
            redis_scheduler: Redis event scheduler instance
        """
        self.redis_scheduler = redis_scheduler
        self._tick_handlers: List[Callable[[], Awaitable[Dict[str, Any]]]] = []

        # Register tick event handler
        asyncio.create_task(self._register_tick_handler())

    async def _register_tick_handler(self):
        """Register handler for tick events."""
        await self.redis_scheduler.register_handler("tick", self._handle_tick_event)

    async def register_tick_component(self, component: Any):
        """
        Register a component to receive ticks.

        Component must have a tick() method.
        """
        if hasattr(component, 'tick'):
            self._tick_handlers.append(component.tick)
            logger.info(f"Registered {component.__class__.__name__} for tick events")
        else:
            logger.warning(f"Component {component.__class__.__name__} has no tick() method")

    async def schedule_tick(self, delay_seconds: float = 1.0) -> str:
        """
        Schedule a single tick event.

        Args:
            delay_seconds: Delay before tick fires

        Returns:
            Event ID
        """
        return await self.redis_scheduler.schedule_event(
            event_type="tick",
            delay_seconds=delay_seconds,
            payload={"tick_time": datetime.utcnow().isoformat()}
        )

    async def schedule_recurring_ticks(
        self,
        interval_seconds: float = 1.0,
        count: Optional[int] = None
    ):
        """
        Schedule recurring tick events.

        Each tick schedules the next one, creating a chain.

        Args:
            interval_seconds: Interval between ticks
            count: Number of ticks (None for infinite)
        """
        tick_data = {
            "interval": interval_seconds,
            "remaining": count,
            "start_time": datetime.utcnow().isoformat()
        }

        await self.redis_scheduler.schedule_event(
            event_type="recurring_tick",
            delay_seconds=interval_seconds,
            payload=tick_data
        )

        # Register handler for recurring ticks
        await self.redis_scheduler.register_handler("recurring_tick", self._handle_recurring_tick)

    async def _handle_tick_event(self, event_data: Dict[str, Any]):
        """Handle a tick event by calling all tick handlers."""
        logger.debug("Processing tick event")

        # Call all registered tick handlers
        results = {}
        for handler in self._tick_handlers:
            try:
                component_name = handler.__self__.__class__.__name__ if hasattr(handler, '__self__') else "unknown"
                result = await handler()
                results[component_name] = result
            except Exception as e:
                logger.error(f"Error in tick handler: {e}")
                results[handler.__name__ if hasattr(handler, '__name__') else "unknown"] = {"error": str(e)}

        logger.debug(f"Tick processed with results: {results}")

    async def _handle_recurring_tick(self, event_data: Dict[str, Any]):
        """Handle a recurring tick event."""
        payload = event_data["payload"]
        interval = payload["interval"]
        remaining = payload.get("remaining")

        # Process this tick
        await self._handle_tick_event(event_data)

        # Schedule next tick if needed
        if remaining is None or remaining > 1:
            next_remaining = remaining - 1 if remaining is not None else None
            next_payload = {
                "interval": interval,
                "remaining": next_remaining,
                "start_time": payload["start_time"]
            }

            await self.redis_scheduler.schedule_event(
                event_type="recurring_tick",
                delay_seconds=interval,
                payload=next_payload
            )