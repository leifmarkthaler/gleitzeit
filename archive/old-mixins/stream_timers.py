"""
Stream timers mixin providing timer management via Redis Streams.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class StreamTimersMixin:
    """
    Mixin providing stream-based timer management.

    This mixin handles:
    - Stream-based timer manager
    - Timer provider registration
    - Timer event processing
    """

    def __init__(self, **kwargs):
        """Initialize timer components."""
        self.timer_manager = None
        super().__init__(**kwargs)

    async def initialize_stream_timers(self):
        """Initialize stream-based timer manager."""
        redis_client = getattr(self.persistence, 'redis', None)
        if not redis_client:
            logger.warning("Redis not available - timer manager disabled")
            return

        try:
            from ...timers.stream_timer_manager import StreamTimerManager

            # Get stream configuration
            total_shards = getattr(self, 'total_shards', 64)
            consumer_group = getattr(self, 'consumer_group', 'gleitzeit-processors')

            self.timer_manager = StreamTimerManager(
                persistence=self.persistence,
                event_bus=self.event_bus,
                instance_id=f"{self.instance_id}-timers",
                total_shards=total_shards,
                consumer_group=f"{consumer_group}-timers"
            )
            await self.timer_manager.initialize()
            await self.timer_manager.start_processing()

            # Register timer/v1 protocol if registry is available
            if hasattr(self, 'registry') and self.registry:
                await self.registry.register_provider_in_persistence(
                    "timer/v1",
                    {
                        "provider_id": "stream_timer_manager",
                        "instance_id": self.instance_id,
                        "capabilities": ["timer/wait", "timer/schedule", "timer/cancel"],
                        "stream_based": True
                    }
                )
                logger.info("Registered timer/v1 protocol in StatelessProtocolRegistry")

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="timer_manager",
                    component_type="service",
                    metadata={
                        "instance_id": self.instance_id,
                        "stream_based": True,
                        "total_shards": total_shards,
                        "consumer_group": f"{consumer_group}-timers"
                    }
                )

            # Register event handlers with stream manager if possible
            if hasattr(self, 'register_stream_handler'):
                # Timer manager can register its own handlers here
                pass

            logger.info("StreamTimerManager initialized and started")

        except Exception as e:
            logger.error(f"Failed to initialize timer manager: {e}")
            self.timer_manager = None

    async def shutdown_stream_timers(self):
        """Shutdown stream-based timer manager."""
        if self.timer_manager:
            try:
                await self.timer_manager.shutdown()
                logger.info("StreamTimerManager shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down timer manager: {e}")

    def get_timer_statistics(self) -> Optional[Dict[str, Any]]:
        """Get timer processing statistics."""
        if not self.timer_manager:
            return None

        try:
            if hasattr(self.timer_manager, 'get_statistics'):
                return self.timer_manager.get_statistics()
            elif hasattr(self.timer_manager, 'get_stream_info'):
                return self.timer_manager.get_stream_info()
        except Exception as e:
            logger.error(f"Error getting timer statistics: {e}")

        return {"error": "Statistics not available"}

    # Timer management interface
    async def schedule_timer(self, timer_id: str, delay_seconds: float, metadata: Optional[Dict] = None) -> bool:
        """Schedule a timer."""
        if not self.timer_manager:
            logger.warning("Timer manager not available")
            return False

        try:
            if hasattr(self.timer_manager, 'schedule_timer'):
                return await self.timer_manager.schedule_timer(timer_id, delay_seconds, metadata)
            else:
                logger.warning("Timer manager does not support scheduling")
                return False
        except Exception as e:
            logger.error(f"Error scheduling timer {timer_id}: {e}")
            return False

    async def cancel_timer(self, timer_id: str) -> bool:
        """Cancel a timer."""
        if not self.timer_manager:
            logger.warning("Timer manager not available")
            return False

        try:
            if hasattr(self.timer_manager, 'cancel_timer'):
                return await self.timer_manager.cancel_timer(timer_id)
            else:
                logger.warning("Timer manager does not support cancellation")
                return False
        except Exception as e:
            logger.error(f"Error canceling timer {timer_id}: {e}")
            return False

    async def get_timer_status(self, timer_id: str) -> Optional[Dict[str, Any]]:
        """Get timer status."""
        if not self.timer_manager:
            return None

        try:
            if hasattr(self.timer_manager, 'get_timer_status'):
                return await self.timer_manager.get_timer_status(timer_id)
            else:
                # Check persistence directly
                return await self.persistence.get_timer(timer_id)
        except Exception as e:
            logger.error(f"Error getting timer status {timer_id}: {e}")
            return None