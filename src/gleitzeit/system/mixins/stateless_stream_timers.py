"""
Stateless stream timers mixin providing timer management without loops.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class StatelessStreamTimersMixin:
    """
    Mixin providing stateless timer management.

    This mixin handles:
    - Stateless timer processing
    - No loops, pure trigger-based
    - Timer operations via Redis
    """

    def __init__(self, **kwargs):
        """Initialize stateless timer components."""
        self.max_timers_per_tick = 100
        super().__init__(**kwargs)

    async def initialize_stateless_stream_timers(self):
        """Initialize stateless timer support."""
        redis_client = getattr(self.persistence, 'redis', None)
        if not redis_client:
            logger.warning("Redis not available - timer support disabled")
            return

        try:
            # Store Redis reference for stateless timer operations
            self.redis_client = redis_client

            # Register timer/v1 protocol if registry is available
            if hasattr(self, 'registry') and self.registry:
                await self.registry.register_provider_in_persistence(
                    "timer/v1",
                    {
                        "provider_id": "stateless_timer_manager",
                        "instance_id": self.instance_id,
                        "capabilities": ["timer/wait", "timer/schedule", "timer/cancel"],
                        "stateless": True,
                        "has_loops": False
                    }
                )
                logger.info("Registered timer/v1 protocol (stateless)")

            # Register in component registry
            if hasattr(self, 'component_registry') and self.component_registry:
                await self.component_registry.register_component(
                    component_id="stateless_timer_manager",
                    component_type="stateless_service",
                    metadata={
                        "instance_id": self.instance_id,
                        "stateless": True,
                        "has_loops": False,
                        "max_timers_per_tick": self.max_timers_per_tick
                    }
                )

            logger.info("Stateless timer support initialized (NO LOOPS!)")

        except Exception as e:
            logger.error(f"Failed to initialize stateless timer support: {e}")

    async def process_timers_once(self) -> Dict[str, Any]:
        """
        Process timers once - NO LOOPS!
        This is called by external triggers.

        Returns:
            Processing statistics
        """
        try:
            from ...timers.stateless_timer_manager import StatelessTimerManager

            result = await StatelessTimerManager.process_all_once(
                self.redis_client,
                max_timers=self.max_timers_per_tick
            )

            logger.debug(f"Processed {result['processed']} timers")
            return result

        except Exception as e:
            logger.error(f"Error processing timers: {e}")
            return {"error": str(e), "processed": 0}

    async def create_timer(
        self,
        workflow_id: str,
        duration_seconds: float,
        task_id: Optional[str] = None,
        timer_type: str = "delay",
        payload: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a timer (stateless operation).

        Args:
            workflow_id: Workflow ID
            duration_seconds: Timer duration
            task_id: Optional task ID
            timer_type: Timer type
            payload: Timer payload

        Returns:
            Timer ID
        """
        try:
            from ...timers.stateless_timer_manager import StatelessTimerManager

            timer_id = await StatelessTimerManager.create_timer(
                self.redis_client,
                workflow_id=workflow_id,
                duration_seconds=duration_seconds,
                task_id=task_id,
                timer_type=timer_type,
                payload=payload
            )

            logger.info(f"Created timer {timer_id} for workflow {workflow_id}")
            return timer_id

        except Exception as e:
            logger.error(f"Failed to create timer: {e}")
            raise

    async def cancel_timer(self, timer_id: str) -> bool:
        """
        Cancel a timer (stateless operation).

        Args:
            timer_id: Timer ID to cancel

        Returns:
            True if cancelled
        """
        try:
            from ...timers.stateless_timer_manager import StatelessTimerManager

            result = await StatelessTimerManager.cancel_timer(
                self.redis_client,
                timer_id=timer_id
            )

            if result:
                logger.info(f"Cancelled timer {timer_id}")

            return result

        except Exception as e:
            logger.error(f"Failed to cancel timer {timer_id}: {e}")
            return False

    async def get_timer_statistics(self) -> Optional[Dict[str, Any]]:
        """Get timer statistics (stateless query)."""
        try:
            from ...timers.stateless_timer_manager import StatelessTimerManager

            stats = await StatelessTimerManager.get_timer_stats(self.redis_client)
            stats["stateless"] = True
            stats["has_loops"] = False

            return stats

        except Exception as e:
            logger.error(f"Failed to get timer statistics: {e}")
            return None

    async def shutdown_stateless_stream_timers(self):
        """Shutdown stateless timer support (no loops to stop!)."""
        logger.info("Stateless timer support shutdown (no loops to stop)")