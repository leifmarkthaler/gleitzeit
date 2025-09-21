"""
Tick Coordinator for driving stateless components.

This coordinator generates internal ticks to drive processing
without using persistent loops - uses asyncio scheduling instead.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import os

logger = logging.getLogger(__name__)


class TickCoordinator:
    """
    Coordinates tick-based processing for stateless components.

    Instead of while loops, uses asyncio scheduling to generate
    periodic ticks that trigger processing in stateless components.
    """

    def __init__(
        self,
        tick_interval: float = 1.0,  # Default 1 second tick
        instance_id: Optional[str] = None
    ):
        """
        Initialize TickCoordinator.

        Args:
            tick_interval: Seconds between ticks
            instance_id: Instance identifier
        """
        self.tick_interval = tick_interval
        self.instance_id = instance_id or f"tick-coordinator-{os.getpid()}"

        # Components to tick
        self.tick_components: List[Any] = []

        # Tick control
        self._tick_task: Optional[asyncio.Task] = None
        self._running = False
        self._tick_count = 0

        # Stats
        self._last_tick_time: Optional[float] = None
        self._tick_durations: List[float] = []
        self._max_duration_history = 100

        logger.info(f"Initialized TickCoordinator (interval: {tick_interval}s)")

    def register_component(self, component: Any):
        """
        Register a component to receive ticks.

        Component must have a tick() method.
        """
        if hasattr(component, 'tick'):
            self.tick_components.append(component)
            logger.info(f"Registered component {component.__class__.__name__} for ticks")
        else:
            logger.warning(f"Component {component.__class__.__name__} has no tick() method")

    async def start(self):
        """Start tick generation."""
        if self._running:
            logger.warning("TickCoordinator already running")
            return

        self._running = True
        self._tick_task = asyncio.create_task(self._tick_generator())
        logger.info(f"TickCoordinator started with {len(self.tick_components)} components")

    async def stop(self):
        """Stop tick generation."""
        self._running = False

        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass

        logger.info(f"TickCoordinator stopped after {self._tick_count} ticks")

    async def _tick_generator(self):
        """
        Generate ticks using asyncio scheduling.

        NOT a while loop - uses recursive scheduling!
        """
        if not self._running:
            return

        try:
            # Process tick
            await self._process_tick()

            # Schedule next tick
            if self._running:
                asyncio.create_task(self._schedule_next_tick())

        except Exception as e:
            logger.error(f"Error in tick generator: {e}")
            # Still schedule next tick
            if self._running:
                asyncio.create_task(self._schedule_next_tick())

    async def _schedule_next_tick(self):
        """Schedule the next tick after interval."""
        await asyncio.sleep(self.tick_interval)
        await self._tick_generator()

    async def _process_tick(self):
        """Process one tick across all components."""
        self._tick_count += 1
        tick_start = time.time()

        logger.debug(f"Processing tick {self._tick_count}")

        # Collect tick results
        results = {}

        # Tick each component concurrently
        tasks = []
        for component in self.tick_components:
            try:
                tasks.append(self._tick_component(component))
            except Exception as e:
                logger.error(f"Error creating tick task for {component.__class__.__name__}: {e}")

        # Wait for all ticks to complete
        if tasks:
            tick_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for i, result in enumerate(tick_results):
                component_name = self.tick_components[i].__class__.__name__
                if isinstance(result, Exception):
                    logger.error(f"Tick error in {component_name}: {result}")
                    results[component_name] = {"error": str(result)}
                else:
                    results[component_name] = result

        # Track duration
        tick_duration = time.time() - tick_start
        self._tick_durations.append(tick_duration)
        if len(self._tick_durations) > self._max_duration_history:
            self._tick_durations.pop(0)

        self._last_tick_time = time.time()

        # Log if tick took too long
        if tick_duration > self.tick_interval * 0.8:
            logger.warning(f"Tick {self._tick_count} took {tick_duration:.2f}s (interval: {self.tick_interval}s)")

        return results

    async def _tick_component(self, component: Any) -> Dict[str, Any]:
        """Tick a single component."""
        try:
            result = await component.tick()
            return result
        except Exception as e:
            logger.error(f"Error ticking {component.__class__.__name__}: {e}")
            raise

    async def manual_tick(self) -> Dict[str, Any]:
        """
        Manually trigger a tick (for testing or external control).

        Returns:
            Tick results from all components
        """
        return await self._process_tick()

    def get_statistics(self) -> Dict[str, Any]:
        """Get coordinator statistics."""
        avg_duration = 0
        if self._tick_durations:
            avg_duration = sum(self._tick_durations) / len(self._tick_durations)

        return {
            "instance_id": self.instance_id,
            "running": self._running,
            "tick_count": self._tick_count,
            "tick_interval": self.tick_interval,
            "registered_components": len(self.tick_components),
            "average_tick_duration": avg_duration,
            "last_tick_time": self._last_tick_time
        }


class AdaptiveTickCoordinator(TickCoordinator):
    """
    Adaptive tick coordinator that adjusts tick rate based on load.

    Increases tick rate when there's work to do,
    decreases when idle to save resources.
    """

    def __init__(
        self,
        min_interval: float = 0.1,
        max_interval: float = 5.0,
        initial_interval: float = 1.0,
        instance_id: Optional[str] = None
    ):
        """
        Initialize AdaptiveTickCoordinator.

        Args:
            min_interval: Minimum tick interval (high load)
            max_interval: Maximum tick interval (idle)
            initial_interval: Starting tick interval
            instance_id: Instance identifier
        """
        super().__init__(tick_interval=initial_interval, instance_id=instance_id)

        self.min_interval = min_interval
        self.max_interval = max_interval

        # Track work done to adjust rate
        self._work_history: List[int] = []
        self._history_size = 10

    async def _process_tick(self):
        """Process tick and adjust interval based on work done."""
        results = await super()._process_tick()

        # Count work done
        work_done = 0
        for component_result in results.values():
            if isinstance(component_result, dict):
                # Sum up processed items from each component
                work_done += component_result.get("processed", 0)
                work_done += component_result.get("fired", 0)
                work_done += component_result.get("delivered", 0)
                work_done += component_result.get("enqueued", 0)

        # Track work history
        self._work_history.append(work_done)
        if len(self._work_history) > self._history_size:
            self._work_history.pop(0)

        # Adjust tick interval
        self._adjust_interval()

        return results

    def _adjust_interval(self):
        """Adjust tick interval based on recent work."""
        if not self._work_history:
            return

        avg_work = sum(self._work_history) / len(self._work_history)

        # High work: decrease interval (tick faster)
        if avg_work > 10:
            self.tick_interval = max(self.min_interval, self.tick_interval * 0.8)
        # Low work: increase interval (tick slower)
        elif avg_work < 1:
            self.tick_interval = min(self.max_interval, self.tick_interval * 1.2)

        logger.debug(f"Adjusted tick interval to {self.tick_interval:.2f}s (avg work: {avg_work:.1f})")

    def get_statistics(self) -> Dict[str, Any]:
        """Get adaptive coordinator statistics."""
        stats = super().get_statistics()

        avg_work = 0
        if self._work_history:
            avg_work = sum(self._work_history) / len(self._work_history)

        stats.update({
            "adaptive": True,
            "min_interval": self.min_interval,
            "max_interval": self.max_interval,
            "current_interval": self.tick_interval,
            "average_work": avg_work
        })

        return stats