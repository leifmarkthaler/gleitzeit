"""
Circuit Breaker pattern implementation for Gleitzeit

Prevents cascading failures by failing fast when external services are down.
Maintains the hard-fail approach while protecting external dependencies.
"""

import time
import asyncio
import logging
from typing import Optional, Dict, Any, Callable, TypeVar, Generic
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"       # Normal operation, requests pass through
    OPEN = "open"           # Service is down, requests fail immediately
    HALF_OPEN = "half_open" # Testing if service recovered


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open"""
    def __init__(self, service_name: str, opened_at: float, reset_timeout: int):
        self.service_name = service_name
        self.opened_at = opened_at
        self.reset_timeout = reset_timeout
        self.time_until_reset = max(0, reset_timeout - (time.time() - opened_at))
        super().__init__(
            f"Circuit breaker for '{service_name}' is OPEN. "
            f"Too many recent failures. Retry in {self.time_until_reset:.0f}s"
        )


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior"""
    failure_threshold: int = 5          # Failures before opening circuit
    success_threshold: int = 2          # Successes in half-open before closing
    reset_timeout: int = 60             # Seconds before trying half-open
    half_open_max_calls: int = 3        # Max concurrent calls in half-open state

    # What counts as a failure
    failure_exceptions: tuple = (Exception,)  # Which exceptions trigger failure count
    exclude_exceptions: tuple = ()            # Exceptions that don't count as failures

    # Optional Redis backing for distributed circuit breakers
    use_redis: bool = False
    redis_key_prefix: str = "circuit_breaker"

    @classmethod
    def for_external_service(cls) -> 'CircuitBreakerConfig':
        """Preset for external HTTP services"""
        return cls(
            failure_threshold=5,
            success_threshold=2,
            reset_timeout=60,
            half_open_max_calls=3
        )

    @classmethod
    def for_database(cls) -> 'CircuitBreakerConfig':
        """Preset for database connections"""
        return cls(
            failure_threshold=3,
            success_threshold=1,
            reset_timeout=30,
            half_open_max_calls=1
        )


@dataclass
class CircuitBreakerStats:
    """Statistics for monitoring circuit breaker behavior"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # Calls rejected due to open circuit

    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None

    consecutive_failures: int = 0
    consecutive_successes: int = 0

    state_changes: list = field(default_factory=list)

    def record_state_change(self, from_state: CircuitState, to_state: CircuitState):
        """Record state transition for monitoring"""
        self.state_changes.append({
            'from': from_state.value,
            'to': to_state.value,
            'timestamp': datetime.utcnow().isoformat()
        })
        # Keep only last 100 transitions
        if len(self.state_changes) > 100:
            self.state_changes = self.state_changes[-100:]


class CircuitBreaker(Generic[T]):
    """
    Circuit breaker implementation for protecting external service calls.

    Usage:
        breaker = CircuitBreaker("ollama", config)
        try:
            result = await breaker.call(async_function, arg1, arg2)
        except CircuitOpenError:
            # Circuit is open, handle gracefully
            pass
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        redis_client: Optional[Any] = None
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.redis = redis_client if config and config.use_redis else None

        # Internal state
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._circuit_opened_at: Optional[float] = None
        self._half_open_calls = 0

        # Statistics
        self.stats = CircuitBreakerStats()

        # Lock for thread-safe state changes
        self._lock = asyncio.Lock()

        logger.info(
            "Circuit breaker '%s' initialized with threshold=%s",
            name,
            self.config.failure_threshold,
        )

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for timeout transitions"""
        if self._state == CircuitState.OPEN:
            if self._circuit_opened_at:
                time_open = time.time() - self._circuit_opened_at
                if time_open >= self.config.reset_timeout:
                    # Transition to half-open
                    logger.info(f"Circuit breaker '{self.name}' transitioning to HALF_OPEN after {time_open:.0f}s")
                    self._transition_to_half_open()
        return self._state

    def is_open(self) -> bool:
        """Check if circuit is open (failing fast)"""
        return self.state == CircuitState.OPEN

    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)"""
        return self.state == CircuitState.CLOSED

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute function through circuit breaker.

        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitOpenError: Circuit is open
            Exception: Original exception from function
        """
        async with self._lock:
            current_state = self.state

            # Check if we should fail fast
            if current_state == CircuitState.OPEN:
                self.stats.rejected_calls += 1
                raise CircuitOpenError(self.name, self._circuit_opened_at, self.config.reset_timeout)

            # Check half-open call limit
            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    self.stats.rejected_calls += 1
                    raise CircuitOpenError(self.name, self._circuit_opened_at, self.config.reset_timeout)
                self._half_open_calls += 1

        # Try to execute the function
        try:
            self.stats.total_calls += 1

            # Execute the actual function
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Record success
            await self._record_success()
            return result

        except Exception as e:
            # Check if this exception should trigger the circuit breaker
            if self._should_count_as_failure(e):
                await self._record_failure(e)
            raise

        finally:
            # Decrement half-open counter
            if current_state == CircuitState.HALF_OPEN:
                async with self._lock:
                    self._half_open_calls = max(0, self._half_open_calls - 1)

    async def _record_success(self):
        """Record successful call"""
        async with self._lock:
            self.stats.successful_calls += 1
            self.stats.consecutive_successes += 1
            self.stats.consecutive_failures = 0
            self.stats.last_success_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                logger.debug(f"Circuit breaker '{self.name}' half-open success {self._success_count}/{self.config.success_threshold}")

                if self._success_count >= self.config.success_threshold:
                    # Close the circuit
                    self._transition_to_closed()

            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    async def _record_failure(self, error: Exception):
        """Record failed call"""
        async with self._lock:
            self.stats.failed_calls += 1
            self.stats.consecutive_failures += 1
            self.stats.consecutive_successes = 0
            self.stats.last_failure_time = time.time()
            self._last_failure_time = time.time()

            if self._state == CircuitState.CLOSED:
                self._failure_count += 1
                logger.warning(f"Circuit breaker '{self.name}' failure {self._failure_count}/{self.config.failure_threshold}: {error}")

                if self._failure_count >= self.config.failure_threshold:
                    # Open the circuit
                    self._transition_to_open()

            elif self._state == CircuitState.HALF_OPEN:
                # Single failure in half-open reopens circuit
                logger.warning(f"Circuit breaker '{self.name}' failed in HALF_OPEN state: {error}")
                self._transition_to_open()

    def _should_count_as_failure(self, error: Exception) -> bool:
        """Determine if exception should count as failure"""
        # Check exclusions first
        if isinstance(error, self.config.exclude_exceptions):
            return False

        # Check if it matches failure exceptions
        return isinstance(error, self.config.failure_exceptions)

    def _transition_to_open(self):
        """Transition to OPEN state"""
        old_state = self._state
        self._state = CircuitState.OPEN
        self._circuit_opened_at = time.time()
        self._failure_count = 0
        self.stats.record_state_change(old_state, CircuitState.OPEN)
        logger.error(f"Circuit breaker '{self.name}' is now OPEN (will retry in {self.config.reset_timeout}s)")

    def _transition_to_closed(self):
        """Transition to CLOSED state"""
        old_state = self._state
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._circuit_opened_at = None
        self.stats.record_state_change(old_state, CircuitState.CLOSED)
        logger.info(f"Circuit breaker '{self.name}' is now CLOSED (normal operation)")

    def _transition_to_half_open(self):
        """Transition to HALF_OPEN state"""
        old_state = self._state
        self._state = CircuitState.HALF_OPEN
        self._success_count = 0
        self._half_open_calls = 0
        self.stats.record_state_change(old_state, CircuitState.HALF_OPEN)
        logger.info(f"Circuit breaker '{self.name}' is now HALF_OPEN (testing recovery)")

    def reset(self):
        """Manually reset the circuit breaker"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._circuit_opened_at = None
        self._half_open_calls = 0
        logger.info(f"Circuit breaker '{self.name}' manually reset to CLOSED")

    def get_status(self) -> Dict[str, Any]:
        """Get current status for monitoring"""
        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self._failure_count,
            'success_count': self._success_count,
            'stats': {
                'total_calls': self.stats.total_calls,
                'successful_calls': self.stats.successful_calls,
                'failed_calls': self.stats.failed_calls,
                'rejected_calls': self.stats.rejected_calls,
                'consecutive_failures': self.stats.consecutive_failures,
                'consecutive_successes': self.stats.consecutive_successes,
                'last_failure': self.stats.last_failure_time,
                'last_success': self.stats.last_success_time
            },
            'config': {
                'failure_threshold': self.config.failure_threshold,
                'success_threshold': self.config.success_threshold,
                'reset_timeout': self.config.reset_timeout
            }
        }


class RedisBackedCircuitBreaker(CircuitBreaker[T]):
    """
    Distributed circuit breaker using Redis for state sharing.

    Allows multiple instances to share circuit state.
    """

    def __init__(self, name: str, config: CircuitBreakerConfig, redis_client):
        super().__init__(name, config, redis_client)
        self.redis = redis_client
        self.redis_key = f"{config.redis_key_prefix}:{name}"

    async def _load_state(self):
        """Load state from Redis"""
        state_data = await self.redis.hgetall(self.redis_key.encode())
        if state_data:
            self._state = CircuitState(state_data.get(b'state', b'closed').decode())
            self._failure_count = int(state_data.get(b'failure_count', b'0'))
            self._success_count = int(state_data.get(b'success_count', b'0'))
            opened_at = state_data.get(b'opened_at')
            self._circuit_opened_at = float(opened_at) if opened_at else None

    async def _save_state(self):
        """Save state to Redis"""
        state_data = {
            b'state': self._state.value.encode(),
            b'failure_count': str(self._failure_count).encode(),
            b'success_count': str(self._success_count).encode()
        }
        if self._circuit_opened_at:
            state_data[b'opened_at'] = str(self._circuit_opened_at).encode()

        await self.redis.hset(self.redis_key.encode(), mapping=state_data)
        await self.redis.expire(self.redis_key.encode(), 3600)  # Expire after 1 hour
