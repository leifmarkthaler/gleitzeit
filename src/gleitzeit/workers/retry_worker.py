"""
Retry worker for Gleitzeit.

Handles retry decisions and scheduling in a centralized, stateless manner.
All retry logic is consolidated here instead of being spread across workers.
"""

import asyncio
import json
import time
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from .base import BaseWorker
from ..core.models import TaskStatus
from ..core.event_store import EventType, EventLevel
from ..core.stateless_retry_service import (
    StatelessRetryService,
    RetryContext,
    RetryDecision
)
from ..core.sharding import default_sharding

logger = logging.getLogger(__name__)


class RetryWorker(BaseWorker):
    """
    Specialized worker for handling retry logic.

    This worker:
    - Processes task failures
    - Makes retry decisions using stateless service
    - Schedules retries via timer mechanism
    - Records retry metrics
    - Manages retry budgets
    """

    def __init__(self, config):
        """
        Initialize retry worker.

        Args:
            config: WorkerConfig instance
        """
        super().__init__(config)

        # Initialize stateless retry service
        retry_config = {}  # Will get from config if needed
        self.retry_service = None  # Will be initialized in initialize()

        # Worker-specific configuration
        self.batch_size = config.batch_size or 10
        self.process_timeout = 30  # Default timeout

        logger.info(
            f"RetryWorker {config.worker_id} initialized with "
            f"batch_size={self.batch_size}"
        )

    async def initialize(self):
        """Initialize worker resources."""
        await super().initialize()

        # Initialize retry service with Redis connection
        self.retry_service = StatelessRetryService(
            redis_client=self.redis,
            config={}  # Use default retry config
        )

        logger.info(f"RetryWorker {self.config.worker_id} initialized retry service")

    async def on_initialize(self):
        """Custom initialization for RetryWorker."""
        # Initialize event store if needed
        from ..core.event_store import EventStore
        self.event_store = EventStore(self.redis, {})  # Use default config
        logger.info(f"RetryWorker {self.config.worker_id} event store initialized")

    def get_base_streams(self) -> List[str]:
        """
        Get base stream patterns this worker processes.

        Returns:
            List of stream patterns (will be sharded)
        """
        return [
            "task:failed",        # Primary stream for failed tasks
            "retry:check",        # Explicit retry check requests
            "retry:configure"     # Configuration updates
        ]

    async def process_message(
        self,
        stream: str,
        msg_id: str,
        data: Dict
    ) -> bool:
        """
        Process a retry-related message.

        Args:
            stream: Stream the message came from
            msg_id: Message ID
            data: Message data

        Returns:
            True to ACK message, False to retry later
        """
        try:
            if "task:failed" in stream:
                return await self._handle_task_failure(data)

            elif "retry:check" in stream:
                return await self._handle_retry_check(data)

            elif "retry:configure" in stream:
                return await self._handle_configuration(data)

            else:
                logger.warning(f"Unknown stream type: {stream}")
                return True  # ACK unknown messages

        except Exception as e:
            logger.error(f"Error processing retry message: {e}", exc_info=True)
            # Log to Redis for queryability
            await self.log_worker_error(
                "process_message",
                e,
                stream=stream,
                message_id=msg_id
            )
            return False  # Don't ACK, retry later

    async def _handle_task_failure(self, data: Dict[str, str]) -> bool:
        """
        Handle a task failure and determine if retry is needed.

        Args:
            data: Failure data including task_id, workflow_id, error

        Returns:
            True if handled successfully
        """
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')
        error_msg = data.get('error', 'Unknown error')
        error_type = data.get('error_type', 'Exception')

        if not task_id or not workflow_id:
            logger.error("Missing task_id or workflow_id in failure message")
            # Log validation error to Redis
            await self.log_worker_error(
                "_handle_task_failure",
                ValueError("Missing task_id or workflow_id in failure message"),
                data=str(data)
            )
            return True  # ACK invalid message

        try:
            # Get task data from Redis
            task_key = default_sharding.get_task_key(task_id, workflow_id).encode()
            task_data = await self.redis.hgetall(task_key)

            # Get current retry count
            current_attempt = int(task_data.get(b"retry_count", b"0"))

            # Extract service/handler info
            method = task_data.get(b"method", b"").decode()
            service_name = method.split('/')[0] if '/' in method else None

            # Create retry context
            context = RetryContext(
                task_id=task_id,
                workflow_id=workflow_id,
                error_type=error_type,
                error_msg=error_msg,
                current_attempt=current_attempt,
                service_name=service_name,
                handler_type=service_name
            )

            # Make retry decision
            decision, metadata = await self.retry_service.should_retry(context)

            logger.info(
                f"Retry decision for {task_id}: {decision.value} "
                f"(attempt {current_attempt})"
            )

            if decision == RetryDecision.RETRY:
                # Schedule retry
                await self._schedule_retry(
                    task_id,
                    workflow_id,
                    metadata['delay'],
                    current_attempt + 1,
                    error_msg
                )

            else:
                # Mark as permanently failed
                await self._mark_permanently_failed(
                    task_id,
                    workflow_id,
                    error_msg,
                    decision,
                    metadata
                )

            return True

        except Exception as e:
            logger.error(f"Error handling task failure: {e}", exc_info=True)
            # Log to Redis for queryability
            await self.log_worker_error(
                "_handle_task_failure",
                e,
                workflow_id=workflow_id if 'workflow_id' in locals() else None,
                task_id=task_id if 'task_id' in locals() else None,
                error_msg=error_msg if 'error_msg' in locals() else None
            )
            return False

    async def _schedule_retry(
        self,
        task_id: str,
        workflow_id: str,
        delay: float,
        next_attempt: int,
        error_msg: str
    ) -> None:
        """Schedule a task retry via timer mechanism."""
        task_key = default_sharding.get_task_key(task_id, workflow_id).encode()

        # Update task status
        await self.redis.hset(
            task_key,
            mapping={
                b"status": TaskStatus.SCHEDULED.encode(),
                b"retry_count": str(next_attempt).encode(),
                b"last_error": error_msg.encode(),
                b"retry_at": str(time.time() + delay).encode(),
                b"last_attempt_at": datetime.utcnow().isoformat().encode()
            }
        )

        # Schedule via timer
        timer_key = default_sharding.get_global_key("timers:pending").encode()
        await self.redis.zadd(
            timer_key,
            {f"{workflow_id}:{task_id}:retry".encode(): time.time() + delay}
        )

        # Emit retry scheduled event
        if hasattr(self, 'event_store'):
            await self.event_store.store_event(
                event_type=EventType.TASK_RETRY_SCHEDULED,
                workflow_id=workflow_id,
                task_id=task_id,
                level=EventLevel.IMPORTANT,
                data={
                    'attempt': next_attempt,
                    'delay': delay,
                    'retry_at': time.time() + delay,
                    'error': error_msg
                }
            )

        logger.info(
            f"Scheduled retry for {task_id} in {delay:.2f}s "
            f"(attempt {next_attempt})"
        )

    async def _mark_permanently_failed(
        self,
        task_id: str,
        workflow_id: str,
        error_msg: str,
        decision: RetryDecision,
        metadata: Dict[str, Any]
    ) -> None:
        """Mark task as permanently failed."""
        task_key = default_sharding.get_task_key(task_id, workflow_id).encode()

        # Update task status
        await self.redis.hset(
            task_key,
            mapping={
                b"status": TaskStatus.FAILED.encode(),
                b"error": error_msg.encode(),
                b"retry_decision": decision.value.encode(),
                b"retry_metadata": json.dumps(metadata).encode(),
                b"failed_at": datetime.utcnow().isoformat().encode()
            }
        )

        # Add to failed tasks set for dependency resolution
        await self.redis.sadd(
            default_sharding.get_workflow_key("tasks:failed", workflow_id).encode(),
            task_id.encode()
        )

        # Emit to task:completed stream with failed status for DependencyWorker
        # This triggers dependency resolution to block dependent tasks
        completed_stream = default_sharding.get_stream_key("task:completed", workflow_id).encode()
        await self.redis.xadd(
            completed_stream,
            {
                b"workflow_id": workflow_id.encode(),
                b"task_id": task_id.encode(),
                b"status": b"failed",
                b"error": error_msg.encode(),
                b"timestamp": datetime.utcnow().isoformat().encode()
            }
        )

        # Record failure in metrics
        await self.retry_service.record_retry_failure(workflow_id, task_id)

        # Emit permanent failure event
        if hasattr(self, 'event_store'):
            await self.event_store.store_event(
                event_type=EventType.TASK_FAILED,
                workflow_id=workflow_id,
                task_id=task_id,
                level=EventLevel.CRITICAL,
                data={
                    'error': error_msg,
                    'retry_decision': decision.value,
                    'metadata': metadata
                }
            )

        logger.warning(
            f"Task {task_id} permanently failed: {decision.value} "
            f"({metadata})"
        )

    async def _handle_retry_check(self, data: Dict[str, str]) -> bool:
        """
        Handle explicit retry check request.

        Used for manual retry triggers or external systems.

        Args:
            data: Check request data

        Returns:
            True if handled successfully
        """
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')

        if not task_id or not workflow_id:
            return True  # ACK invalid message

        # Get current task status
        task_key = default_sharding.get_task_key(task_id, workflow_id).encode()
        task_data = await self.redis.hgetall(task_key)

        status = task_data.get(b"status", b"").decode()
        if status == TaskStatus.FAILED:
            # Check if manual retry is allowed
            last_error = task_data.get(b"last_error", b"Unknown").decode()

            # Create minimal context for check
            context = RetryContext(
                task_id=task_id,
                workflow_id=workflow_id,
                error_type="ManualRetry",
                error_msg=last_error,
                current_attempt=0  # Reset for manual retry
            )

            decision, metadata = await self.retry_service.should_retry(context)

            if decision == RetryDecision.RETRY:
                await self._schedule_retry(
                    task_id,
                    workflow_id,
                    metadata['delay'],
                    1,
                    "Manual retry requested"
                )
                logger.info(f"Manual retry scheduled for {task_id}")
            else:
                logger.warning(
                    f"Manual retry denied for {task_id}: {decision.value}"
                )

        return True

    async def _handle_configuration(self, data: Dict[str, str]) -> bool:
        """
        Handle retry configuration updates.

        Args:
            data: Configuration data

        Returns:
            True if handled successfully
        """
        config_type = data.get('type', 'global')
        config_data = json.loads(data.get('config', '{}'))

        if config_type == 'global':
            await self.retry_service.set_retry_config(config_data)
            logger.info(f"Updated global retry configuration: {config_data}")

        elif config_type == 'workflow':
            workflow_id = data.get('workflow_id')
            if workflow_id:
                await self.retry_service.set_retry_config(
                    config_data,
                    workflow_id=workflow_id
                )
                logger.info(
                    f"Updated retry configuration for workflow {workflow_id}"
                )

        elif config_type == 'task':
            workflow_id = data.get('workflow_id')
            task_id = data.get('task_id')
            if workflow_id and task_id:
                await self.retry_service.set_retry_config(
                    config_data,
                    workflow_id=workflow_id,
                    task_id=task_id
                )
                logger.info(
                    f"Updated retry configuration for task {task_id}"
                )

        elif config_type == 'reset_budget':
            # Emergency budget reset
            workflow_id = data.get('workflow_id')
            service_name = data.get('service_name')
            await self.retry_service.reset_budget(
                workflow_id=workflow_id,
                service_name=service_name
            )
            logger.warning(
                f"Emergency budget reset for {workflow_id or service_name or 'global'}"
            )

        return True

    async def get_retry_metrics(self, workflow_id: str) -> Dict[str, Any]:
        """
        Get retry metrics for a workflow.

        Args:
            workflow_id: Workflow identifier

        Returns:
            Retry metrics dictionary
        """
        return await self.retry_service.get_retry_metrics(workflow_id)

    async def stop(self):
        """Clean up worker resources."""
        logger.info(f"Stopping RetryWorker {self.config.worker_id}")
        await super().stop()