"""
Stateless stream core mixin providing Redis Streams infrastructure without loops.
"""

import logging
from typing import Optional, Dict, Any

from ...core.errors import SystemManagerError

logger = logging.getLogger(__name__)


class StatelessStreamCoreMixin:
    """
    Mixin providing stateless Redis Streams infrastructure.

    This mixin handles:
    - Stateless event scheduler
    - Triggered stream consumer
    - No loops, no background tasks
    - Pure trigger-based processing
    """

    def __init__(self, stream_config: Optional[Dict[str, Any]] = None, **kwargs):
        """Initialize stateless stream core components."""
        # Stream configuration
        self.stream_config = stream_config or {}
        self.total_shards = self.stream_config.get("total_shards", 64)
        self.consumer_group = self.stream_config.get("consumer_group", "gleitzeit-processors")

        # Stateless components (no loops!)
        self.stateless_scheduler = None
        self.stateless_consumer = None
        self.triggered_consumer = None

        # Processing limits
        self.max_events_per_tick = self.stream_config.get("max_events_per_tick", 100)
        self.max_messages_per_tick = self.stream_config.get("max_messages_per_tick", 100)

        # Pass along kwargs to next mixin in chain
        super().__init__(**kwargs)

    async def initialize_stateless_stream_core(self):
        """Initialize stateless stream infrastructure."""
        redis_client = getattr(self.persistence, 'redis', None)
        if not redis_client:
            raise SystemManagerError("Redis is required for stateless stream-based system manager")

        try:
            logger.info("Initializing stateless stream core (NO LOOPS!)")

            # Store Redis reference for stateless operations
            self.redis_client = redis_client

            # Initialize triggered stream consumer
            await self._initialize_triggered_consumer()

            # Register tick handlers
            await self._register_tick_handlers()

            logger.info("Stateless stream core infrastructure initialized")

        except Exception as e:
            logger.error(f"Failed to initialize stateless stream core: {e}")
            raise SystemManagerError("Stateless stream core initialization failed", cause=e)

    async def _initialize_triggered_consumer(self):
        """Initialize triggered stream consumer (no loops!)."""
        # No longer needed - the StreamlinedEventBus handles everything
        logger.info("Stream processing handled by StreamlinedEventBus (no separate consumer needed)")

    async def _register_tick_handlers(self):
        """Register handlers for processing ticks."""
        # This would be called by external triggers
        logger.info("Tick handlers ready for external triggering")

    async def process_streams_once(self) -> Dict[str, Any]:
        """
        Process all streams once - NO LOOPS!
        This is called by external triggers.

        Returns:
            Processing statistics
        """
        stats = {
            "scheduler": {},
            "consumer": {},
            "errors": 0
        }

        try:
            # Process scheduled events
            from ...scheduler.stateless_scheduler import StatelessScheduler
            scheduler_result = await StatelessScheduler.process_all_once(
                self.redis_client,
                max_events=self.max_events_per_tick
            )
            stats["scheduler"] = scheduler_result

            # Process stream messages using the streamlined event bus
            if hasattr(self, 'event_bus') and self.event_bus:
                # The event bus handles everything - reading from streams and calling handlers
                bus_stats = await self.event_bus.process_once()
                stats["consumer"]["processed"] = bus_stats.get("processed", 0)
                stats["consumer"]["by_type"] = bus_stats.get("by_type", {})
                stats["errors"] += bus_stats.get("errors", 0)
            else:
                logger.warning("No event bus available for stream processing")
                stats["consumer"]["processed"] = 0

        except Exception as e:
            logger.error(f"Error in stateless stream processing: {e}")
            stats["errors"] += 1

        return stats

    async def trigger_processing(self, action: str = "consume") -> bool:
        """
        Send a trigger to process streams.

        Args:
            action: Trigger action (consume, discover, shutdown)

        Returns:
            True if trigger sent successfully
        """
        try:
            # For stateless operation, triggers aren't needed
            # External systems (K8s, Lambda, etc.) trigger process_all_once() directly
            logger.debug(f"Trigger action '{action}' noted - external systems will trigger processing")
            return True

        except Exception as e:
            logger.error(f"Failed to trigger processing: {e}")
            return False

    async def get_stream_statistics(self) -> Dict[str, Any]:
        """Get statistics about streams (no loops needed)."""
        try:
            from ...events.stateless_stream_consumer import StatelessStreamConsumer

            # Get stream info
            streams = await StatelessStreamConsumer.get_all_streams(self.redis_client)
            pending = await StatelessStreamConsumer.get_pending_info(self.redis_client)

            return {
                "total_streams": len(streams),
                "streams_with_pending": len(pending),
                "total_pending": sum(pending.values()),
                "consumer_group": self.consumer_group,
                "stateless": True,
                "has_loops": False
            }

        except Exception as e:
            logger.error(f"Error getting stream statistics: {e}")
            return {}

    async def shutdown_stateless_stream_core(self):
        """Shutdown stateless stream core (no loops to stop!)."""
        logger.info("Stateless stream core shutdown (no loops to stop)")

        # Send shutdown trigger if needed
        await self.trigger_processing("shutdown")