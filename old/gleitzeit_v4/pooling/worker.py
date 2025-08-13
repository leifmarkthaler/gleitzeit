"""
Refactored Provider Worker using centralized event system
"""

import asyncio
import logging
import uuid
from typing import Dict, Any, Optional, Callable
from enum import Enum
from datetime import datetime, timedelta
import psutil
import os

from ..core.events import EventType, GleitzeitEvent
from ..core.errors import TaskError, TaskTimeoutError, ErrorCode, SystemError

logger = logging.getLogger(__name__)


class WorkerState(str, Enum):
    """States of a provider worker"""
    STARTING = "starting"
    IDLE = "idle"
    CLAIMING = "claiming"
    BUSY = "busy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class ProviderWorker:
    """
    Individual worker using centralized event system
    
    This replaces ProviderWorker to properly integrate with
    the centralized GleitzeitEvent system.
    """
    
    def __init__(
        self,
        worker_id: str,
        protocol_id: str,
        provider_instance: Any,
        event_emitter: Optional[Callable] = None,
        max_concurrent_tasks: int = 1,
        heartbeat_interval: int = 5,
        task_timeout: int = 300
    ):
        self.worker_id = worker_id
        self.protocol_id = protocol_id
        self.provider = provider_instance
        self.event_emitter = event_emitter  # Function to emit centralized events
        self.max_concurrent_tasks = max_concurrent_tasks
        self.heartbeat_interval = heartbeat_interval
        self.task_timeout = task_timeout
        
        # State management
        self.state = WorkerState.STARTING
        self.current_tasks: Dict[str, Dict[str, Any]] = {}
        self.running = False
        
        # Statistics
        self.stats = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_execution_time": 0.0,
            "started_at": None,
            "last_task_at": None
        }
        
        # Tasks
        self._claim_lock = asyncio.Lock()
        self._last_activity = datetime.utcnow()  # Track activity for health assessment
        
        # Process info
        self._process = psutil.Process(os.getpid())
        
    async def start(self) -> None:
        """Start the worker"""
        if self.running:
            return
            
        self.running = True
        self.state = WorkerState.IDLE
        self.stats["started_at"] = datetime.utcnow()
        
        # Event-driven health reporting - no periodic heartbeats
        # Health status reported via task execution events and failures
        
        # Emit started event
        await self._emit_event(EventType.WORKER_STARTED, {
            "worker_id": self.worker_id,
            "protocol_id": self.protocol_id,
            "max_concurrent_tasks": self.max_concurrent_tasks
        })
        
        logger.info(f"ProviderWorker {self.worker_id} started for protocol {self.protocol_id}")
    
    async def stop(self) -> None:
        """Stop the worker gracefully"""
        if not self.running:
            return
            
        self.running = False
        self.state = WorkerState.STOPPING
        
        # No heartbeat task to stop - using event-driven health reporting
        
        # Wait for current tasks to complete (with timeout)
        if self.current_tasks:
            logger.info(f"Worker {self.worker_id} waiting for {len(self.current_tasks)} tasks to complete")
            try:
                await asyncio.wait_for(self._wait_for_tasks(), timeout=30)
            except asyncio.TimeoutError:
                logger.warning(f"Worker {self.worker_id} timed out waiting for tasks")
        
        self.state = WorkerState.STOPPED
        
        # Emit stopped event
        await self._emit_event(EventType.WORKER_STOPPED, {
            "worker_id": self.worker_id,
            "stats": self.get_stats()
        })
        
        logger.info(f"ProviderWorker {self.worker_id} stopped")
    
    async def _wait_for_tasks(self) -> None:
        """Wait for all current tasks to complete"""
        while self.current_tasks:
            await asyncio.sleep(0.1)
    
    async def handle_task_available(self, event: GleitzeitEvent) -> None:
        """Handle TASK_AVAILABLE event from centralized system"""
        task_data = event.data
        task_id = task_data.get("task_id", "unknown")
        
        print(f"🔥 Worker {self.worker_id} considering task {task_id}")
        print(f"   Worker state: {self.state}, current tasks: {len(self.current_tasks)}")
        
        if self.state != WorkerState.IDLE:
            print(f"   Skipping - worker not idle")
            return
            
        if len(self.current_tasks) >= self.max_concurrent_tasks:
            print(f"   Skipping - at max concurrent tasks")
            return
            
        # Check if we can handle this task
        if not self._can_handle_task(task_data):
            print(f"   Skipping - cannot handle this task")
            return
        
        print(f"   Attempting to claim and execute task {task_id}")
        # Try to claim the task
        await self._try_claim_and_execute(task_data)
    
    def _can_handle_task(self, task_data: Dict[str, Any]) -> bool:
        """Check if this worker can handle the task"""
        # Check protocol match
        if task_data.get("protocol") != self.protocol_id:
            return False
            
        # Check if provider supports the method
        if hasattr(self.provider, 'get_supported_methods'):
            supported = self.provider.get_supported_methods()
            if task_data.get("method") not in supported:
                return False
        
        return True
    
    async def _try_claim_and_execute(self, task_data: Dict[str, Any]) -> None:
        """Try to claim and execute a task"""
        task_id = task_data["task_id"]
        
        print(f"🎯 Worker {self.worker_id} trying to claim task {task_id}")
        
        async with self._claim_lock:
            # Double-check we can still take tasks
            if len(self.current_tasks) >= self.max_concurrent_tasks:
                print(f"   Cannot claim - at max concurrent tasks")
                return
                
            # Try to claim (would use Redis or coordination service in production)
            claimed = await self._claim_task(task_id)
            
            if not claimed:
                print(f"   Failed to claim task {task_id}")
                return
            
            print(f"   Successfully claimed task {task_id}")
            
            # Update state
            self.state = WorkerState.BUSY if len(self.current_tasks) == 0 else self.state
            self.current_tasks[task_id] = {
                "task_data": task_data,
                "started_at": datetime.utcnow()
            }
            
            # Emit claimed event
            await self._emit_event(EventType.TASK_CLAIMED, {
                "task_id": task_id,
                "worker_id": self.worker_id,
                "protocol": task_data.get("protocol"),
                "method": task_data.get("method")
            }, correlation_id=task_id)
            
            # Emit worker busy event
            await self._emit_event(EventType.WORKER_BUSY, {
                "worker_id": self.worker_id,
                "current_tasks": len(self.current_tasks)
            })
        
        print(f"   Starting execution of task {task_id}")
        # Execute task asynchronously
        asyncio.create_task(self._execute_task(task_id, task_data))
    
    async def _claim_task(self, task_id: str) -> bool:
        """
        Atomically claim a task
        
        In production, this would use Redis SET NX or similar
        for distributed coordination.
        """
        # Simplified in-memory claim for now
        # In real implementation, use Redis:
        # return await redis.set(f"task:{task_id}:claimed", self.worker_id, nx=True, ex=300)
        
        # For now, always succeed (first worker wins in practice due to async)
        return True
    
    async def _execute_task(self, task_id: str, task_data: Dict[str, Any]) -> None:
        """Execute a claimed task"""
        start_time = datetime.utcnow()
        
        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                self.provider.handle_request(
                    task_data.get("method"),
                    task_data.get("params", {})
                ),
                timeout=self.task_timeout
            )
            
            # Calculate execution time
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Update stats
            self.stats["tasks_completed"] += 1
            self.stats["total_execution_time"] += execution_time
            self.stats["last_task_at"] = datetime.utcnow()
            
            # Emit completion event
            await self._emit_event(EventType.TASK_COMPLETED, {
                "task_id": task_id,
                "worker_id": self.worker_id,
                "result": result,
                "execution_time": execution_time
            }, correlation_id=task_id)
            
            logger.debug(f"Worker {self.worker_id} completed task {task_id} in {execution_time:.2f}s")
            
            # Report health on successful task completion
            await self._report_health_on_activity()
            
        except asyncio.TimeoutError:
            self.stats["tasks_failed"] += 1
            
            await self._emit_event(EventType.TASK_TIMEOUT, {
                "task_id": task_id,
                "worker_id": self.worker_id,
                "timeout": self.task_timeout
            }, correlation_id=task_id)
            
            logger.error(f"Worker {self.worker_id} task {task_id} timed out")
            
        except Exception as e:
            self.stats["tasks_failed"] += 1
            
            await self._emit_event(EventType.TASK_FAILED, {
                "task_id": task_id,
                "worker_id": self.worker_id,
                "error": str(e),
                "error_type": type(e).__name__
            }, correlation_id=task_id)
            
            logger.error(f"Worker {self.worker_id} task {task_id} failed: {e}")
            
            # Report potential health issue on task failure
            await self._report_health_on_activity()
            
        finally:
            # Remove from current tasks
            self.current_tasks.pop(task_id, None)
            
            # Update state
            if len(self.current_tasks) == 0:
                self.state = WorkerState.IDLE
                await self._emit_event(EventType.WORKER_IDLE, {
                    "worker_id": self.worker_id
                })
    
    async def _report_health_on_activity(self) -> None:
        """Report health status when activity occurs - no periodic polling"""
        try:
            self._last_activity = datetime.utcnow()
            
            # Only report detailed health on significant events
            memory_info = self._process.memory_info()
            
            await self._emit_event(EventType.WORKER_HEALTH_REPORT, {
                "worker_id": self.worker_id,
                "state": self.state.value,
                "current_tasks": len(self.current_tasks),
                "max_tasks": self.max_concurrent_tasks,
                "memory_usage_mb": memory_info.rss / 1024 / 1024,
                "last_activity": self._last_activity.isoformat(),
                "stats": self.get_stats()
            })
        except Exception as e:
            logger.error(f"Worker {self.worker_id} health report error: {e}")
    
    def is_healthy(self) -> bool:
        """Check if worker is healthy based on activity"""
        if not self.running or self.state == WorkerState.FAILED:
            return False
        
        # Worker is healthy if it's been active recently or is processing tasks
        time_since_activity = datetime.utcnow() - self._last_activity
        return time_since_activity.total_seconds() < 300 or len(self.current_tasks) > 0  # 5 minutes
    
    async def _emit_event(self, event_type: EventType, data: Dict[str, Any], correlation_id: Optional[str] = None) -> None:
        """Emit event using centralized system"""
        if self.event_emitter:
            event = GleitzeitEvent(
                event_type=event_type,
                data=data,
                source=f"worker:{self.worker_id}",
                timestamp=datetime.utcnow(),
                correlation_id=correlation_id
            )
            await self.event_emitter(event)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics"""
        uptime = None
        if self.stats["started_at"]:
            uptime = (datetime.utcnow() - self.stats["started_at"]).total_seconds()
            
        avg_execution_time = 0
        if self.stats["tasks_completed"] > 0:
            avg_execution_time = self.stats["total_execution_time"] / self.stats["tasks_completed"]
            
        return {
            "worker_id": self.worker_id,
            "state": self.state.value,
            "tasks_completed": self.stats["tasks_completed"],
            "tasks_failed": self.stats["tasks_failed"],
            "avg_execution_time": avg_execution_time,
            "uptime_seconds": uptime,
            "current_load": len(self.current_tasks)
        }
    
    def __repr__(self) -> str:
        return f"ProviderWorker({self.worker_id}, {self.state.value}, tasks={len(self.current_tasks)})"