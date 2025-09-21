"""
Timer Provider for Gleitzeit

Provides timer/scheduler functionality following the protocol/provider pattern.
This provider handles timer tasks by registering them in Redis and returning
immediately with a SLEEPING status, allowing for non-blocking timer operations.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from gleitzeit.providers.simple import SimpleProvider
from gleitzeit.core.models import TaskStatus, TaskResult
from gleitzeit.core.errors import ProviderError

logger = logging.getLogger(__name__)


class TimerProvider(SimpleProvider):
    """
    Simple timer provider that handles timer/v1 protocol.
    
    This provider handles timer tasks in a non-blocking way by:
    1. Registering timers in Redis
    2. Returning immediately with SLEEPING status
    3. Relying on TimerMonitorService to wake tasks
    """
    
    def __init__(
        self,
        provider_id: str = "timer",
        persistence=None,
        **kwargs
    ):
        """Initialize the timer provider."""
        # Don't pass protocol_id in kwargs if it's already specified
        kwargs_filtered = {k: v for k, v in kwargs.items() if k != 'protocol_id'}
        super().__init__(
            provider_id=provider_id,
            protocol_id="timer/v1",
            name="Timer Provider",
            description="Handles timer and scheduling operations",
            **kwargs_filtered
        )
        self.persistence = persistence
        self.timer_handler = None
        
        # Initialize LoggingMixin to set _component_name
        from gleitzeit.core.logging_mixin import LoggingMixin
        LoggingMixin.__init__(self)
        
        # Register supported methods with protocol prefix
        self.supported_methods = [
            "timer/sleep",
            "timer/wait_until",  
            "timer/wait_or_signal"
        ]
        
    def get_supported_methods(self) -> list:
        """Return list of supported methods."""
        return self.supported_methods
        
    async def initialize(self):
        """Initialize the provider."""
        await super().initialize()
        logger.info(f"Initializing TimerProvider {self.provider_id}")
        
        # Check for Redis support - timers REQUIRE Redis
        if not self.persistence:
            raise RuntimeError("TimerProvider requires persistence to be configured")
        
        # Check if persistence has Redis support (UnifiedRedisAdapter has 'redis' attribute)
        if not hasattr(self.persistence, 'redis'):
            raise RuntimeError("TimerProvider requires Redis-backed persistence (got non-Redis persistence)")
        
        # Timer functionality will be handled by storing in Redis
        # No need for TimerTaskHandler which doesn't exist
        self.redis = self.persistence.redis
        logger.info("TimerProvider initialized with Redis persistence")
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Execute a timer method.

        This is the main method required by SimpleProvider.

        Args:
            method: Timer method (e.g., "sleep", "wait", "timer/wait")
            params: Method parameters

        Returns:
            TaskResult or dict with timer information
        """
        # Get workflow and task context from parameters
        workflow_id = params.pop("_workflow_id", None) or params.pop("workflow_id", None)
        task_id = params.pop("_task_id", None) or params.pop("task_id", None)
        
        if not workflow_id or not task_id:
            # If called without context, try to extract from task if present
            if "_task" in params:
                task = params["_task"]
                workflow_id = getattr(task, 'workflow_id', None)
                task_id = getattr(task, 'id', None)
        
        if not workflow_id or not task_id:
            return TaskResult(
                task_id=task_id or "unknown",
                status=TaskStatus.FAILED,
                error="Timer tasks require workflow and task context",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )
        
        # Normalize method name (remove protocol prefix if present)
        if "/" in method:
            method = method.split("/")[-1]
        
        try:
            # Route to appropriate handler method
            if method in ["sleep", "wait"]:
                result = await self._handle_wait(
                    workflow_id=workflow_id,
                    task_id=task_id,
                    params=params
                )
            elif method == "wait_until":
                result = await self._handle_wait_until(
                    workflow_id=workflow_id,
                    task_id=task_id,
                    params=params
                )
            else:
                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=f"Unsupported timer method: {method}",
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow()
                )
            
            # Convert result to TaskResult if needed
            if isinstance(result, dict):
                if result.get("status") == "waiting":
                    # Task is scheduled (waiting for timer)
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.SCHEDULED,
                        result=result,
                        started_at=datetime.utcnow(),
                        metadata={
                            "timer_id": result.get("timer_id"),
                            "wake_at": result.get("wake_at")
                        }
                    )
                elif result.get("status") == TaskStatus.COMPLETED.value:
                    # Timer completed immediately
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.COMPLETED,
                        result=result.get("result"),
                        started_at=datetime.utcnow(),
                        completed_at=datetime.utcnow()
                    )
                else:
                    # Failed or unknown status
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.FAILED,
                        error=result.get("error", "Timer task failed"),
                        started_at=datetime.utcnow(),
                        completed_at=datetime.utcnow()
                    )
            
            return result
            
        except Exception as e:
            logger.error(f"Timer task {task_id} failed: {e}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )

    async def _handle_wait(self, workflow_id: str, task_id: str, params: Dict[str, Any]) -> Dict:
        """
        Handle wait/sleep timer request.
        Stores timer in Redis sorted set for processing by TimerWorker.
        """
        import time

        # Get duration from params (default 60 seconds)
        duration = params.get("duration", 60)

        # Calculate expiry time
        expire_at = time.time() + duration

        # Store timer in Redis sorted set
        timer_key = f"timer:task:{task_id}"
        await self.redis.zadd("timers:pending", {timer_key: expire_at})

        # Store timer metadata
        await self.redis.hset(
            f"timer:metadata:{task_id}",
            mapping={
                "workflow_id": workflow_id,
                "task_id": task_id,
                "duration": str(duration),
                "created_at": str(time.time()),
                "expire_at": str(expire_at)
            }
        )

        # Emit timer created event
        await self.redis.xadd(
            "gleitzeit:events:stream:timer:created",
            {
                "event_type": "timer:created",
                "task_id": task_id,
                "workflow_id": workflow_id,
                "duration": str(duration),
                "expire_at": str(expire_at)
            }
        )

        logger.info(f"Timer created for task {task_id}, expires in {duration}s")

        # Return waiting status - task will be resumed when timer expires
        return {
            "status": "waiting",
            "timer_id": timer_key,
            "duration": duration,
            "expire_at": expire_at,
            "resume_after": duration
        }

    async def _handle_wait_until(self, workflow_id: str, task_id: str, params: Dict[str, Any]) -> Dict:
        """
        Handle wait_until timer request.
        Waits until a specific timestamp.
        """
        import time
        from datetime import datetime

        # Get target time from params
        target_time = params.get("timestamp")
        if not target_time:
            raise ValueError("wait_until requires 'timestamp' parameter")

        # Convert to timestamp if it's a datetime string
        if isinstance(target_time, str):
            target_timestamp = datetime.fromisoformat(target_time).timestamp()
        elif isinstance(target_time, datetime):
            target_timestamp = target_time.timestamp()
        else:
            target_timestamp = float(target_time)

        current_time = time.time()

        # If target time is in the past, complete immediately
        if target_timestamp <= current_time:
            return {
                "status": TaskStatus.COMPLETED.value,
                "result": "Timer already expired"
            }

        # Store timer in Redis sorted set
        timer_key = f"timer:task:{task_id}"
        await self.redis.zadd("timers:pending", {timer_key: target_timestamp})

        # Store timer metadata
        duration = target_timestamp - current_time
        await self.redis.hset(
            f"timer:metadata:{task_id}",
            mapping={
                "workflow_id": workflow_id,
                "task_id": task_id,
                "type": "wait_until",
                "target_timestamp": str(target_timestamp),
                "duration": str(duration),
                "created_at": str(current_time)
            }
        )

        logger.info(f"Timer created for task {task_id}, expires at {target_timestamp}")

        return {
            "status": "waiting",
            "timer_id": timer_key,
            "target_timestamp": target_timestamp,
            "duration": duration,
            "resume_at": target_timestamp
        }