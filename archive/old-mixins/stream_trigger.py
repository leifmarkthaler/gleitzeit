"""
Stream trigger mixin for Redis-triggered event consumption.
"""

import asyncio
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class StreamTriggerMixin:
    """
    Mixin providing Redis-triggered stream consumption.

    This mixin replaces the traditional loop-based consumption with
    a trigger-based approach where Redis itself drives consumption.
    """

    def __init__(self, **kwargs):
        """Initialize trigger components."""
        self.triggered_consumer = None
        self.trigger_scheduler = None
        self._trigger_task = None
        self._auto_trigger_enabled = False

        super().__init__(**kwargs)

    async def initialize_triggered_consumer(self):
        """Initialize the triggered stream consumer."""
        try:
            from ...events.triggered_stream_consumer import TriggeredStreamConsumer

            # Create triggered consumer
            self.triggered_consumer = TriggeredStreamConsumer(
                redis=self.persistence.redis,
                handlers_registry=self.event_handlers,
                consumer_group=f"{self.consumer_group}-events",
                consumer_id=f"{self.instance_id}-consumer",
                instance_id=self.instance_id
            )

            # Setup trigger stream
            await self.triggered_consumer.setup_trigger_stream()

            # Discover initial streams
            await self.triggered_consumer.discover_streams()
            await self.triggered_consumer.ensure_consumer_groups()

            logger.info("TriggeredStreamConsumer initialized")

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="triggered_consumer",
                    component_type="consumer",
                    metadata={
                        "instance_id": self.instance_id,
                        "consumer_group": f"{self.consumer_group}-events",
                        "trigger_based": True
                    }
                )

        except Exception as e:
            logger.error(f"Failed to initialize triggered consumer: {e}")
            raise

    async def start_trigger_processor(self):
        """
        Start processing triggers for consumption.

        This replaces the old loop-based consumer.
        """
        if not self.triggered_consumer:
            logger.warning("No triggered consumer to start")
            return

        try:
            # Register all handlers with the consumer
            if self.event_handlers:
                for event_type, handlers in self.event_handlers.items():
                    for handler in handlers:
                        self.triggered_consumer.register_handler(event_type, handler)
                logger.info(f"Registered {len(self.event_handlers)} event types with triggered consumer")

            # Start trigger processing task
            self._trigger_task = asyncio.create_task(self._process_triggers())
            logger.info("Trigger processor started")

            # Send initial trigger to process any pending messages
            await self.triggered_consumer.trigger_consumption("consume", {"reason": "startup"})

        except Exception as e:
            logger.error(f"Failed to start trigger processor: {e}")
            raise

    async def _process_triggers(self):
        """
        Process consumption triggers.

        This task waits for triggers and processes messages accordingly.
        No loops - just waiting for Redis triggers!
        """
        logger.info("Starting trigger processor")

        try:
            while True:
                # Wait for trigger and process
                result = await self.triggered_consumer.process_with_trigger()

                if result == -1:  # Shutdown trigger
                    logger.info("Received shutdown trigger")
                    break
                elif result > 0:
                    logger.debug(f"Processed {result} messages from trigger")

                # If messages were processed, check for more
                if result > 0:
                    # Auto-trigger if more messages are available
                    await asyncio.sleep(0.1)  # Brief yield
                    await self.triggered_consumer.trigger_consumption("consume", {"reason": "continuation"})

        except asyncio.CancelledError:
            logger.info("Trigger processor cancelled")
        except Exception as e:
            logger.error(f"Error in trigger processor: {e}")

        logger.info("Trigger processor stopped")

    async def trigger_event_consumption(self, reason: str = "manual"):
        """
        Manually trigger event consumption.

        This can be called by any component to trigger processing.

        Args:
            reason: Reason for triggering
        """
        if self.triggered_consumer:
            await self.triggered_consumer.trigger_consumption("consume", {"reason": reason})
            logger.debug(f"Triggered consumption: {reason}")

    async def enable_auto_triggers(self):
        """
        Enable automatic triggering based on stream activity.

        This uses Redis Streams metadata to detect when new messages arrive.
        """
        self._auto_trigger_enabled = True

        # Use the scheduler if available to periodically check
        if hasattr(self, 'event_scheduler') and self.event_scheduler:
            from ...core.events import GleitzeitEvent, EventType
            from datetime import datetime

            # Schedule periodic trigger checks
            async def check_and_trigger():
                if self.triggered_consumer and self._auto_trigger_enabled:
                    triggered = await self.triggered_consumer.auto_trigger_on_stream_activity()
                    if triggered:
                        logger.debug("Auto-triggered consumption based on stream activity")

            # Schedule every second
            await self.event_scheduler.schedule_event(
                event=GleitzeitEvent(
                    event_type=EventType.CUSTOM,
                    data={"action": "check_streams"},
                    timestamp=datetime.utcnow()
                ),
                delay_seconds=1,
                recurring=True,
                handler=check_and_trigger
            )

            logger.info("Auto-triggers enabled via scheduler")

    async def shutdown_triggered_consumer(self):
        """Shutdown the triggered consumer."""
        logger.info("Shutting down triggered consumer")

        try:
            # Disable auto-triggers
            self._auto_trigger_enabled = False

            # Send shutdown trigger
            if self.triggered_consumer:
                await self.triggered_consumer.trigger_consumption("shutdown", {"source": "system"})

            # Cancel trigger processor
            if self._trigger_task:
                self._trigger_task.cancel()
                try:
                    await self._trigger_task
                except asyncio.CancelledError:
                    pass

            self.triggered_consumer = None

        except Exception as e:
            logger.error(f"Error shutting down triggered consumer: {e}")

        logger.info("Triggered consumer shutdown complete")

    # Hook into event emission to trigger consumption
    async def emit_and_trigger(self, event: 'GleitzeitEvent') -> str:
        """
        Emit an event and trigger consumption.

        This ensures that when events are emitted, consumption is triggered.
        """
        # Emit the event normally
        msg_id = await self.event_bus.emit(event) if hasattr(self, 'event_bus') else None

        # Trigger consumption for this event type
        if self.triggered_consumer and self._auto_trigger_enabled:
            await self.triggered_consumer.trigger_consumption(
                "consume",
                {"reason": "event_emitted", "event_type": event.event_type.value if event.event_type else ""}
            )

        return msg_id