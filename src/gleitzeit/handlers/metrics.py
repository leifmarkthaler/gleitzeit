"""
Handler metrics for monitoring and performance tracking.

Provides lightweight metrics collection for handlers without external dependencies.
"""

import time
import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class MetricSnapshot:
    """Point-in-time snapshot of handler metrics"""
    handler_name: str
    timestamp: float
    tasks_processed: int
    tasks_failed: int
    tasks_succeeded: int
    avg_execution_time_ms: float
    p50_execution_time_ms: float
    p95_execution_time_ms: float
    p99_execution_time_ms: float
    current_executing: int
    max_concurrent_seen: int
    error_rate: float
    throughput_per_sec: float


class HandlerMetrics:
    """
    Metrics collector for individual handlers.

    Tracks execution times, success/failure rates, concurrency, and throughput.
    Uses a rolling window for performance metrics to avoid unbounded memory growth.
    """

    def __init__(self, handler_name: str, window_size: int = 1000):
        """
        Initialize metrics for a handler.

        Args:
            handler_name: Name of the handler
            window_size: Size of rolling window for timing metrics
        """
        self.handler_name = handler_name
        self.window_size = window_size

        # Counters
        self.tasks_processed = 0
        self.tasks_failed = 0
        self.tasks_succeeded = 0

        # Timing metrics (rolling window)
        self.execution_times: deque = deque(maxlen=window_size)

        # Concurrency tracking
        self.current_executing = 0
        self.max_concurrent_seen = 0

        # Throughput tracking
        self.start_time = time.time()
        self.last_snapshot_time = time.time()
        self.tasks_since_snapshot = 0

        # Lock for thread safety
        self._lock = asyncio.Lock()

    async def record_task_start(self) -> float:
        """
        Record the start of a task execution.

        Returns:
            Start timestamp for use in record_task_end
        """
        async with self._lock:
            self.current_executing += 1
            if self.current_executing > self.max_concurrent_seen:
                self.max_concurrent_seen = self.current_executing

        return time.time()

    async def record_task_end(
        self,
        start_time: float,
        success: bool = True,
        error: Optional[Exception] = None
    ):
        """
        Record the end of a task execution.

        Args:
            start_time: Start time from record_task_start
            success: Whether the task succeeded
            error: Optional exception if task failed
        """
        execution_time = time.time() - start_time

        async with self._lock:
            # Update counters
            self.tasks_processed += 1
            self.tasks_since_snapshot += 1

            if success:
                self.tasks_succeeded += 1
            else:
                self.tasks_failed += 1
                if error:
                    logger.debug(f"Task failed in {self.handler_name}: {error}")

            # Record execution time
            self.execution_times.append(execution_time)

            # Update concurrency
            self.current_executing = max(0, self.current_executing - 1)

    async def record_execution(self, coro, record_errors: bool = True):
        """
        Context manager to automatically record execution metrics.

        Usage:
            async with metrics.record_execution():
                result = await handler.execute(task)

        Args:
            coro: Coroutine to execute
            record_errors: Whether to record exceptions as failures

        Returns:
            Result of the coroutine
        """
        start_time = await self.record_task_start()

        try:
            result = await coro
            await self.record_task_end(start_time, success=True)
            return result

        except Exception as e:
            if record_errors:
                await self.record_task_end(start_time, success=False, error=e)
            else:
                await self.record_task_end(start_time, success=True)
            raise

    def get_snapshot(self) -> MetricSnapshot:
        """
        Get a snapshot of current metrics.

        Returns:
            MetricSnapshot with current metrics
        """
        current_time = time.time()

        # Calculate percentiles if we have data
        if self.execution_times:
            sorted_times = sorted(self.execution_times)
            count = len(sorted_times)

            p50_idx = int(count * 0.5)
            p95_idx = int(count * 0.95)
            p99_idx = int(count * 0.99)

            p50 = sorted_times[p50_idx] * 1000  # Convert to ms
            p95 = sorted_times[p95_idx] * 1000
            p99 = sorted_times[p99_idx] * 1000
            avg = sum(sorted_times) / count * 1000
        else:
            p50 = p95 = p99 = avg = 0.0

        # Calculate rates
        error_rate = (
            self.tasks_failed / self.tasks_processed
            if self.tasks_processed > 0 else 0.0
        )

        # Calculate throughput
        time_since_snapshot = current_time - self.last_snapshot_time
        throughput = (
            self.tasks_since_snapshot / time_since_snapshot
            if time_since_snapshot > 0 else 0.0
        )

        # Reset snapshot counters
        self.last_snapshot_time = current_time
        self.tasks_since_snapshot = 0

        return MetricSnapshot(
            handler_name=self.handler_name,
            timestamp=current_time,
            tasks_processed=self.tasks_processed,
            tasks_failed=self.tasks_failed,
            tasks_succeeded=self.tasks_succeeded,
            avg_execution_time_ms=avg,
            p50_execution_time_ms=p50,
            p95_execution_time_ms=p95,
            p99_execution_time_ms=p99,
            current_executing=self.current_executing,
            max_concurrent_seen=self.max_concurrent_seen,
            error_rate=error_rate,
            throughput_per_sec=throughput
        )

    def get_stats(self) -> Dict[str, Any]:
        """
        Get current statistics as a dictionary.

        Returns:
            Dict with current metrics
        """
        snapshot = self.get_snapshot()
        return {
            'handler': snapshot.handler_name,
            'processed': snapshot.tasks_processed,
            'succeeded': snapshot.tasks_succeeded,
            'failed': snapshot.tasks_failed,
            'error_rate': f"{snapshot.error_rate:.2%}",
            'avg_time_ms': f"{snapshot.avg_execution_time_ms:.2f}",
            'p50_ms': f"{snapshot.p50_execution_time_ms:.2f}",
            'p95_ms': f"{snapshot.p95_execution_time_ms:.2f}",
            'p99_ms': f"{snapshot.p99_execution_time_ms:.2f}",
            'executing': snapshot.current_executing,
            'max_concurrent': snapshot.max_concurrent_seen,
            'throughput/s': f"{snapshot.throughput_per_sec:.2f}"
        }

    async def flush(self):
        """Flush any pending metrics (for cleanup)"""
        # Currently no buffering, but could add in future
        pass

    def reset(self):
        """Reset all metrics to zero"""
        self.tasks_processed = 0
        self.tasks_failed = 0
        self.tasks_succeeded = 0
        self.execution_times.clear()
        self.current_executing = 0
        self.max_concurrent_seen = 0
        self.start_time = time.time()
        self.last_snapshot_time = time.time()
        self.tasks_since_snapshot = 0

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"HandlerMetrics({self.handler_name}: "
            f"{self.tasks_processed} processed, "
            f"{self.current_executing} executing)"
        )