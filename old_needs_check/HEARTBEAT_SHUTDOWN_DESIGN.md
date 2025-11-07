# Heartbeat & Redis Failure Handling Design

## Overview
Gleitzeit depends on Redis for critical coordination. When Redis becomes unavailable for an extended period, the system should gracefully shutdown rather than continue running in a degraded state.

## System Requirements

### 1. Redis is Critical
Gleitzeit depends on Redis for:
- Service discovery and registration
- Task queue management
- Workflow coordination
- Distributed state management
- Inter-service communication

### 2. Graceful Degradation Strategy
- **Brief outages (< 2 min)**: Keep retrying, log warnings
- **Extended outages (2-5 min)**: Enter critical state, prepare for shutdown
- **Persistent outages (> 5 min)**: Initiate graceful shutdown
- Services should not run "blind" without coordination capability

## State Machine Design

```
┌─────────────────────────────────────────────────────────┐
│                  Heartbeat State Machine                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  HEALTHY ──────────┐                                   │
│     │               │                                   │
│     │ Error         │ Success (auto-recovery)          │
│     ▼               │                                   │
│  WARNING ◄──────────┘                                   │
│     │                                                   │
│     │ Time > critical_timeout                          │
│     ▼                                                   │
│  CRITICAL                                               │
│     │                                                   │
│     │ Time > shutdown_timeout                          │
│     ▼                                                   │
│  SHUTDOWN                                               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Configuration Schema

Configuration values are read from `gleitzeit.yaml`:

```yaml
# gleitzeit.yaml
redis:
  # Existing Redis configuration
  url: redis://localhost:6379

  # Heartbeat configuration
  heartbeat:
    enabled: true                    # Enable heartbeat monitoring (default: true)
    interval: 30                     # Heartbeat interval in seconds (default: 30)
    warning_threshold: 3             # Consecutive failures before WARNING state (default: 3)
    critical_timeout: 120            # Seconds before CRITICAL state (default: 120)
    shutdown_timeout: 300            # Seconds before SHUTDOWN (default: 300)

  # Shutdown behavior configuration
  shutdown:
    mode: "graceful"                 # "graceful" or "immediate" (default: graceful)
    grace_period: 30                 # Seconds to wait for task completion (default: 30)
    force_after: 60                  # Force shutdown after this many seconds (default: 60)
```

## Implementation Design

### HeartbeatMonitor Class

```python
from enum import Enum
from datetime import datetime, timedelta
import asyncio
import sys
from typing import Optional

class HeartbeatState(Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    SHUTDOWN = "shutdown"

class HeartbeatMonitor:
    """
    Monitors Redis connectivity and initiates shutdown if unhealthy.
    Configuration is loaded from gleitzeit.yaml.
    """

    def __init__(self, config_manager, redis_client, service_manager):
        self.config = config_manager.get_redis_heartbeat_config()
        self.redis = redis_client
        self.service_manager = service_manager

        # Load configuration with defaults
        self.interval = self.config.get('interval', 30)
        self.warning_threshold = self.config.get('warning_threshold', 3)
        self.critical_timeout = self.config.get('critical_timeout', 120)
        self.shutdown_timeout = self.config.get('shutdown_timeout', 300)

        # Shutdown configuration
        self.shutdown_config = config_manager.get_redis_shutdown_config()
        self.shutdown_mode = self.shutdown_config.get('mode', 'graceful')
        self.grace_period = self.shutdown_config.get('grace_period', 30)
        self.force_after = self.shutdown_config.get('force_after', 60)

        # State tracking
        self.state = HeartbeatState.HEALTHY
        self.consecutive_failures = 0
        self.first_failure_time: Optional[datetime] = None
        self.shutdown_initiated = False

    async def heartbeat_loop(self):
        """
        Main heartbeat loop with escalating failure handling.
        Reads configuration from gleitzeit.yaml.
        """
        logger.info(f"Starting heartbeat monitor (interval={self.interval}s, "
                   f"shutdown_after={self.shutdown_timeout}s)")

        while self.state != HeartbeatState.SHUTDOWN:
            try:
                # Attempt heartbeat
                await self.perform_heartbeat()

                # Success - check if we're recovering
                if self.state != HeartbeatState.HEALTHY:
                    logger.info(f"Redis recovered from {self.state.value} state, returning to healthy")
                    await self.notify_recovery()

                # Reset to healthy state
                self.state = HeartbeatState.HEALTHY
                self.consecutive_failures = 0
                self.first_failure_time = None

                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                logger.info("Heartbeat monitor cancelled")
                raise

            except Exception as e:
                await self.handle_heartbeat_failure(e)

    async def perform_heartbeat(self):
        """
        Perform the actual heartbeat operations.
        """
        # Test Redis connectivity first - this is critical
        await self.redis.ping()

        # Track individual service heartbeat failures
        service_failures = []

        # Refresh service registrations
        if self.service_manager:
            for service_name in ['api', 'ui']:
                try:
                    # Check if service is still running locally
                    is_running = await self.service_manager.is_service_running(service_name)

                    if not is_running:
                        # Service died - don't refresh registration
                        logger.warning(f"Service {service_name} is not running, skipping heartbeat")
                        service_failures.append((service_name, "not_running"))
                        continue

                    # Get current registration from Redis
                    service_data = await self.redis.hgetall(f"service:registry:{service_name}")

                    if not service_data:
                        # Service not registered - try to re-register if running
                        logger.warning(f"Service {service_name} not in registry, attempting re-registration")
                        await self.service_manager.register_service(service_name)
                    else:
                        # Refresh the registration TTL
                        await self.service_manager.refresh_registration(service_name, service_data)

                except Exception as e:
                    # Individual service heartbeat failed, but Redis is up
                    logger.error(f"Failed to heartbeat {service_name}: {e}")
                    service_failures.append((service_name, str(e)))

        # Handle individual service failures
        if service_failures:
            await self.handle_service_failures(service_failures)

    async def handle_heartbeat_failure(self, error: Exception):
        """
        Handle heartbeat failure with state transitions.
        """
        self.consecutive_failures += 1

        # Track first failure time
        if self.first_failure_time is None:
            self.first_failure_time = datetime.now()

        time_down = datetime.now() - self.first_failure_time

        # State transitions based on configuration
        new_state = self.determine_new_state(time_down)

        if new_state != self.state:
            await self.transition_state(new_state, error, time_down)

        # Log based on current state
        self.log_failure(error, time_down)

        # Backoff based on state
        await self.apply_backoff()

    def determine_new_state(self, time_down: timedelta) -> HeartbeatState:
        """
        Determine state based on failure duration and configuration.
        """
        if time_down.total_seconds() >= self.shutdown_timeout:
            return HeartbeatState.SHUTDOWN
        elif time_down.total_seconds() >= self.critical_timeout:
            return HeartbeatState.CRITICAL
        elif self.consecutive_failures >= self.warning_threshold:
            return HeartbeatState.WARNING
        else:
            return self.state

    async def transition_state(self, new_state: HeartbeatState, error: Exception, time_down: timedelta):
        """
        Handle state transitions.
        """
        old_state = self.state
        self.state = new_state

        logger.warning(f"Heartbeat state transition: {old_state.value} -> {new_state.value}")

        if new_state == HeartbeatState.WARNING:
            logger.warning(f"Redis connectivity issues after {self.consecutive_failures} failures: {error}")

        elif new_state == HeartbeatState.CRITICAL:
            logger.error(f"Redis has been down for {time_down.total_seconds():.0f}s, entering CRITICAL state")
            await self.notify_critical_state()

        elif new_state == HeartbeatState.SHUTDOWN:
            logger.critical(f"Redis down for {time_down.total_seconds():.0f}s, initiating shutdown")
            await self.initiate_graceful_shutdown()

    def log_failure(self, error: Exception, time_down: timedelta):
        """
        Log failures with appropriate severity based on state.
        """
        if self.state == HeartbeatState.HEALTHY:
            # First few failures, just debug
            logger.debug(f"Transient Redis error ({self.consecutive_failures}): {error}")

        elif self.state == HeartbeatState.WARNING:
            # Log every 10th failure to avoid spam
            if self.consecutive_failures % 10 == 0:
                logger.warning(f"Redis still down after {time_down.total_seconds():.0f}s")

        elif self.state == HeartbeatState.CRITICAL:
            # Log every 20th failure in critical state
            if self.consecutive_failures % 20 == 0:
                logger.error(f"CRITICAL: Redis unavailable for {time_down.total_seconds():.0f}s")

    async def apply_backoff(self):
        """
        Apply exponential backoff strategy based on current state and failure count.
        """
        # Calculate exponential backoff with jitter
        base_delay = 5  # Base delay in seconds
        max_delay = 60  # Maximum delay in seconds

        if self.state == HeartbeatState.HEALTHY:
            # Exponential backoff: 5, 10, 20, 40, 60 (capped)
            delay = min(base_delay * (2 ** min(self.consecutive_failures - 1, 4)), max_delay)
        elif self.state == HeartbeatState.WARNING:
            # Slower backoff in warning: 10, 20, 40, 60 (capped)
            delay = min(10 * (2 ** min(self.consecutive_failures // 3, 3)), max_delay)
        elif self.state == HeartbeatState.CRITICAL:
            # Fixed longer interval in critical state
            delay = 30

        # Add jitter to prevent thundering herd
        import random
        jitter = random.uniform(0, delay * 0.1)  # Up to 10% jitter
        actual_delay = delay + jitter

        logger.debug(f"Backing off for {actual_delay:.1f}s (state={self.state.value}, failures={self.consecutive_failures})")
        await asyncio.sleep(actual_delay)

    async def notify_critical_state(self):
        """
        Notify services that we're in critical state.
        Services should prepare for potential shutdown.
        """
        logger.warning("Notifying services of CRITICAL state - prepare for potential shutdown")

        # Set a Redis key if we can (might fail)
        try:
            await self.redis.set("system:state", "critical", ex=60)
        except:
            pass

        # Notify service manager
        if self.service_manager:
            await self.service_manager.notify_critical_state()

    async def notify_recovery(self):
        """
        Notify services that Redis has recovered.
        """
        logger.info("Notifying services of recovery")

        try:
            await self.redis.set("system:state", "healthy", ex=60)
        except:
            pass

        if self.service_manager:
            await self.service_manager.notify_recovery()

    async def initiate_graceful_shutdown(self):
        """
        Gracefully shutdown all services based on configuration.
        """
        if self.shutdown_initiated:
            return

        self.shutdown_initiated = True

        logger.critical("="*60)
        logger.critical("SYSTEM SHUTDOWN: Redis unavailable for extended period")
        logger.critical(f"Shutdown mode: {self.shutdown_mode}")
        logger.critical(f"Grace period: {self.grace_period}s")
        logger.critical("="*60)

        if self.shutdown_mode == "immediate":
            await self.immediate_shutdown()
        else:
            await self.graceful_shutdown()

    async def graceful_shutdown(self):
        """
        Perform graceful shutdown with task completion.
        """
        try:
            # Step 1: Stop accepting new work
            logger.info("Step 1/4: Stopping new work acceptance")
            if self.service_manager:
                await self.service_manager.stop_accepting_work()

            # Step 2: Wait for in-flight tasks
            logger.info(f"Step 2/4: Waiting {self.grace_period}s for task completion")
            await self.wait_for_tasks_with_timeout()

            # Step 3: Stop all services
            logger.info("Step 3/4: Stopping all services")
            if self.service_manager:
                await self.service_manager.stop_all()

            # Step 4: Exit
            logger.info("Step 4/4: Exiting process")

        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}")
        finally:
            sys.exit(1)

    async def immediate_shutdown(self):
        """
        Perform immediate shutdown without waiting.
        """
        logger.critical("Performing immediate shutdown")

        if self.service_manager:
            await self.service_manager.stop_all()

        sys.exit(1)

    async def wait_for_tasks_with_timeout(self):
        """
        Wait for tasks to complete with configured timeout.
        """
        start_time = datetime.now()

        while (datetime.now() - start_time).total_seconds() < self.grace_period:
            # Check if tasks are complete
            if self.service_manager:
                task_count = await self.service_manager.get_active_task_count()
                if task_count == 0:
                    logger.info("All tasks completed")
                    return

                logger.info(f"Waiting for {task_count} tasks to complete...")

            await asyncio.sleep(5)

        # Force shutdown if we exceed force_after timeout
        if (datetime.now() - start_time).total_seconds() >= self.force_after:
            logger.warning(f"Force shutdown after {self.force_after}s")
```

## Integration Points

### 1. AsyncServiceManager
```python
class AsyncServiceManager:
    def __init__(self, config):
        # ... existing init ...

        # Initialize heartbeat monitor
        if config.get_redis_heartbeat_enabled():
            self.heartbeat_monitor = HeartbeatMonitor(
                config_manager=self.config,
                redis_client=self.smart_manager.redis,
                service_manager=self
            )

    async def monitor_loop(self):
        # Start heartbeat monitor task
        if self.heartbeat_monitor:
            heartbeat_task = asyncio.create_task(
                self.heartbeat_monitor.heartbeat_loop()
            )

        # ... existing monitor loop ...
```

### 2. Configuration Manager
```python
class ConfigurationManager:
    def get_redis_heartbeat_config(self) -> dict:
        """Get Redis heartbeat configuration from gleitzeit.yaml"""
        return self.config.get('redis', {}).get('heartbeat', {})

    def get_redis_shutdown_config(self) -> dict:
        """Get Redis shutdown configuration from gleitzeit.yaml"""
        return self.config.get('redis', {}).get('shutdown', {})

    def get_redis_heartbeat_enabled(self) -> bool:
        """Check if heartbeat monitoring is enabled"""
        return self.get_redis_heartbeat_config().get('enabled', True)
```

## Benefits

1. **Configurable via gleitzeit.yaml**: All timeouts and behaviors configured in one place
2. **Predictable Behavior**: Clear state transitions and escalation path
3. **Observable**: Comprehensive logging at each state
4. **Graceful**: Services get time to complete work
5. **Recoverable**: Automatically recovers when Redis returns
6. **No Infinite Loops**: System shuts down cleanly after persistent failures

## Default Behavior

With default configuration:
1. **0-90s**: Retry with backoff, WARNING state after 3 failures
2. **90s-120s**: WARNING state, more frequent logging
3. **120s-300s**: CRITICAL state, services prepare for shutdown
4. **300s+**: Initiate graceful shutdown with 30s grace period
5. **360s**: Force shutdown if tasks haven't completed

## Testing Recommendations

1. **Test Redis recovery**: Stop Redis for 1 minute, verify recovery
2. **Test graceful shutdown**: Stop Redis for 6 minutes, verify clean shutdown
3. **Test configuration**: Modify gleitzeit.yaml values, verify behavior changes
4. **Test task completion**: Have long-running tasks during shutdown
5. **Test immediate mode**: Configure immediate shutdown, verify behavior