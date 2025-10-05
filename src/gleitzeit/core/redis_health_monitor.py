"""
Per-Instance Redis Health Monitor

Monitors Redis connectivity and triggers graceful shutdown on extended failure.
This is NOT distributed - each process monitors its own Redis connection.

Uses Gleitzeit's central error system for consistent error handling.
"""

import asyncio
import logging
from enum import Enum
from typing import Optional, Callable, Dict, Any
from datetime import datetime, timedelta

from .errors import (
    PersistenceConnectionError,
    HealthCheckError,
    CoordinationError,
    ErrorCode
)

logger = logging.getLogger(__name__)


class RedisHealthState(Enum):
    """Redis health states for a single instance"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    SHUTDOWN = "shutdown"


class RedisHealthMonitor:
    """
    Per-instance Redis connection health monitor.

    Monitors Redis connectivity and escalates through states:
    HEALTHY → WARNING → CRITICAL → SHUTDOWN

    Features:
    - State-based failure escalation
    - Configurable thresholds and timeouts
    - Graceful shutdown on extended failure
    - Automatic recovery detection
    - Integration with Gleitzeit error system
    """

    def __init__(
        self,
        redis_client,
        config: Optional[Dict[str, Any]] = None,
        shutdown_callback: Optional[Callable] = None
    ):
        """
        Initialize Redis health monitor.

        Args:
            redis_client: Redis client to monitor
            config: Configuration dict with:
                - check_interval: Seconds between health checks (default: 10)
                - warning_threshold: Consecutive failures before WARNING (default: 3)
                - critical_timeout: Seconds before CRITICAL state (default: 120)
                - shutdown_timeout: Seconds before SHUTDOWN (default: 300)
            shutdown_callback: Async function to call on SHUTDOWN state
        """
        self.redis = redis_client
        self.config = config or {}
        self.shutdown_callback = shutdown_callback

        # Configuration with defaults
        self.check_interval = self.config.get('check_interval', 10)
        self.warning_threshold = self.config.get('warning_threshold', 3)
        self.critical_timeout = self.config.get('critical_timeout', 120)
        self.shutdown_timeout = self.config.get('shutdown_timeout', 300)

        # State tracking
        self.state = RedisHealthState.HEALTHY
        self.consecutive_failures = 0
        self.first_failure_time: Optional[datetime] = None
        self.last_success_time: Optional[datetime] = None

        # Running flag
        self._running = False
        self._task: Optional[asyncio.Task] = None

        logger.info(
            f"RedisHealthMonitor initialized: check_interval={self.check_interval}s, "
            f"warning_threshold={self.warning_threshold}, "
            f"critical_timeout={self.critical_timeout}s, "
            f"shutdown_timeout={self.shutdown_timeout}s"
        )

    async def start(self):
        """Start the health monitoring loop"""
        if self._running:
            logger.warning("RedisHealthMonitor already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        logger.info("RedisHealthMonitor started")

    async def stop(self):
        """Stop the health monitoring loop"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("RedisHealthMonitor stopped")

    async def _monitoring_loop(self):
        """Main monitoring loop"""
        while self._running:
            try:
                # Perform health check
                await self._check_health()

                # Sleep based on current state
                sleep_duration = self._get_sleep_duration()
                await asyncio.sleep(sleep_duration)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in Redis health monitor: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)

    async def _check_health(self):
        """Perform Redis health check"""
        try:
            # Attempt Redis ping
            await self.redis.ping()

            # Success - handle recovery if needed
            await self._handle_success()

        except Exception as e:
            # Failure - handle failure escalation
            await self._handle_failure(e)

    async def _handle_success(self):
        """Handle successful Redis ping"""
        now = datetime.utcnow()
        self.last_success_time = now

        # Check if we're recovering from a failure
        if self.state != RedisHealthState.HEALTHY:
            old_state = self.state
            downtime = (now - self.first_failure_time).total_seconds() if self.first_failure_time else 0

            logger.info(
                f"Redis connection recovered! "
                f"Previous state: {old_state.value}, "
                f"Downtime: {downtime:.1f}s"
            )

            # Transition back to healthy
            self.state = RedisHealthState.HEALTHY
            self.consecutive_failures = 0
            self.first_failure_time = None

    async def _handle_failure(self, error: Exception):
        """Handle Redis connection failure"""
        self.consecutive_failures += 1

        # Record first failure time
        if self.first_failure_time is None:
            self.first_failure_time = datetime.utcnow()

        # Calculate time down
        time_down = (datetime.utcnow() - self.first_failure_time).total_seconds()

        # Determine new state based on time down
        new_state = self._calculate_state(time_down)

        # Transition if state changed
        if new_state != self.state:
            await self._transition_to_state(new_state, error, time_down)

        # Log based on state
        if self.state == RedisHealthState.WARNING:
            logger.warning(
                f"Redis connection issues: {self.consecutive_failures} consecutive failures, "
                f"downtime: {time_down:.1f}s - {error}"
            )
        elif self.state == RedisHealthState.CRITICAL:
            logger.error(
                f"Redis connection CRITICAL: downtime {time_down:.1f}s - {error}"
            )
        elif self.state == RedisHealthState.SHUTDOWN:
            logger.critical(
                f"Redis connection down for {time_down:.1f}s, initiating SHUTDOWN - {error}"
            )

    def _calculate_state(self, time_down: float) -> RedisHealthState:
        """
        Calculate health state based on downtime.

        Args:
            time_down: Seconds since first failure

        Returns:
            Appropriate RedisHealthState
        """
        if time_down >= self.shutdown_timeout:
            return RedisHealthState.SHUTDOWN
        elif time_down >= self.critical_timeout:
            return RedisHealthState.CRITICAL
        elif self.consecutive_failures >= self.warning_threshold:
            return RedisHealthState.WARNING
        else:
            return self.state  # No change

    async def _transition_to_state(
        self,
        new_state: RedisHealthState,
        error: Exception,
        time_down: float
    ):
        """
        Transition to new health state.

        Args:
            new_state: New state to transition to
            error: Exception that triggered transition
            time_down: Seconds since first failure
        """
        old_state = self.state
        self.state = new_state

        logger.warning(
            f"Redis health state transition: {old_state.value} → {new_state.value} "
            f"(downtime: {time_down:.1f}s, failures: {self.consecutive_failures})"
        )

        # Take action based on new state
        if new_state == RedisHealthState.SHUTDOWN:
            await self._trigger_shutdown(error, time_down)

    async def _trigger_shutdown(self, error: Exception, time_down: float):
        """
        Trigger graceful shutdown.

        Args:
            error: Exception that triggered shutdown
            time_down: Seconds since first failure
        """
        logger.critical(
            f"Redis health monitor triggering shutdown: "
            f"Redis down for {time_down:.1f}s, {self.consecutive_failures} failures"
        )

        # Create appropriate Gleitzeit error
        shutdown_error = CoordinationError(
            operation="redis_health_check",
            data={
                "time_down_seconds": time_down,
                "consecutive_failures": self.consecutive_failures,
                "original_error": str(error),
                "original_error_type": type(error).__name__
            },
            cause=error
        )

        # Log error context
        logger.critical(f"Shutdown error context: {shutdown_error.to_json_string()}")

        # Call shutdown callback if provided
        if self.shutdown_callback:
            try:
                await self.shutdown_callback(shutdown_error)
            except Exception as e:
                logger.error(f"Error in shutdown callback: {e}", exc_info=True)
        else:
            logger.critical("No shutdown callback registered, monitor will stop but process continues")

        # Stop monitoring
        self._running = False

    def _get_sleep_duration(self) -> float:
        """
        Get sleep duration based on current state.

        Increases check frequency in degraded states.

        Returns:
            Seconds to sleep before next check
        """
        durations = {
            RedisHealthState.HEALTHY: self.check_interval,
            RedisHealthState.WARNING: self.check_interval,  # Same frequency in WARNING
            RedisHealthState.CRITICAL: self.check_interval / 2,  # Check more frequently
            RedisHealthState.SHUTDOWN: 0  # Don't sleep, loop will exit
        }
        return durations[self.state]

    def get_status(self) -> Dict[str, Any]:
        """
        Get current health status.

        Returns:
            Dict with health status information
        """
        status = {
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "is_healthy": self.state == RedisHealthState.HEALTHY
        }

        if self.first_failure_time:
            time_down = (datetime.utcnow() - self.first_failure_time).total_seconds()
            status["time_down_seconds"] = time_down

        if self.last_success_time:
            time_since_success = (datetime.utcnow() - self.last_success_time).total_seconds()
            status["last_success_seconds_ago"] = time_since_success

        return status

    def is_healthy(self) -> bool:
        """Check if Redis connection is healthy"""
        return self.state == RedisHealthState.HEALTHY

    def is_degraded(self) -> bool:
        """Check if Redis connection is degraded (WARNING or CRITICAL)"""
        return self.state in [RedisHealthState.WARNING, RedisHealthState.CRITICAL]

    def is_shutdown(self) -> bool:
        """Check if shutdown has been triggered"""
        return self.state == RedisHealthState.SHUTDOWN