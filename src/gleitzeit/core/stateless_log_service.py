"""
Stateless Log Service for Gleitzeit

A completely stateless log service using Redis with global index for efficient querying.
Follows the same pattern as StatelessRetryService and StatelessSignalManager.
"""

import json
import uuid
import random
from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum


class LogLevel(Enum):
    """Log levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class StatelessLogService:
    """
    Stateless log service with global index for efficient querying.

    Design:
    - Logs stored on workflow shard (locality)
    - Global index on shard 0 (queryability)
    - Metadata on shard 0 (for fetching from correct shard)
    """

    # Default TTLs by level (seconds)
    DEFAULT_TTL = {
        "DEBUG": 86400,      # 1 day
        "INFO": 604800,      # 7 days
        "WARNING": 1209600,  # 14 days
        "ERROR": 2592000,    # 30 days
        "CRITICAL": 2592000, # 30 days
    }

    @staticmethod
    def _get_shard(workflow_id: str) -> int:
        """Get shard number for workflow_id."""
        from gleitzeit.core.sharding import default_sharding
        return default_sharding.get_shard(workflow_id)

    @staticmethod
    async def log_error(
        redis,
        message: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        component: str = "system",
        error_type: Optional[str] = None,
        stack_trace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None
    ) -> str:
        """
        Log an error to Redis with global index.

        Args:
            redis: Redis connection
            message: Error message
            workflow_id: Optional workflow ID
            task_id: Optional task ID
            component: Component that logged the error
            error_type: Type of error (e.g., "ConnectionTimeout")
            stack_trace: Stack trace if available
            metadata: Additional metadata
            ttl: Time to live (defaults to 30 days for errors)

        Returns:
            Log ID
        """
        # Generate log ID with timestamp
        timestamp = int(datetime.utcnow().timestamp() * 1000)
        log_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"

        # Determine shard
        if workflow_id:
            shard = StatelessLogService._get_shard(workflow_id)
        else:
            shard = 0  # System errors on shard 0

        # Use default TTL if not specified
        if ttl is None:
            ttl = StatelessLogService.DEFAULT_TTL["ERROR"]

        # Build error log entry
        log_entry = {
            "log_id": log_id,
            "timestamp": timestamp,
            "level": "ERROR",
            "message": message,
            "component": component,
            "workflow_id": workflow_id or "",
            "task_id": task_id or "",
            "error_type": error_type or "UnknownError",
            "stack_trace": stack_trace or "",
            "metadata": metadata or {}
        }

        # 1. Store full log entry on workflow shard
        log_key = f"{{shard:{shard}}}:log:error:{log_id}"
        await redis.set(
            log_key,
            json.dumps(log_entry),
            ex=ttl
        )

        # 2. Add to global error index (shard 0)
        global_index_key = f"{{shard:0}}:log:global:error"
        await redis.zadd(
            global_index_key,
            {log_id: timestamp}
        )
        await redis.expire(global_index_key, ttl)

        # 3. Store metadata for fetching (shard 0)
        meta_key = f"{{shard:0}}:log:meta:{log_id}"
        await redis.hset(
            meta_key,
            mapping={
                "shard": str(shard),
                "workflow_id": workflow_id or "",
                "error_type": error_type or "UnknownError",
                "level": "ERROR",
                "timestamp": str(timestamp)
            }
        )
        await redis.expire(meta_key, ttl)

        # 4. If workflow_id exists, add to workflow error index
        if workflow_id:
            workflow_error_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:errors"
            await redis.zadd(
                workflow_error_key,
                {log_id: timestamp}
            )
            await redis.expire(workflow_error_key, ttl)

        # 5. Publish to WebSocket pub/sub channel for real-time broadcasting
        try:
            await redis.publish(
                'gleitzeit:events',
                json.dumps({
                    'type': 'log_event',
                    'level': 'ERROR',
                    'message': message,
                    'workflow_id': workflow_id,
                    'task_id': task_id,
                    'component': component,
                    'error_type': error_type,
                    'log_id': log_id,
                    'timestamp': datetime.utcnow().isoformat(),
                    'metadata': metadata or {}
                })
            )
        except Exception as e:
            # Don't fail if pub/sub fails - logging is more important
            import logging
            logging.getLogger(__name__).error(f"Failed to publish log to WebSocket: {e}")

        return log_id

    @staticmethod
    async def query_errors(
        redis,
        workflow_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Query error logs.

        Args:
            redis: Redis connection
            workflow_id: Optional workflow ID to filter by
            limit: Maximum number of results
            offset: Offset for pagination
            start_time: Start timestamp (milliseconds)
            end_time: End timestamp (milliseconds)

        Returns:
            List of error log entries
        """
        # Determine which index to query
        if workflow_id:
            # Query workflow-specific errors
            shard = StatelessLogService._get_shard(workflow_id)
            index_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:errors"
        else:
            # Query global error index
            index_key = f"{{shard:0}}:log:global:error"

        # Time range
        min_score = start_time if start_time else "-inf"
        max_score = end_time if end_time else "+inf"

        # Get log IDs from index (newest first)
        log_ids = await redis.zrevrangebyscore(
            index_key,
            max_score,
            min_score,
            start=offset,
            num=limit
        )

        # Fetch error logs
        errors = []
        for log_id in log_ids:
            log_id_str = log_id.decode() if isinstance(log_id, bytes) else log_id

            if workflow_id:
                # We know the shard from workflow_id
                log_key = f"{{shard:{shard}}}:log:error:{log_id_str}"
                log_data = await redis.get(log_key)
            else:
                # Fetch metadata to find which shard
                meta_key = f"{{shard:0}}:log:meta:{log_id_str}"
                meta = await redis.hgetall(meta_key)

                if not meta:
                    continue

                # Get log from correct shard
                log_shard = int(meta[b'shard'].decode())
                log_key = f"{{shard:{log_shard}}}:log:error:{log_id_str}"
                log_data = await redis.get(log_key)

            if log_data:
                errors.append(json.loads(log_data))

        return errors

    @staticmethod
    async def get_error_count(
        redis,
        workflow_id: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> int:
        """
        Get count of errors.

        Args:
            redis: Redis connection
            workflow_id: Optional workflow ID
            start_time: Start timestamp (milliseconds)
            end_time: End timestamp (milliseconds)

        Returns:
            Count of errors
        """
        if workflow_id:
            shard = StatelessLogService._get_shard(workflow_id)
            index_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:errors"
        else:
            index_key = f"{{shard:0}}:log:global:error"

        min_score = start_time if start_time else "-inf"
        max_score = end_time if end_time else "+inf"

        return await redis.zcount(index_key, min_score, max_score)

    @staticmethod
    def _should_sample(sample_rate: float) -> bool:
        """Determine if this log should be recorded based on sample rate"""
        if sample_rate >= 1.0:
            return True
        if sample_rate <= 0.0:
            return False
        return random.random() < sample_rate

    @staticmethod
    async def log_info(
        redis,
        message: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        component: str = "system",
        operation: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None
    ) -> str:
        """
        Log an INFO level event to Redis with global index.

        Args:
            redis: Redis connection
            message: Log message
            workflow_id: Optional workflow ID
            task_id: Optional task ID
            component: Component that logged the event
            operation: Operation name (e.g., "task_execution_started")
            metadata: Additional metadata
            ttl: Time to live (defaults to 7 days for INFO)

        Returns:
            Log ID
        """
        # Generate log ID with timestamp
        timestamp = int(datetime.utcnow().timestamp() * 1000)
        log_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"

        # Determine shard
        if workflow_id:
            shard = StatelessLogService._get_shard(workflow_id)
        else:
            shard = 0  # System logs on shard 0

        # Use default TTL if not specified
        if ttl is None:
            ttl = StatelessLogService.DEFAULT_TTL["INFO"]

        # Build log entry
        log_entry = {
            "log_id": log_id,
            "timestamp": timestamp,
            "level": "INFO",
            "message": message,
            "component": component,
            "workflow_id": workflow_id or "",
            "task_id": task_id or "",
            "operation": operation or "",
            "metadata": metadata or {}
        }

        # 1. Store full log entry on workflow shard
        log_key = f"{{shard:{shard}}}:log:info:{log_id}"
        await redis.set(
            log_key,
            json.dumps(log_entry),
            ex=ttl
        )

        # 2. Add to global info index (shard 0)
        global_index_key = f"{{shard:0}}:log:global:info"
        await redis.zadd(
            global_index_key,
            {log_id: timestamp}
        )
        await redis.expire(global_index_key, ttl)

        # 3. Store metadata for fetching (shard 0)
        meta_key = f"{{shard:0}}:log:meta:{log_id}"
        await redis.hset(
            meta_key,
            mapping={
                "shard": str(shard),
                "workflow_id": workflow_id or "",
                "component": component,
                "level": "INFO",
                "timestamp": str(timestamp)
            }
        )
        await redis.expire(meta_key, ttl)

        # 4. If workflow_id exists, add to workflow info index
        if workflow_id:
            workflow_info_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:info"
            await redis.zadd(
                workflow_info_key,
                {log_id: timestamp}
            )
            await redis.expire(workflow_info_key, ttl)

        # 5. Add to component index (shard 0)
        component_index_key = f"{{shard:0}}:log:component:{component}:info"
        await redis.zadd(
            component_index_key,
            {log_id: timestamp}
        )
        await redis.expire(component_index_key, ttl)

        return log_id

    @staticmethod
    async def log_debug(
        redis,
        message: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        component: str = "system",
        operation: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
        sample_rate: float = 1.0
    ) -> Optional[str]:
        """
        Log a DEBUG level event with optional sampling.

        Args:
            redis: Redis connection
            message: Log message
            workflow_id: Optional workflow ID
            task_id: Optional task ID
            component: Component that logged the event
            operation: Operation name
            metadata: Additional metadata
            ttl: Time to live (defaults to 1 day for DEBUG)
            sample_rate: Sampling rate (0.0 - 1.0). 0.1 = 10% of logs

        Returns:
            Log ID if logged, None if sampled out
        """
        # Check sampling
        if not StatelessLogService._should_sample(sample_rate):
            return None

        # Generate log ID with timestamp
        timestamp = int(datetime.utcnow().timestamp() * 1000)
        log_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"

        # Determine shard
        if workflow_id:
            shard = StatelessLogService._get_shard(workflow_id)
        else:
            shard = 0

        # Use default TTL if not specified
        if ttl is None:
            ttl = StatelessLogService.DEFAULT_TTL["DEBUG"]

        # Build log entry
        log_entry = {
            "log_id": log_id,
            "timestamp": timestamp,
            "level": "DEBUG",
            "message": message,
            "component": component,
            "workflow_id": workflow_id or "",
            "task_id": task_id or "",
            "operation": operation or "",
            "metadata": metadata or {},
            "sample_rate": sample_rate
        }

        # 1. Store full log entry on workflow shard
        log_key = f"{{shard:{shard}}}:log:debug:{log_id}"
        await redis.set(
            log_key,
            json.dumps(log_entry),
            ex=ttl
        )

        # 2. Add to global debug index (shard 0)
        global_index_key = f"{{shard:0}}:log:global:debug"
        await redis.zadd(
            global_index_key,
            {log_id: timestamp}
        )
        await redis.expire(global_index_key, ttl)

        # 3. Store metadata for fetching (shard 0)
        meta_key = f"{{shard:0}}:log:meta:{log_id}"
        await redis.hset(
            meta_key,
            mapping={
                "shard": str(shard),
                "workflow_id": workflow_id or "",
                "component": component,
                "level": "DEBUG",
                "timestamp": str(timestamp)
            }
        )
        await redis.expire(meta_key, ttl)

        # 4. If workflow_id exists, add to workflow debug index
        if workflow_id:
            workflow_debug_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:debug"
            await redis.zadd(
                workflow_debug_key,
                {log_id: timestamp}
            )
            await redis.expire(workflow_debug_key, ttl)

        # 5. Add to component index (shard 0)
        component_index_key = f"{{shard:0}}:log:component:{component}:debug"
        await redis.zadd(
            component_index_key,
            {log_id: timestamp}
        )
        await redis.expire(component_index_key, ttl)

        return log_id

    @staticmethod
    async def log_warning(
        redis,
        message: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        component: str = "system",
        warning_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None
    ) -> str:
        """
        Log a WARNING level event to Redis with global index.

        Args:
            redis: Redis connection
            message: Warning message
            workflow_id: Optional workflow ID
            task_id: Optional task ID
            component: Component that logged the warning
            warning_type: Type of warning (e.g., "slow_execution")
            metadata: Additional metadata
            ttl: Time to live (defaults to 14 days for WARNING)

        Returns:
            Log ID
        """
        # Generate log ID with timestamp
        timestamp = int(datetime.utcnow().timestamp() * 1000)
        log_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"

        # Determine shard
        if workflow_id:
            shard = StatelessLogService._get_shard(workflow_id)
        else:
            shard = 0

        # Use default TTL if not specified
        if ttl is None:
            ttl = StatelessLogService.DEFAULT_TTL["WARNING"]

        # Build log entry
        log_entry = {
            "log_id": log_id,
            "timestamp": timestamp,
            "level": "WARNING",
            "message": message,
            "component": component,
            "workflow_id": workflow_id or "",
            "task_id": task_id or "",
            "warning_type": warning_type or "unknown",
            "metadata": metadata or {}
        }

        # 1. Store full log entry on workflow shard
        log_key = f"{{shard:{shard}}}:log:warning:{log_id}"
        await redis.set(
            log_key,
            json.dumps(log_entry),
            ex=ttl
        )

        # 2. Add to global warning index (shard 0)
        global_index_key = f"{{shard:0}}:log:global:warning"
        await redis.zadd(
            global_index_key,
            {log_id: timestamp}
        )
        await redis.expire(global_index_key, ttl)

        # 3. Store metadata for fetching (shard 0)
        meta_key = f"{{shard:0}}:log:meta:{log_id}"
        await redis.hset(
            meta_key,
            mapping={
                "shard": str(shard),
                "workflow_id": workflow_id or "",
                "component": component,
                "level": "WARNING",
                "timestamp": str(timestamp)
            }
        )
        await redis.expire(meta_key, ttl)

        # 4. If workflow_id exists, add to workflow warning index
        if workflow_id:
            workflow_warning_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:warning"
            await redis.zadd(
                workflow_warning_key,
                {log_id: timestamp}
            )
            await redis.expire(workflow_warning_key, ttl)

        # 5. Add to component index (shard 0)
        component_index_key = f"{{shard:0}}:log:component:{component}:warning"
        await redis.zadd(
            component_index_key,
            {log_id: timestamp}
        )
        await redis.expire(component_index_key, ttl)

        # 6. Publish to WebSocket pub/sub channel for real-time broadcasting
        try:
            await redis.publish(
                'gleitzeit:events',
                json.dumps({
                    'type': 'log_event',
                    'level': 'WARNING',
                    'message': message,
                    'workflow_id': workflow_id,
                    'task_id': task_id,
                    'component': component,
                    'warning_type': warning_type,
                    'log_id': log_id,
                    'timestamp': datetime.utcnow().isoformat(),
                    'metadata': metadata or {}
                })
            )
        except Exception as e:
            # Don't fail if pub/sub fails - logging is more important
            import logging
            logging.getLogger(__name__).error(f"Failed to publish log to WebSocket: {e}")

        return log_id

    @staticmethod
    async def query_logs(
        redis,
        level: str = "INFO",
        workflow_id: Optional[str] = None,
        component: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Query logs by level with optional filters.

        Args:
            redis: Redis connection
            level: Log level (INFO, DEBUG, WARNING, ERROR)
            workflow_id: Optional workflow ID to filter by
            component: Optional component to filter by
            limit: Maximum number of results
            offset: Offset for pagination
            start_time: Start timestamp (milliseconds)
            end_time: End timestamp (milliseconds)

        Returns:
            List of log entries
        """
        level = level.upper()
        level_lower = level.lower()

        # Determine which index to query
        if workflow_id:
            # Query workflow-specific logs
            shard = StatelessLogService._get_shard(workflow_id)
            if level == "ERROR":
                index_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:errors"
            else:
                index_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:{level_lower}"
        elif component:
            # Query component-specific logs
            index_key = f"{{shard:0}}:log:component:{component}:{level_lower}"
        else:
            # Query global index
            index_key = f"{{shard:0}}:log:global:{level_lower}"

        # Time range
        min_score = start_time if start_time else "-inf"
        max_score = end_time if end_time else "+inf"

        # Get log IDs from index (newest first)
        log_ids = await redis.zrevrangebyscore(
            index_key,
            max_score,
            min_score,
            start=offset,
            num=limit
        )

        # Fetch logs
        logs = []
        for log_id in log_ids:
            log_id_str = log_id.decode() if isinstance(log_id, bytes) else log_id

            if workflow_id:
                # We know the shard from workflow_id
                log_key = f"{{shard:{shard}}}:log:{level_lower}:{log_id_str}"
                log_data = await redis.get(log_key)
            else:
                # Fetch metadata to find which shard
                meta_key = f"{{shard:0}}:log:meta:{log_id_str}"
                meta = await redis.hgetall(meta_key)

                if not meta:
                    continue

                # Get log from correct shard
                log_shard = int(meta[b'shard'].decode())
                log_key = f"{{shard:{log_shard}}}:log:{level_lower}:{log_id_str}"
                log_data = await redis.get(log_key)

            if log_data:
                logs.append(json.loads(log_data))

        return logs

    @staticmethod
    async def get_log_count(
        redis,
        level: str = "INFO",
        workflow_id: Optional[str] = None,
        component: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> int:
        """
        Get count of logs by level.

        Args:
            redis: Redis connection
            level: Log level (INFO, DEBUG, WARNING, ERROR)
            workflow_id: Optional workflow ID
            component: Optional component
            start_time: Start timestamp (milliseconds)
            end_time: End timestamp (milliseconds)

        Returns:
            Count of logs
        """
        level = level.upper()
        level_lower = level.lower()

        if workflow_id:
            shard = StatelessLogService._get_shard(workflow_id)
            if level == "ERROR":
                index_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:errors"
            else:
                index_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:{level_lower}"
        elif component:
            index_key = f"{{shard:0}}:log:component:{component}:{level_lower}"
        else:
            index_key = f"{{shard:0}}:log:global:{level_lower}"

        min_score = start_time if start_time else "-inf"
        max_score = end_time if end_time else "+inf"

        return await redis.zcount(index_key, min_score, max_score)
