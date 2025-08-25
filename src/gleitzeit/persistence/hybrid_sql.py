"""
Hybrid SQL Persistence Adapter

Combines in-memory runtime persistence with SQL archival storage.
Memory adapter handles all active task coordination with monitoring,
while SQL adapter archives completed/failed tasks for audit trails.
"""

import os
import logging
import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Set
from datetime import datetime

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("psutil not available, memory monitoring disabled")

from gleitzeit.persistence.unified_memory_events import UnifiedMemoryEventsAdapter
from gleitzeit.persistence.unified_sqlalchemy import UnifiedSQLAlchemyAdapter
from gleitzeit.core.models import Task, TaskStatus, Workflow, WorkflowStatus, TaskResult
from gleitzeit.core.errors import PersistenceError, ErrorCode

logger = logging.getLogger(__name__)


@dataclass
class MemoryStats:
    """Memory usage statistics"""
    used_mb: float
    max_mb: float
    task_count: int
    workflow_count: int
    result_count: int
    usage_ratio: float


class MonitoredMemoryAdapter(UnifiedMemoryEventsAdapter):
    """
    Memory adapter with monitoring and memory limit enforcement.
    """
    
    def __init__(
        self,
        max_memory_mb: int = 1024,
        enable_monitoring: bool = True,
        warning_threshold: float = 0.8,
        critical_threshold: float = 0.95,
        monitor_interval: int = 10,
        *args,
        **kwargs
    ):
        """
        Initialize memory adapter with monitoring.
        
        Args:
            max_memory_mb: Maximum memory limit in MB
            enable_monitoring: Enable memory monitoring
            warning_threshold: Warn at this memory usage ratio
            critical_threshold: Reject new tasks at this ratio
            monitor_interval: Check interval in seconds
        """
        super().__init__(*args, **kwargs)
        
        self.max_memory_mb = max_memory_mb
        self.enable_monitoring = enable_monitoring and PSUTIL_AVAILABLE
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.monitor_interval = monitor_interval
        
        self._monitor_task = None
        self._archived_tasks: Set[str] = set()  # Track archived tasks for cleanup
        
        if self.enable_monitoring:
            logger.info(f"Memory monitoring enabled: max={max_memory_mb}MB, "
                       f"warning={warning_threshold*100}%, critical={critical_threshold*100}%")
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage of this process in MB"""
        if not PSUTIL_AVAILABLE:
            return 0.0
        try:
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except Exception as e:
            logger.error(f"Failed to get memory usage: {e}")
            return 0.0
    
    def get_memory_stats(self) -> MemoryStats:
        """Get detailed memory statistics"""
        used_mb = self._get_memory_usage()
        usage_ratio = used_mb / self.max_memory_mb if self.max_memory_mb > 0 else 0
        
        return MemoryStats(
            used_mb=used_mb,
            max_mb=self.max_memory_mb,
            task_count=len(self.tasks),
            workflow_count=len(self.workflows),
            result_count=len(self.task_results),
            usage_ratio=usage_ratio
        )
    
    async def _monitor_memory(self):
        """Background task to monitor memory usage"""
        logger.info("Starting memory monitor task")
        
        while self.enable_monitoring:
            try:
                stats = self.get_memory_stats()
                
                if stats.usage_ratio > self.critical_threshold:
                    logger.critical(
                        f"MEMORY CRITICAL: {stats.used_mb:.1f}MB / {stats.max_mb:.1f}MB "
                        f"({stats.usage_ratio*100:.1f}%) - Tasks: {stats.task_count}, "
                        f"Workflows: {stats.workflow_count}, Results: {stats.result_count}"
                    )
                    # Trigger cleanup of completed tasks
                    await self._cleanup_archived_tasks()
                    
                elif stats.usage_ratio > self.warning_threshold:
                    logger.warning(
                        f"Memory usage high: {stats.used_mb:.1f}MB / {stats.max_mb:.1f}MB "
                        f"({stats.usage_ratio*100:.1f}%) - Tasks: {stats.task_count}"
                    )
                
                await asyncio.sleep(self.monitor_interval)
                
            except Exception as e:
                logger.error(f"Error in memory monitor: {e}")
                await asyncio.sleep(self.monitor_interval)
    
    async def _check_memory_before_save(self) -> None:
        """Check memory before accepting new tasks"""
        if not self.enable_monitoring:
            return
            
        stats = self.get_memory_stats()
        
        if stats.usage_ratio > self.critical_threshold:
            raise MemoryError(
                f"Out of memory: {stats.used_mb:.1f}MB / {stats.max_mb:.1f}MB "
                f"({stats.usage_ratio*100:.1f}%). Cannot accept new tasks. "
                f"Consider increasing GLEITZEIT_MAX_MEMORY_MB or using Redis backend."
            )
    
    async def save_task(self, task: Task) -> None:
        """Save task with memory check"""
        await self._check_memory_before_save()
        await super().save_task(task)
    
    async def save_workflow(self, workflow: Workflow) -> None:
        """Save workflow with memory check"""
        await self._check_memory_before_save()
        await super().save_workflow(workflow)
    
    async def _cleanup_archived_tasks(self) -> int:
        """Remove completed tasks that have been archived"""
        cleaned = 0
        
        for task_id in list(self.tasks.keys()):
            if task_id in self._archived_tasks:
                task = self.tasks.get(task_id)
                if task and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                    # Remove task and its result
                    del self.tasks[task_id]
                    if task_id in self.task_results:
                        del self.task_results[task_id]
                    self._archived_tasks.discard(task_id)
                    cleaned += 1
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} archived tasks to free memory")
        
        return cleaned
    
    async def start_monitoring(self):
        """Start the memory monitoring task"""
        if self.enable_monitoring and not self._monitor_task:
            self._monitor_task = asyncio.create_task(self._monitor_memory())
            logger.info("Memory monitoring started")
    
    async def stop_monitoring(self):
        """Stop the memory monitoring task"""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
            logger.info("Memory monitoring stopped")


class HybridSQLAdapter:
    """
    Hybrid persistence adapter combining memory runtime with SQL archive.
    
    This adapter delegates all methods to the runtime adapter, while
    archiving completed/failed tasks to SQL for audit trails.
    """
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        max_memory_mb: Optional[int] = None,
        event_bus=None
    ):
        """
        Initialize hybrid adapter.
        
        Args:
            connection_string: SQL database connection string
            max_memory_mb: Maximum memory limit in MB
            event_bus: Event bus for coordination
        """
        # Get configuration from environment
        max_memory = max_memory_mb or int(os.getenv("GLEITZEIT_MAX_MEMORY_MB", "1024"))
        warning_threshold = float(os.getenv("GLEITZEIT_MEMORY_WARNING_THRESHOLD", "0.8"))
        critical_threshold = float(os.getenv("GLEITZEIT_MEMORY_CRITICAL_THRESHOLD", "0.95"))
        monitor_interval = int(os.getenv("GLEITZEIT_MEMORY_MONITOR_INTERVAL", "10"))
        
        # Initialize runtime adapter with monitoring
        self.runtime = MonitoredMemoryAdapter(
            max_memory_mb=max_memory,
            enable_monitoring=True,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            monitor_interval=monitor_interval,
            event_bus=event_bus
        )
        
        # Initialize archive adapter (SQL)
        self.archive = UnifiedSQLAlchemyAdapter(
            connection_string=connection_string
            # No event bus for archive - SQL adapter doesn't support it
        )
        
        self._initialized = False
        self.event_bus = event_bus
        
        logger.info(f"Initialized HybridSQLAdapter with {max_memory}MB memory limit")
    
    async def initialize(self) -> None:
        """Initialize both adapters"""
        await self.runtime.initialize()
        await self.archive.initialize()
        
        # Start memory monitoring
        await self.runtime.start_monitoring()
        
        self._initialized = True
        logger.info("HybridSQLAdapter initialized")
    
    async def shutdown(self) -> None:
        """Shutdown both adapters"""
        await self.runtime.stop_monitoring()
        await self.runtime.shutdown()
        await self.archive.shutdown()
        self._initialized = False
    
    async def cleanup(self) -> None:
        """Cleanup both adapters (alias for shutdown)"""
        await self.shutdown()
    
    # =========================================================================
    # Task Operations - Delegate to runtime, archive terminal states
    # =========================================================================
    
    async def save_task(self, task: Task) -> None:
        """Save task to runtime, archive if terminal state"""
        # Validate workflow_id requirement
        if not task.workflow_id:
            error_msg = (
                f"Task {task.id} ({task.name}) cannot be saved without a workflow_id. "
                "Every task must belong to a workflow. "
                "Use ExecutionEngine.submit_task() which auto-creates workflows for single tasks."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Always save to runtime
        await self.runtime.save_task(task)
        
        # Archive terminal states
        if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
            try:
                await self.archive.save_task(task)
                self.runtime._archived_tasks.add(task.id)
                
                # Check if cleanup needed
                stats = self.runtime.get_memory_stats()
                if stats.usage_ratio > 0.9:
                    await self.runtime._cleanup_archived_tasks()
                    
            except Exception as e:
                # Archive failure shouldn't affect runtime
                logger.error(f"Failed to archive task {task.id}: {e}")
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task from runtime or archive"""
        # Check runtime first
        task = await self.runtime.get_task(task_id)
        if task:
            return task
        
        # Fall back to archive
        return await self.archive.get_task(task_id)
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete task from runtime"""
        return await self.runtime.delete_task(task_id)
    
    async def get_tasks_by_status(self, status: str) -> List[Task]:
        """Get tasks by status from runtime"""
        return await self.runtime.get_tasks_by_status(status)
    
    async def get_tasks_by_workflow(self, workflow_id: str) -> List[Task]:
        """Get tasks by workflow from runtime"""
        return await self.runtime.get_tasks_by_workflow(workflow_id)
    
    # =========================================================================
    # Task Result Operations
    # =========================================================================
    
    async def save_task_result(self, result: TaskResult) -> None:
        """Save task result to runtime and archive"""
        await self.runtime.save_task_result(result)
        
        # Also archive the result
        try:
            await self.archive.save_task_result(result)
        except Exception as e:
            logger.error(f"Failed to archive result for task {result.task_id}: {e}")
    
    async def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """Get task result from runtime or archive"""
        # Check runtime first
        result = await self.runtime.get_task_result(task_id)
        if result:
            return result
        
        # Fall back to archive
        return await self.archive.get_task_result(task_id)
    
    # =========================================================================
    # Workflow Operations
    # =========================================================================
    
    async def save_workflow(self, workflow: Workflow) -> None:
        """Save workflow to runtime, archive if terminal state"""
        await self.runtime.save_workflow(workflow)
        
        # Archive terminal states
        if workflow.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
            try:
                await self.archive.save_workflow(workflow)
            except Exception as e:
                logger.error(f"Failed to archive workflow {workflow.id}: {e}")
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get workflow from runtime or archive"""
        # Check runtime first
        workflow = await self.runtime.get_workflow(workflow_id)
        if workflow:
            return workflow
        
        # Fall back to archive
        return await self.archive.get_workflow(workflow_id)
    
    async def delete_workflow(self, workflow_id: str) -> bool:
        """Delete workflow from runtime"""
        return await self.runtime.delete_workflow(workflow_id)
    
    # =========================================================================
    # Delegate all other methods to runtime adapter
    # =========================================================================
    
    async def save_workflow_execution(self, execution: Any) -> None:
        return await self.runtime.save_workflow_execution(execution)
    
    async def get_workflow_execution(self, execution_id: str) -> Any:
        return await self.runtime.get_workflow_execution(execution_id)
    
    async def save_queue_state(self, queue_name: str, state: Dict[str, Any]) -> None:
        return await self.runtime.save_queue_state(queue_name, state)
    
    async def get_queue_state(self, queue_name: str) -> Optional[Dict[str, Any]]:
        return await self.runtime.get_queue_state(queue_name)
    
    async def delete_queue_state(self, queue_name: str) -> bool:
        return await self.runtime.delete_queue_state(queue_name)
    
    async def save_tasks_batch(self, tasks: List[Task]) -> None:
        return await self.runtime.save_tasks_batch(tasks)
    
    async def get_all_queued_tasks(self) -> List[Task]:
        return await self.runtime.get_all_queued_tasks()
    
    async def get_task_count_by_status(self) -> Dict[str, int]:
        return await self.runtime.get_task_count_by_status()
    
    async def cleanup_old_data(self, cutoff_date: datetime) -> int:
        return await self.runtime.cleanup_old_data(cutoff_date)
    
    async def list_workflows(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return await self.runtime.list_workflows(status, limit, offset)
    
    async def list_tasks(self, workflow_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return await self.runtime.list_tasks(workflow_id, status, limit, offset)
    
    # Resource management delegation
    async def save_instance(self, hub_id: str, instance: Any) -> None:
        return await self.runtime.save_instance(hub_id, instance)
    
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        return await self.runtime.load_instance(instance_id)
    
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
        return await self.runtime.list_instances(hub_id)
    
    async def delete_instance(self, instance_id: str) -> None:
        return await self.runtime.delete_instance(instance_id)
    
    async def save_metrics(self, instance_id: str, metrics: Any) -> None:
        return await self.runtime.save_metrics(instance_id, metrics)
    
    async def get_metrics_history(self, instance_id: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None, limit: int = 100) -> List[Any]:
        return await self.runtime.get_metrics_history(instance_id, start_time, end_time, limit)
    
    # Lock operations
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        return await self.runtime.acquire_lock(resource_id, owner_id, timeout)
    
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        return await self.runtime.release_lock(resource_id, owner_id)
    
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        return await self.runtime.extend_lock(resource_id, owner_id, timeout)
    
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        return await self.runtime.get_lock_owner(resource_id)
    
    async def is_locked(self, resource_id: str) -> bool:
        return await self.runtime.is_locked(resource_id)
    
    # Queue operations (runtime only)
    async def enqueue_task(self, queue_name: str, task_id: str) -> None:
        return await self.runtime.enqueue_task(queue_name, task_id)
    
    async def dequeue_task(self, queue_name: str) -> Optional[str]:
        return await self.runtime.dequeue_task(queue_name)
    
    async def peek_queue(self, queue_name: str, count: int = 10) -> List[str]:
        return await self.runtime.peek_queue(queue_name, count)
    
    async def get_queue_length(self, queue_name: str) -> int:
        return await self.runtime.get_queue_length(queue_name)
    
    # Event operations (runtime only)
    async def emit_event(self, event: Any) -> None:
        return await self.runtime.emit_event(event)
    
    async def subscribe_to_events(self, event_types: List[str], callback: Any) -> str:
        return await self.runtime.subscribe_to_events(event_types, callback)
    
    async def unsubscribe_from_events(self, subscription_id: str) -> None:
        return await self.runtime.unsubscribe_from_events(subscription_id)
    
    # Monitoring
    def get_memory_stats(self) -> MemoryStats:
        """Get memory statistics from runtime adapter"""
        return self.runtime.get_memory_stats()
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check for both adapters"""
        runtime_health = await self.runtime.health_check()
        archive_health = await self.archive.health_check()
        memory_stats = self.runtime.get_memory_stats()
        
        return {
            "runtime": runtime_health,
            "archive": archive_health,
            "memory": {
                "used_mb": memory_stats.used_mb,
                "max_mb": memory_stats.max_mb,
                "usage_ratio": memory_stats.usage_ratio,
                "task_count": memory_stats.task_count,
                "workflow_count": memory_stats.workflow_count
            }
        }