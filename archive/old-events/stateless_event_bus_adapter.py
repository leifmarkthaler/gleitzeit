"""
Stateless Event Bus Adapter - Drop-in replacement for StreamEventBus.

This adapter provides backward compatibility with the StreamEventBus interface
while using the new stateless architecture underneath.
"""

import asyncio
import logging
import json
import uuid
import os
from typing import Dict, List, Callable, Optional, Any, Union
from datetime import datetime

from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.events.stateless_stream_consumer import StatelessStreamConsumer
from gleitzeit.events.external_triggers import TimerTrigger
from gleitzeit.core.idempotency import IdempotencyManager, IdempotencyStrategy

logger = logging.getLogger(__name__)


class StatelessEventBusAdapter:
    """
    Adapter that provides StreamEventBus interface using StatelessEventConsumer.

    This allows existing code to work unchanged while using the new stateless
    architecture underneath. No persistent loops!
    """

    def __init__(
        self,
        redis_client,
        scheduler = None,
        event_store=None,
        consumer_group: str = "gleitzeit-workers",  # Will be made instance-specific
        consumer_id: Optional[str] = None,
        max_retries: int = 3,
        claim_idle_time: int = 60000,
        validate_event_types: bool = True
    ):
        """
        Initialize with StreamEventBus-compatible interface.

        Args:
            redis_client: Redis client instance
            scheduler: Event scheduler for trigger operations
            event_store: Optional EventStore (for compatibility)
            consumer_group: Base name for consumer group (will be made unique)
            consumer_id: Consumer ID (auto-generated if None)
            max_retries: Maximum retries (compatibility parameter)
            claim_idle_time: Idle time before claiming (ms)
            validate_event_types: Whether to validate event types
        """
        self.redis = redis_client
        self.scheduler = scheduler
        self.event_store = event_store
        self.base_consumer_group = consumer_group
        self.max_retries = max_retries
        self.claim_idle_time = claim_idle_time
        self.validate_event_types = validate_event_types

        # Generate unique instance ID to prevent collision
        self.instance_id = os.environ.get(
            "GLEITZEIT_INSTANCE_ID",
            f"instance_{uuid.uuid4().hex[:8]}"
        )

        # Create stateless consumer with instance-specific group
        self.consumer = StatelessEventConsumer(
            redis_client=redis_client,
            instance_id=self.instance_id,
            consumer_group_prefix=consumer_group.replace("-workers", ""),
            idempotency_manager=IdempotencyManager(redis_client)
        )

        # For compatibility - store but don't use
        self.consumer_id = consumer_id or self.consumer.consumer_id

        # Handler registry for compatibility
        self._handlers: Dict[str, List[Callable]] = {}

        # NO _running flag! Stateless!
        self._consumer_task: Optional[asyncio.Task] = None
        self._trigger_task: Optional[asyncio.Task] = None

        # Timer trigger for periodic processing
        self.timer_trigger = TimerTrigger(
            consumer=self.consumer,
            redis=redis_client
        )

        logger.info(
            f"Initialized StatelessEventBusAdapter "
            f"(instance: {self.instance_id}, "
            f"group: {self.consumer.consumer_group})"
        )

    def _normalize_event_type(self, event_type: Union[str, EventType]) -> str:
        """Normalize event type (compatibility method)."""
        if isinstance(event_type, EventType):
            return event_type.value
        elif hasattr(event_type, 'value'):
            return event_type.value
        return str(event_type)

    async def initialize(self):
        """Initialize (compatibility method)."""
        await self.start()

    async def start(self):
        """
        Start the event bus.

        NOTE: This does NOT start any loops!
        It only initializes the consumer with TTL registration.
        Processing must be triggered externally via process_once().
        """
        logger.info("Starting StatelessEventBusAdapter (truly stateless!)")

        # Initialize consumer lifecycle
        await self.consumer.initialize()

        # NO LOOPS! Processing must be triggered externally
        logger.info(
            f"StatelessEventBusAdapter initialized - ready for external triggers "
            f"(NO loops running!)"
        )

    async def stop(self):
        """Stop the event bus."""
        logger.info("Stopping StatelessEventBusAdapter")

        # Cancel trigger task
        if self._trigger_task:
            self._trigger_task.cancel()
            try:
                await self._trigger_task
            except asyncio.CancelledError:
                pass

        # Shutdown consumer
        await self.consumer.shutdown()

        logger.info("StatelessEventBusAdapter stopped")

    async def _handle_trigger_event(self, event_data: Dict) -> Dict[str, Any]:
        """Handle trigger event from scheduler."""
        try:
            trigger_interval = float(os.environ.get("GLEITZEIT_TRIGGER_INTERVAL", "1"))
            logger.debug(f"Processing trigger event for {self.instance_id}")

            # Use timer trigger to coordinate between instances
            triggered = await self.timer_trigger.check_and_trigger(
                trigger_key=f"gleitzeit:triggers:{self.base_consumer_group}",
                interval_seconds=int(trigger_interval)
            )

            if triggered:
                logger.debug(f"Trigger executed by {self.instance_id}")

            # Schedule next trigger event
            if self.scheduler:
                event_name = f"event_bus_trigger_{self.instance_id}"
                await self.scheduler.schedule_event(event_name, trigger_interval)

            return {
                "instance_id": self.instance_id,
                "triggered": triggered,
                "next_trigger_in": trigger_interval
            }

        except Exception as e:
            logger.error(f"Error in trigger event handler: {e}")
            # Still schedule next trigger
            if self.scheduler:
                trigger_interval = float(os.environ.get("GLEITZEIT_TRIGGER_INTERVAL", "1"))
                event_name = f"event_bus_trigger_{self.instance_id}"
                await self.scheduler.schedule_event(event_name, trigger_interval)
            return {"error": str(e), "instance_id": self.instance_id}

    async def start_trigger_loop(self):
        """Start event-driven trigger processing."""
        if self.scheduler:
            trigger_interval = float(os.environ.get("GLEITZEIT_TRIGGER_INTERVAL", "1"))
            event_name = f"event_bus_trigger_{self.instance_id}"
            await self.scheduler.register_handler(event_name, self._handle_trigger_event)
            await self.scheduler.schedule_event(event_name, trigger_interval)
            logger.info(f"Started event-driven trigger for {self.instance_id}")
        else:
            logger.warning(f"No scheduler available for {self.instance_id} - trigger disabled")

    def register(
        self,
        event_type: Union[str, EventType],
        handler: Callable,
        idempotency_strategy: IdempotencyStrategy = IdempotencyStrategy.CHECK_STATE
    ):
        """
        Register event handler (compatibility method).

        Args:
            event_type: Event type to handle
            handler: Handler function
            idempotency_strategy: Strategy for idempotency
        """
        normalized_type = self._normalize_event_type(event_type)

        # Store in local registry for compatibility
        if normalized_type not in self._handlers:
            self._handlers[normalized_type] = []
        self._handlers[normalized_type].append(handler)

        # Register with stateless consumer
        asyncio.create_task(
            self.consumer.register_handler(
                normalized_type,
                handler,
                idempotency_strategy
            )
        )

        logger.info(
            f"Registered handler for {normalized_type} "
            f"with {idempotency_strategy.value} strategy"
        )

    async def register_handler(
        self,
        event_type: Union[str, EventType],
        handler: Callable,
        priority: int = 2,
        filter_expr: Optional[str] = None,
        once: bool = False
    ) -> str:
        """
        Register event handler (async compatibility method for EventBus interface).

        Args:
            event_type: Event type to handle
            handler: Handler function
            priority: Priority level (ignored for compatibility)
            filter_expr: Filter expression (ignored for compatibility)
            once: Whether to run only once (ignored for compatibility)

        Returns:
            Handler ID
        """
        # Use the existing register method
        self.register(event_type, handler)

        # Return a synthetic handler ID
        normalized_type = self._normalize_event_type(event_type)
        handler_id = f"{normalized_type}:{id(handler)}"
        return handler_id

    def unregister(self, event_type: Union[str, EventType], handler: Callable):
        """Unregister event handler (compatibility method)."""
        normalized_type = self._normalize_event_type(event_type)

        if normalized_type in self._handlers:
            if handler in self._handlers[normalized_type]:
                self._handlers[normalized_type].remove(handler)
                logger.info(f"Unregistered handler for {normalized_type}")

    async def emit(self, event: GleitzeitEvent) -> str:
        """
        Emit an event (compatibility method).

        Args:
            event: Event to emit

        Returns:
            Message ID
        """
        # Convert to stream format
        stream_data = {
            "event_type": event.event_type.value if event.event_type else "",
            "timestamp": event.timestamp.isoformat() if event.timestamp else datetime.utcnow().isoformat(),
            "data": json.dumps(event.data),
            "source": event.source or "",
            "correlation_id": event.correlation_id or "",
            "severity": event.severity.value if event.severity else "INFO",
            "metadata": json.dumps(event.tags or {})
        }

        # Get stream key
        stream_key = self.consumer._get_stream_key(stream_data["event_type"])

        # Add to stream
        msg_id = await self.redis.xadd(stream_key, stream_data)

        # Store in event store if configured
        if self.event_store:
            await self.event_store.save_event(event)

        logger.debug(f"Emitted event {stream_data['event_type']} to {stream_key}")
        return msg_id

    async def process_once(self) -> int:
        """
        Process messages once (no loop).

        This can be called manually for testing or by external triggers.

        Returns:
            Number of messages processed
        """
        return await self.consumer.process_batch(
            max_messages=100,
            block_ms=100
        )

    async def claim_idle_once(self) -> int:
        """
        Claim idle messages once (no loop).

        Returns:
            Number of messages claimed
        """
        return await self.consumer.claim_idle_messages(
            idle_time_ms=self.claim_idle_time,
            max_messages=100
        )

    # Compatibility properties
    @property
    def running(self) -> bool:
        """Check if running (compatibility)."""
        return self._trigger_task is not None and not self._trigger_task.done()

    # Additional helper methods for migration
    async def get_consumer_stats(self) -> Dict[str, Any]:
        """Get consumer statistics."""
        if hasattr(self.consumer.lifecycle, 'get_consumer_stats'):
            return await self.consumer.lifecycle.get_consumer_stats()
        return {
            "instance_id": self.instance_id,
            "consumer_group": self.consumer.consumer_group,
            "handlers_registered": len(self._handlers)
        }


# Alias for drop-in replacement
StreamEventBus = StatelessEventBusAdapter