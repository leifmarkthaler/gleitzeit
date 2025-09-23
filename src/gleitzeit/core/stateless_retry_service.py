"""
Stateless retry service for Gleitzeit.

All state is managed in Redis, ensuring true horizontal scalability.
This service can be called from any worker without coordination issues.
"""

import asyncio
import time
import json
import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class RetryDecision(Enum):
    """Retry decision outcomes"""
    RETRY = "retry"
    SKIP = "skip"  # Don't retry this error type
    BUDGET_EXHAUSTED = "budget_exhausted"
    MAX_ATTEMPTS = "max_attempts"
    PERMANENT_FAILURE = "permanent_failure"


@dataclass
class RetryContext:
    """Context for retry decision"""
    task_id: str
    workflow_id: str
    error_type: str
    error_msg: str
    current_attempt: int
    service_name: Optional[str] = None
    handler_type: Optional[str] = None


class StatelessRetryService:
    """
    Completely stateless retry service using Redis for all state.

    This service provides:
    - Retry decisions based on Redis-stored configuration
    - Distributed retry budgeting using Redis
    - Metrics collection in Redis streams
    - Adaptive configuration stored in Redis
    """

    # Lua scripts for atomic operations
    CONSUME_BUDGET_SCRIPT = """
    -- Consume from retry budget atomically
    local budget_key = KEYS[1]
    local refill_key = KEYS[2]
    local max_tokens = tonumber(ARGV[1])
    local refill_rate = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])

    -- Get last refill time
    local last_refill = tonumber(redis.call('get', refill_key) or now)

    -- Calculate tokens to add
    local elapsed = now - last_refill
    local tokens_to_add = elapsed * refill_rate

    -- Get current tokens
    local current_tokens = tonumber(redis.call('get', budget_key) or max_tokens)

    -- Refill tokens
    current_tokens = math.min(current_tokens + tokens_to_add, max_tokens)

    -- Try to consume
    if current_tokens >= 1 then
        redis.call('set', budget_key, current_tokens - 1)
        redis.call('set', refill_key, now)
        return 1
    else
        redis.call('set', budget_key, current_tokens)
        redis.call('set', refill_key, now)
        return 0
    end
    """

    INCREMENT_METRICS_SCRIPT = """
    -- Atomically increment retry metrics
    local metrics_key = KEYS[1]
    local window_key = KEYS[2]
    local error_type = ARGV[1]
    local task_id = ARGV[2]
    local now = tonumber(ARGV[3])
    local window_size = tonumber(ARGV[4])

    -- Increment counters
    redis.call('hincrby', metrics_key, 'total_retries', 1)
    redis.call('hincrby', metrics_key, 'error:' .. error_type, 1)
    redis.call('hincrby', metrics_key, 'task:' .. task_id, 1)

    -- Add to sliding window
    redis.call('zadd', window_key, now, task_id .. ':' .. now)

    -- Clean old entries from window
    local cutoff = now - window_size
    redis.call('zremrangebyscore', window_key, 0, cutoff)

    return redis.call('hget', metrics_key, 'total_retries')
    """

    def __init__(self, redis_client, config: Optional[Dict[str, Any]] = None):
        """
        Initialize stateless retry service.

        Args:
            redis_client: Redis client for state management
            config: Optional configuration overrides
        """
        self.redis = redis_client
        self.config = config or {}

        # Default configuration
        self.default_max_retries = self.config.get('max_retries', 2)
        self.default_base_delay = self.config.get('base_delay', 1.0)
        self.default_max_delay = self.config.get('max_delay', 30.0)
        self.default_multiplier = self.config.get('multiplier', 2.0)

        # Budget defaults
        self.default_budget_per_minute = self.config.get('budget_per_minute', 100)
        self.default_budget_per_hour = self.config.get('budget_per_hour', 3000)

        # Non-retryable error types (centralized error types)
        self.non_retryable_errors = {
            'CircuitOpenError',
            'HandlerExecutionError',  # Handler-level execution errors (Python, SQL, etc.)
            'ValidationError',        # Validation failures
            'AuthenticationError',    # Auth failures (wrong credentials)
            'AuthorizationError',     # Permission denied
            'NotFoundError',         # Resource not found
            'ConfigurationError'     # Misconfiguration
        }

        # Non-retryable error patterns in error messages
        self.non_retryable_patterns = [
            '[TASK_EXECUTION_FAILED]',
            '[INVALID_PARAMS]',
            '[VALIDATION_FAILED]',
            'HandlerExecutionError',
            'Missing required parameter',
            'validation',
            'invalid',
            'not found',
            'permission denied',
            'unauthorized',
            'forbidden'
        ]

    async def should_retry(self, context: RetryContext) -> Tuple[RetryDecision, Dict[str, Any]]:
        """
        Determine if retry should be attempted.

        All decisions based on Redis state.

        Args:
            context: Retry context with task/error information

        Returns:
            Tuple of (decision, metadata)
        """
        # Check if error type is retryable
        if not self._is_retryable_error(context):
            return RetryDecision.SKIP, {'reason': 'non_retryable_error'}

        # Get retry configuration from Redis
        config = await self._get_retry_config(context.workflow_id, context.task_id)

        # Check max attempts
        if context.current_attempt >= config['max_retries']:
            return RetryDecision.MAX_ATTEMPTS, {
                'max_retries': config['max_retries'],
                'current_attempt': context.current_attempt
            }

        # Check budget
        if not await self._check_budget(context):
            return RetryDecision.BUDGET_EXHAUSTED, {
                'workflow_id': context.workflow_id,
                'service': context.service_name
            }

        # Record metrics
        await self._record_retry_attempt(context)

        return RetryDecision.RETRY, {
            'delay': await self.calculate_delay(context, config),
            'config': config
        }

    def _is_retryable_error(self, context: RetryContext) -> bool:
        """Check if error type should be retried."""
        # Check non-retryable error types
        if context.error_type in self.non_retryable_errors:
            return False

        # Check non-retryable patterns
        error_msg_lower = context.error_msg.lower()
        for pattern in self.non_retryable_patterns:
            if pattern.lower() in error_msg_lower:
                return False

        return True

    async def _get_retry_config(
        self,
        workflow_id: str,
        task_id: str
    ) -> Dict[str, Any]:
        """
        Get retry configuration from Redis.

        Hierarchy:
        1. Task-specific config
        2. Workflow-specific config
        3. Global defaults
        """
        # Try task-specific config
        task_config_key = f"retry:config:task:{workflow_id}:{task_id}"
        task_config = await self.redis.hgetall(task_config_key.encode())
        if task_config:
            return self._decode_config(task_config)

        # Try workflow-specific config
        wf_config_key = f"retry:config:workflow:{workflow_id}"
        wf_config = await self.redis.hgetall(wf_config_key.encode())
        if wf_config:
            return self._decode_config(wf_config)

        # Try global config
        global_config_key = "retry:config:global"
        global_config = await self.redis.hgetall(global_config_key.encode())
        if global_config:
            return self._decode_config(global_config)

        # Return defaults
        return {
            'max_retries': self.default_max_retries,
            'base_delay': self.default_base_delay,
            'max_delay': self.default_max_delay,
            'multiplier': self.default_multiplier,
            'strategy': 'exponential_jitter'
        }

    def _decode_config(self, redis_config: Dict[bytes, bytes]) -> Dict[str, Any]:
        """Decode Redis config to Python dict."""
        config = {}
        for key, value in redis_config.items():
            key_str = key.decode()
            value_str = value.decode()

            # Try to parse as number
            try:
                if '.' in value_str:
                    config[key_str] = float(value_str)
                else:
                    config[key_str] = int(value_str)
            except ValueError:
                config[key_str] = value_str

        return config

    async def _check_budget(self, context: RetryContext) -> bool:
        """
        Check retry budget using Redis.

        Uses atomic Lua script for token bucket.
        """
        # Determine budget scope
        if context.service_name:
            budget_key = f"retry:budget:service:{context.service_name}"
            refill_key = f"retry:budget:refill:service:{context.service_name}"
            max_tokens = self.default_budget_per_minute / 4  # Service gets 1/4
            refill_rate = max_tokens / 60  # Per second
        else:
            budget_key = f"retry:budget:workflow:{context.workflow_id}"
            refill_key = f"retry:budget:refill:workflow:{context.workflow_id}"
            max_tokens = self.default_budget_per_minute / 2  # Workflow gets 1/2
            refill_rate = max_tokens / 60

        # Execute atomic budget consumption
        result = await self.redis.eval(
            self.CONSUME_BUDGET_SCRIPT,
            2,  # Number of keys
            budget_key.encode(),
            refill_key.encode(),
            str(max_tokens).encode(),
            str(refill_rate).encode(),
            str(time.time()).encode()
        )

        return result == 1

    async def _record_retry_attempt(self, context: RetryContext) -> None:
        """Record retry metrics in Redis."""
        metrics_key = f"retry:metrics:{context.workflow_id}"
        window_key = f"retry:metrics:window:{context.workflow_id}"

        # Record in Redis stream for time-series
        stream_key = f"retry:events:{context.workflow_id}"
        await self.redis.xadd(
            stream_key.encode(),
            {
                b'task_id': context.task_id.encode(),
                b'error_type': context.error_type.encode(),
                b'error_msg': context.error_msg.encode(),
                b'attempt': str(context.current_attempt).encode(),
                b'timestamp': str(time.time()).encode()
            }
        )

        # Update metrics atomically
        await self.redis.eval(
            self.INCREMENT_METRICS_SCRIPT,
            2,
            metrics_key.encode(),
            window_key.encode(),
            context.error_type.encode(),
            context.task_id.encode(),
            str(time.time()).encode(),
            str(3600).encode()  # 1 hour window
        )

        # Set TTL on keys (24 hours)
        await self.redis.expire(metrics_key.encode(), 86400)
        await self.redis.expire(window_key.encode(), 86400)
        await self.redis.expire(stream_key.encode(), 86400)

    async def calculate_delay(
        self,
        context: RetryContext,
        config: Dict[str, Any]
    ) -> float:
        """
        Calculate retry delay based on strategy.

        Args:
            context: Retry context
            config: Retry configuration

        Returns:
            Delay in seconds
        """
        strategy = config.get('strategy', 'exponential_jitter')
        base_delay = config.get('base_delay', self.default_base_delay)
        max_delay = config.get('max_delay', self.default_max_delay)
        multiplier = config.get('multiplier', self.default_multiplier)

        if strategy == 'fixed':
            delay = base_delay

        elif strategy == 'linear':
            delay = base_delay * (context.current_attempt + 1) * multiplier

        elif strategy == 'exponential':
            delay = base_delay * (multiplier ** context.current_attempt)

        elif strategy == 'exponential_jitter':
            # Full jitter
            exp_delay = base_delay * (multiplier ** context.current_attempt)
            import random
            delay = random.uniform(0, exp_delay)

        else:
            delay = base_delay

        # Apply max delay cap
        return min(delay, max_delay)

    async def record_retry_success(
        self,
        workflow_id: str,
        task_id: str
    ) -> None:
        """Record successful retry."""
        metrics_key = f"retry:metrics:{workflow_id}"
        await self.redis.hincrby(metrics_key.encode(), b'total_retries', 1)
        await self.redis.hincrby(metrics_key.encode(), b'successful_retries', 1)

        # Update task-specific success
        task_key = f"retry:metrics:task:{workflow_id}:{task_id}"
        await self.redis.hincrby(task_key.encode(), b'success', 1)

    async def record_retry_failure(
        self,
        workflow_id: str,
        task_id: str
    ) -> None:
        """Record retry exhaustion."""
        metrics_key = f"retry:metrics:{workflow_id}"
        await self.redis.hincrby(metrics_key.encode(), b'total_retries', 1)
        await self.redis.hincrby(metrics_key.encode(), b'failed_retries', 1)

        # Update task-specific failure
        task_key = f"retry:metrics:task:{workflow_id}:{task_id}"
        await self.redis.hincrby(task_key.encode(), b'permanent_failure', 1)

    async def get_retry_metrics(
        self,
        workflow_id: str
    ) -> Dict[str, Any]:
        """Get retry metrics from Redis."""
        metrics_key = f"retry:metrics:{workflow_id}"
        window_key = f"retry:metrics:window:{workflow_id}"

        # Get basic metrics
        metrics = await self.redis.hgetall(metrics_key.encode())

        # Get window size (recent retries)
        window_size = await self.redis.zcard(window_key.encode())

        # Decode and structure metrics
        result = {
            'workflow_id': workflow_id,
            'total_retries': int(metrics.get(b'total_retries', 0)),
            'successful_retries': int(metrics.get(b'successful_retries', 0)),
            'failed_retries': int(metrics.get(b'failed_retries', 0)),
            'recent_retries_count': window_size,
            'error_distribution': {}
        }

        # Extract error distribution
        for key, value in metrics.items():
            key_str = key.decode()
            if key_str.startswith('error:'):
                error_type = key_str[6:]
                result['error_distribution'][error_type] = int(value)

        # Calculate success rate
        total = result['total_retries']
        if total > 0:
            result['success_rate'] = (
                result['successful_retries'] / total * 100
            )
        else:
            result['success_rate'] = 0.0

        return result

    async def set_retry_config(
        self,
        config: Dict[str, Any],
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None
    ) -> None:
        """
        Set retry configuration in Redis.

        Args:
            config: Configuration dictionary
            workflow_id: Optional workflow ID for workflow-specific config
            task_id: Optional task ID for task-specific config
        """
        if task_id and workflow_id:
            key = f"retry:config:task:{workflow_id}:{task_id}"
        elif workflow_id:
            key = f"retry:config:workflow:{workflow_id}"
        else:
            key = "retry:config:global"

        # Store each config item
        mapping = {}
        for k, v in config.items():
            mapping[k.encode()] = str(v).encode()

        if mapping:
            await self.redis.hset(key.encode(), mapping=mapping)

    async def reset_budget(
        self,
        workflow_id: Optional[str] = None,
        service_name: Optional[str] = None
    ) -> None:
        """Reset retry budget (emergency refill)."""
        if service_name:
            budget_key = f"retry:budget:service:{service_name}"
            max_tokens = self.default_budget_per_minute / 4
        elif workflow_id:
            budget_key = f"retry:budget:workflow:{workflow_id}"
            max_tokens = self.default_budget_per_minute / 2
        else:
            budget_key = "retry:budget:global"
            max_tokens = self.default_budget_per_minute

        await self.redis.set(budget_key.encode(), str(max_tokens).encode())
        logger.info(f"Reset budget for {budget_key} to {max_tokens} tokens")