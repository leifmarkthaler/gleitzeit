"""
Idempotency Framework for Safe Task Reruns.

This module provides mechanisms to track task execution state and determine
if tasks can be safely rerun without side effects. Critical for horizontal
scaling and recovery scenarios.
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from datetime import datetime, timedelta

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class IdempotencyStrategy(Enum):
    """Strategies for determining task idempotency."""

    ALWAYS_SAFE = "always_safe"  # Task can always be rerun (read-only)
    NEVER_SAFE = "never_safe"    # Task must never be rerun (external effects)
    CHECK_STATE = "check_state"  # Check execution state before rerun
    CONDITIONAL = "conditional"  # Check custom conditions
    TIME_BASED = "time_based"    # Safe to rerun after certain time


class ExecutionState(Enum):
    """Track task execution state for idempotency checks."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIALLY_COMPLETED = "partially_completed"


class IdempotencyKey:
    """Generate and manage idempotency keys for tasks."""

    @staticmethod
    def generate(
        task_id: str,
        params: Optional[Dict[str, Any]] = None,
        version: Optional[str] = None
    ) -> str:
        """
        Generate a deterministic idempotency key.

        Args:
            task_id: Task identifier
            params: Task parameters (included in key)
            version: Task version (for code changes)

        Returns:
            Deterministic idempotency key
        """
        key_parts = [task_id]

        if params:
            # Sort params for deterministic ordering
            params_str = json.dumps(params, sort_keys=True)
            params_hash = hashlib.sha256(params_str.encode()).hexdigest()[:8]
            key_parts.append(params_hash)

        if version:
            key_parts.append(version)

        return ":".join(key_parts)


class IdempotencyManager:
    """
    Manages idempotency for task execution.

    This is stateless - all state stored in Redis.
    """

    def __init__(
        self,
        redis: Redis,
        default_ttl: int = 86400,  # 24 hours
        namespace: str = "idempotency"
    ):
        """
        Initialize idempotency manager.

        Args:
            redis: Redis connection
            default_ttl: Default TTL for idempotency records (seconds)
            namespace: Redis key namespace
        """
        self.redis = redis
        self.default_ttl = default_ttl
        self.namespace = namespace

    def _make_key(self, idempotency_key: str) -> str:
        """Create Redis key for idempotency record."""
        return f"gleitzeit:{self.namespace}:{idempotency_key}"

    async def check_can_execute(
        self,
        task_id: str,
        strategy: IdempotencyStrategy = IdempotencyStrategy.CHECK_STATE,
        params: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a task can be executed safely.

        Args:
            task_id: Task identifier
            strategy: Idempotency strategy to use
            params: Task parameters
            metadata: Additional metadata for decision

        Returns:
            Tuple of (can_execute, reason)
        """
        # Generate idempotency key
        idempotency_key = IdempotencyKey.generate(
            task_id,
            params,
            metadata.get("version") if metadata else None
        )

        # Handle different strategies
        if strategy == IdempotencyStrategy.ALWAYS_SAFE:
            return True, "Task is always safe to execute"

        elif strategy == IdempotencyStrategy.NEVER_SAFE:
            # Check if already executed
            state = await self.get_execution_state(idempotency_key)
            if state and state != ExecutionState.NOT_STARTED:
                return False, f"Task already executed with state: {state.value}"
            return True, "First execution allowed"

        elif strategy == IdempotencyStrategy.CHECK_STATE:
            return await self._check_state_based(idempotency_key)

        elif strategy == IdempotencyStrategy.TIME_BASED:
            cooldown = metadata.get("cooldown_seconds", 300) if metadata else 300
            return await self._check_time_based(idempotency_key, cooldown)

        elif strategy == IdempotencyStrategy.CONDITIONAL:
            if not metadata or "condition_checker" not in metadata:
                return False, "No condition checker provided"
            checker = metadata["condition_checker"]
            return await checker(task_id, params)

        return False, f"Unknown strategy: {strategy}"

    async def _check_state_based(
        self,
        idempotency_key: str
    ) -> Tuple[bool, Optional[str]]:
        """Check if task can execute based on current state."""
        state = await self.get_execution_state(idempotency_key)

        if not state or state == ExecutionState.NOT_STARTED:
            return True, "Task not started, safe to execute"

        if state == ExecutionState.IN_PROGRESS:
            # Check if stuck (e.g., running for too long)
            record = await self.get_execution_record(idempotency_key)
            if record:
                started_at = record.get("started_at", 0)
                if time.time() - started_at > 3600:  # 1 hour timeout
                    return True, "Task stuck in progress, safe to retry"
            return False, "Task currently in progress"

        if state == ExecutionState.COMPLETED:
            return False, "Task already completed successfully"

        if state == ExecutionState.FAILED:
            # Failed tasks can be retried
            return True, "Previous execution failed, safe to retry"

        if state == ExecutionState.PARTIALLY_COMPLETED:
            # Need more context for partial completions
            return False, "Task partially completed, manual intervention needed"

        return False, f"Unknown state: {state}"

    async def _check_time_based(
        self,
        idempotency_key: str,
        cooldown_seconds: int
    ) -> Tuple[bool, Optional[str]]:
        """Check if enough time has passed since last execution."""
        record = await self.get_execution_record(idempotency_key)

        if not record:
            return True, "No previous execution"

        last_execution = record.get("completed_at") or record.get("started_at", 0)
        time_since = time.time() - last_execution

        if time_since >= cooldown_seconds:
            return True, f"Cooldown period elapsed ({time_since:.0f}s >= {cooldown_seconds}s)"

        remaining = cooldown_seconds - time_since
        return False, f"Cooldown period not elapsed ({remaining:.0f}s remaining)"

    async def record_execution_start(
        self,
        task_id: str,
        params: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None
    ) -> str:
        """
        Record that task execution has started.

        Args:
            task_id: Task identifier
            params: Task parameters
            metadata: Additional metadata
            ttl: Custom TTL for this record

        Returns:
            Idempotency key for this execution
        """
        idempotency_key = IdempotencyKey.generate(
            task_id,
            params,
            metadata.get("version") if metadata else None
        )

        record = {
            "task_id": task_id,
            "state": ExecutionState.IN_PROGRESS.value,
            "started_at": time.time(),
            "params": params,
            "metadata": metadata
        }

        key = self._make_key(idempotency_key)
        ttl = ttl or self.default_ttl

        await self.redis.setex(
            key,
            ttl,
            json.dumps(record)
        )

        logger.debug(f"Recorded execution start for {task_id} with key {idempotency_key}")
        return idempotency_key

    async def record_execution_complete(
        self,
        idempotency_key: str,
        result: Optional[Any] = None,
        error: Optional[str] = None
    ):
        """
        Record task execution completion.

        Args:
            idempotency_key: Idempotency key from record_execution_start
            result: Task result (if successful)
            error: Error message (if failed)
        """
        key = self._make_key(idempotency_key)
        record_str = await self.redis.get(key)

        if not record_str:
            logger.warning(f"No execution record found for {idempotency_key}")
            return

        record = json.loads(record_str)
        record["completed_at"] = time.time()

        if error:
            record["state"] = ExecutionState.FAILED.value
            record["error"] = error
        else:
            record["state"] = ExecutionState.COMPLETED.value
            if result is not None:
                record["result"] = result

        # Get remaining TTL
        ttl = await self.redis.ttl(key)
        if ttl > 0:
            await self.redis.setex(
                key,
                ttl,
                json.dumps(record)
            )
        else:
            # Use default TTL if original expired
            await self.redis.setex(
                key,
                self.default_ttl,
                json.dumps(record)
            )

        state = record["state"]
        logger.debug(f"Recorded execution completion for {idempotency_key}: {state}")

    async def get_execution_state(
        self,
        idempotency_key: str
    ) -> Optional[ExecutionState]:
        """
        Get current execution state for a task.

        Args:
            idempotency_key: Idempotency key

        Returns:
            Current execution state or None
        """
        record = await self.get_execution_record(idempotency_key)
        if not record:
            return None

        state_str = record.get("state")
        if not state_str:
            return None

        try:
            return ExecutionState(state_str)
        except ValueError:
            logger.error(f"Invalid state in record: {state_str}")
            return None

    async def get_execution_record(
        self,
        idempotency_key: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get full execution record.

        Args:
            idempotency_key: Idempotency key

        Returns:
            Execution record or None
        """
        key = self._make_key(idempotency_key)
        record_str = await self.redis.get(key)

        if not record_str:
            return None

        try:
            return json.loads(record_str)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in execution record: {record_str}")
            return None

    async def cleanup_expired_records(
        self,
        older_than_seconds: int = 86400
    ) -> int:
        """
        Clean up old execution records.

        This is optional since Redis TTL handles expiry, but can be
        used for explicit cleanup.

        Args:
            older_than_seconds: Age threshold for cleanup

        Returns:
            Number of records cleaned up
        """
        pattern = f"gleitzeit:{self.namespace}:*"
        cleaned = 0
        now = time.time()

        async for key in self.redis.scan_iter(match=pattern):
            try:
                record_str = await self.redis.get(key)
                if not record_str:
                    continue

                record = json.loads(record_str)
                completed_at = record.get("completed_at", 0)
                started_at = record.get("started_at", 0)

                # Use completed time if available, otherwise started time
                last_time = completed_at or started_at

                if last_time and (now - last_time) > older_than_seconds:
                    await self.redis.delete(key)
                    cleaned += 1

            except Exception as e:
                logger.error(f"Error cleaning up {key}: {e}")

        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired idempotency records")

        return cleaned


class TaskIdempotencyDecorator:
    """
    Decorator for marking task idempotency strategies.

    Usage:
        @idempotent(strategy=IdempotencyStrategy.CHECK_STATE)
        async def my_task(params):
            ...
    """

    def __init__(
        self,
        strategy: IdempotencyStrategy = IdempotencyStrategy.CHECK_STATE,
        ttl: Optional[int] = None,
        cooldown: Optional[int] = None
    ):
        """
        Initialize decorator.

        Args:
            strategy: Idempotency strategy
            ttl: TTL for idempotency records
            cooldown: Cooldown period for TIME_BASED strategy
        """
        self.strategy = strategy
        self.ttl = ttl
        self.cooldown = cooldown

    def __call__(self, func):
        """Decorate function with idempotency metadata."""
        func._idempotency_strategy = self.strategy
        func._idempotency_ttl = self.ttl
        func._idempotency_cooldown = self.cooldown
        return func


# Convenience decorator instances
idempotent = TaskIdempotencyDecorator
always_safe = TaskIdempotencyDecorator(IdempotencyStrategy.ALWAYS_SAFE)
never_safe = TaskIdempotencyDecorator(IdempotencyStrategy.NEVER_SAFE)
time_based = lambda cooldown: TaskIdempotencyDecorator(
    IdempotencyStrategy.TIME_BASED,
    cooldown=cooldown
)