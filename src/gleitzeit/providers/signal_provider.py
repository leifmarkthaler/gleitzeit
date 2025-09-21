"""
Signal Provider for Gleitzeit

Provides signal functionality following the protocol/provider pattern.
This provider handles signal tasks by registering them in Redis and returning
immediately with a SLEEPING status, allowing for non-blocking signal operations.
"""

import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime
import json

from gleitzeit.providers.simple import SimpleProvider
from gleitzeit.core.models import TaskStatus, TaskResult
from gleitzeit.core.errors import ProviderError

logger = logging.getLogger(__name__)


class SignalProvider(SimpleProvider):
    """
    Signal provider that handles signal/v1 protocol.
    
    This provider handles signal tasks in a non-blocking way by:
    1. Registering signal waiters in Redis
    2. Returning immediately with SLEEPING status
    3. Relying on SignalWorker to wake tasks when signals arrive
    """
    
    def __init__(
        self,
        provider_id: str = "signal",
        persistence=None,
        **kwargs
    ):
        """Initialize the signal provider."""
        # Don't pass protocol_id in kwargs if it's already specified
        kwargs_filtered = {k: v for k, v in kwargs.items() if k != 'protocol_id'}
        super().__init__(
            provider_id=provider_id,
            protocol_id="signal/v1",
            name="Signal Provider",
            description="Handles workflow signals and external events",
            **kwargs_filtered
        )
        self.persistence = persistence
        # No signal_handler needed - SignalWorker handles signal processing
        
        # Initialize LoggingMixin to set _component_name
        from gleitzeit.core.logging_mixin import LoggingMixin
        LoggingMixin.__init__(self)
        
        # Register supported methods with protocol prefix
        # Note: "send" and "broadcast" removed - signals are sent via API endpoints only
        self.supported_methods = [
            "signal/wait",
            "signal/wait_any",
            "signal/wait_all"
        ]
        
    def get_supported_methods(self) -> list:
        """Return list of supported methods."""
        return self.supported_methods
        
    async def initialize(self):
        """Initialize the provider."""
        await super().initialize()
        logger.info(f"Initializing SignalProvider {self.provider_id}")
        
        # Check for Redis support - signals REQUIRE Redis
        if not self.persistence:
            raise RuntimeError("SignalProvider requires persistence to be configured")
        
        # Check if persistence has Redis support (UnifiedRedisAdapter has 'redis' attribute)
        if not hasattr(self.persistence, 'redis'):
            raise RuntimeError("SignalProvider requires Redis-backed persistence (got non-Redis persistence)")
        
        # Signal operations handled by SignalWorker
        # Provider just registers waiters, SignalWorker processes signals
        logger.info("SignalProvider initialized - SignalWorker will handle signal processing")
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Execute a signal method.

        This is the main method required by SimpleProvider.

        Args:
            method: Signal method (e.g., "wait", "signal/wait")
            params: Method parameters

        Returns:
            TaskResult or dict with signal information
        """
        # Ensure initialization has been called
        logger.info(f"SignalProvider.execute: method={method}, params keys={list(params.keys())}")

        # Ensure Redis is available
        if not hasattr(self.persistence, 'redis'):
            return TaskResult(
                task_id=params.get("_task_id", "unknown"),
                status=TaskStatus.FAILED,
                error="Signal functionality requires Redis persistence",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )
        
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
                error="Signal tasks require workflow and task context",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )
        
        # Normalize method name (remove protocol prefix if present)
        if "/" in method:
            method = method.split("/")[-1]
        
        try:
            # Route to appropriate handler method
            if method == "wait":
                # Wait for a signal within this workflow
                signal_name = params.get("signal_name") or params.get("signal_id")
                timeout = params.get("timeout", None)  # Optional timeout

                # Register task as waiting for signal IN THIS WORKFLOW
                await self.persistence.redis.sadd(
                    f"signal:waiters:{workflow_id}:{signal_name}",
                    task_id
                )

                # Store waiter metadata
                await self.persistence.redis.hset(
                    f"signal:metadata:{workflow_id}:{task_id}",
                    mapping={
                        "signal_name": signal_name,
                        "workflow_id": workflow_id,
                        "waiting_since": str(time.time()),
                        "timeout": str(timeout) if timeout else "none"
                    }
                )

                # Set timeout if specified
                if timeout:
                    timeout_at = time.time() + timeout
                    await self.persistence.redis.zadd(
                        "signal:timeouts",
                        {f"signal:task:{workflow_id}:{task_id}": timeout_at}
                    )

                logger.info(f"Task {task_id} waiting for signal {signal_name} in workflow {workflow_id}")

                # Return waiting status - SignalWorker will handle the rest
                result = {
                    "status": "waiting",
                    "signal_name": signal_name,
                    "workflow_id": workflow_id,
                    "timeout": timeout
                }

            elif method == "wait_any":
                # Wait for any of multiple signals
                signal_names = params.get("signal_names", [])
                timeout = params.get("timeout", None)

                # Register task for all signals
                for signal_name in signal_names:
                    await self.persistence.redis.sadd(
                        f"signal:waiters:{workflow_id}:{signal_name}",
                        task_id
                    )

                # Store metadata
                await self.persistence.redis.hset(
                    f"signal:metadata:{workflow_id}:{task_id}",
                    mapping={
                        "signal_names": json.dumps(signal_names),
                        "mode": "any",
                        "workflow_id": workflow_id,
                        "waiting_since": str(time.time()),
                        "timeout": str(timeout) if timeout else "none"
                    }
                )

                # Set timeout if specified
                if timeout:
                    timeout_at = time.time() + timeout
                    await self.persistence.redis.zadd(
                        "signal:timeouts",
                        {f"signal:task:{workflow_id}:{task_id}": timeout_at}
                    )

                result = {
                    "status": "waiting",
                    "signal_names": signal_names,
                    "mode": "any",
                    "workflow_id": workflow_id,
                    "timeout": timeout
                }

            elif method == "wait_all":
                # Wait for all of multiple signals
                signal_names = params.get("signal_names", [])
                timeout = params.get("timeout", None)

                # Track which signals are pending
                await self.persistence.redis.hset(
                    f"signal:pending:{workflow_id}:{task_id}",
                    mapping={
                        "required": json.dumps(signal_names),
                        "received": json.dumps([]),
                        "pending": json.dumps(signal_names)
                    }
                )

                # Register for all signals
                for signal_name in signal_names:
                    await self.persistence.redis.sadd(
                        f"signal:waiters:{workflow_id}:{signal_name}",
                        task_id
                    )

                # Store metadata
                await self.persistence.redis.hset(
                    f"signal:metadata:{workflow_id}:{task_id}",
                    mapping={
                        "signal_names": json.dumps(signal_names),
                        "mode": "all",
                        "workflow_id": workflow_id,
                        "waiting_since": str(time.time()),
                        "timeout": str(timeout) if timeout else "none"
                    }
                )

                # Set timeout if specified
                if timeout:
                    timeout_at = time.time() + timeout
                    await self.persistence.redis.zadd(
                        "signal:timeouts",
                        {f"signal:task:{workflow_id}:{task_id}": timeout_at}
                    )

                result = {
                    "status": "waiting",
                    "signal_names": signal_names,
                    "mode": "all",
                    "workflow_id": workflow_id,
                    "timeout": timeout
                }

            elif method in ["send", "broadcast"]:
                # Signals should be sent via API endpoints, not through provider
                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error="Signals must be sent via API endpoints (/workflows/{id}/send)",
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow()
                )
            else:
                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=f"Unsupported signal method: {method}",
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow()
                )
            
            # Convert result to TaskResult if needed
            if isinstance(result, dict):
                if result.get("status") == "waiting":
                    # Task is waiting for signal
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.WAITING,
                        result=result,
                        started_at=datetime.utcnow(),
                        metadata={
                            "signal_id": result.get("signal_id"),
                            "signals": result.get("signals"),
                            "timeout": result.get("timeout")
                        }
                    )
                elif result.get("status") == TaskStatus.COMPLETED.value:
                    # Signal operation completed immediately
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.COMPLETED,
                        result=result.get("result"),
                        started_at=datetime.utcnow(),
                        completed_at=datetime.utcnow()
                    )
                elif result.get("status") == "timeout":
                    # Signal timed out
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.FAILED,
                        error="Signal wait timed out",
                        result={"timeout": True},
                        started_at=datetime.utcnow(),
                        completed_at=datetime.utcnow()
                    )
                else:
                    # Failed or unknown status
                    return TaskResult(
                        task_id=task_id,
                        status=TaskStatus.FAILED,
                        error=result.get("error", "Signal task failed"),
                        started_at=datetime.utcnow(),
                        completed_at=datetime.utcnow()
                    )
            
            return result
            
        except Exception as e:
            logger.error(f"Signal task {task_id} failed: {e}")
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )