"""
Task Queue for Gleitzeit V2

Advanced queuing system with priority handling, dependency resolution,
and batch processing support.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime
from collections import defaultdict, deque

from .models import Task, Priority, TaskStatus
from ..storage.redis_client import RedisClient

logger = logging.getLogger(__name__)


class TaskQueue:
    """
    Advanced task queue with dependency resolution
    
    Features:
    - Priority-based queuing (urgent, high, normal, low)
    - Task dependency resolution and ordering
    - Batch processing support
    - Redis persistence
    - Deadlock detection and prevention
    """
    
    def __init__(self, redis_client: RedisClient):
        self.redis_client = redis_client
        
        # Priority queues (in-memory for fast access)
        self.queues: Dict[Priority, deque] = {
            Priority.URGENT: deque(),
            Priority.HIGH: deque(),
            Priority.NORMAL: deque(),
            Priority.LOW: deque()
        }
        
        # Dependency tracking
        self.task_dependencies: Dict[str, Set[str]] = {}  # task_id -> {dependency_ids}
        self.dependency_graph: Dict[str, Set[str]] = {}  # task_id -> {dependent_task_ids}
        self.completed_tasks: Set[str] = set()
        
        # Task registry
        self.tasks: Dict[str, Task] = {}  # task_id -> Task
        
        # Queue state
        self._queue_lock = asyncio.Lock()
        
        logger.info("TaskQueue initialized")
    
    async def enqueue_task(self, task: Task) -> None:
        """Add task to appropriate priority queue"""
        async with self._queue_lock:
            try:
                # Store task
                self.tasks[task.id] = task
                
                # Track dependencies
                if task.dependencies:
                    self.task_dependencies[task.id] = set(task.dependencies)
                    
                    # Build dependency graph (reverse mapping)
                    for dep_id in task.dependencies:
                        if dep_id not in self.dependency_graph:
                            self.dependency_graph[dep_id] = set()
                        self.dependency_graph[dep_id].add(task.id)
                
                # Store in Redis for persistence
                await self._persist_task(task)
                
                # Add to appropriate queue if ready
                if self._is_task_ready(task):
                    self.queues[task.priority].append(task.id)
                    task.status = TaskStatus.QUEUED
                    await self._update_task_status(task.id, TaskStatus.QUEUED)
                    
                    logger.debug(f"Task queued: {task.id} (priority: {task.priority.value})")
                else:
                    task.status = TaskStatus.PENDING
                    await self._update_task_status(task.id, TaskStatus.PENDING)
                    logger.debug(f"Task pending dependencies: {task.id}")
                
            except Exception as e:
                logger.error(f"Failed to enqueue task {task.id}: {e}")
                raise
    
    async def enqueue_batch(self, tasks: List[Task]) -> None:
        """Enqueue multiple tasks as a batch"""
        async with self._queue_lock:
            logger.info(f"Enqueueing batch of {len(tasks)} tasks")
            
            # First pass: register all tasks and dependencies
            for task in tasks:
                self.tasks[task.id] = task
                if task.dependencies:
                    self.task_dependencies[task.id] = set(task.dependencies)
            
            # Build dependency graph
            self._build_dependency_graph(tasks)
            
            # Check for cycles
            cycles = self._detect_cycles(tasks)
            if cycles:
                raise ValueError(f"Circular dependencies detected: {cycles}")
            
            # Second pass: persist and queue ready tasks
            ready_tasks = []
            for task in tasks:
                await self._persist_task(task)
                
                if self._is_task_ready(task):
                    self.queues[task.priority].append(task.id)
                    task.status = TaskStatus.QUEUED
                    ready_tasks.append(task.id)
                else:
                    task.status = TaskStatus.PENDING
                
                await self._update_task_status(task.id, task.status)
            
            logger.info(f"Batch enqueued: {len(ready_tasks)} ready, {len(tasks) - len(ready_tasks)} pending")
    
    async def dequeue_task(self, provider_capabilities: Optional[Set] = None) -> Optional[Task]:
        """Get next available task from queue"""
        async with self._queue_lock:
            # Check queues in priority order
            for priority in [Priority.URGENT, Priority.HIGH, Priority.NORMAL, Priority.LOW]:
                queue = self.queues[priority]
                
                # Try to find a compatible task
                for _ in range(len(queue)):
                    task_id = queue.popleft()
                    task = self.tasks.get(task_id)
                    
                    if not task:
                        continue
                    
                    # Check if task is still ready (dependencies might have changed)
                    if not self._is_task_ready(task):
                        # Put back in pending state
                        task.status = TaskStatus.PENDING
                        await self._update_task_status(task.id, TaskStatus.PENDING)
                        continue
                    
                    # Check provider compatibility if specified
                    if provider_capabilities and not self._is_compatible(task, provider_capabilities):
                        # Put task back at end of queue
                        queue.append(task_id)
                        continue
                    
                    # Task is ready and compatible
                    task.status = TaskStatus.ASSIGNED
                    await self._update_task_status(task.id, TaskStatus.ASSIGNED)
                    
                    logger.debug(f"Task dequeued: {task.id} (priority: {task.priority.value})")
                    return task
            
            return None
    
    async def mark_task_completed(self, task_id: str, result: Optional[any] = None) -> List[str]:
        """Mark task as completed and return newly available tasks"""
        async with self._queue_lock:
            newly_available = []
            
            try:
                # Mark as completed
                self.completed_tasks.add(task_id)
                
                if task_id in self.tasks:
                    task = self.tasks[task_id]
                    task.status = TaskStatus.COMPLETED
                    task.result = result
                    task.completed_at = datetime.utcnow()
                    await self._update_task_status(task_id, TaskStatus.COMPLETED)
                
                # Check dependent tasks
                if task_id in self.dependency_graph:
                    for dependent_id in self.dependency_graph[task_id]:
                        dependent_task = self.tasks.get(dependent_id)
                        
                        if dependent_task and self._is_task_ready(dependent_task):
                            # Move from pending to queue
                            if dependent_task.status == TaskStatus.PENDING:
                                self.queues[dependent_task.priority].append(dependent_id)
                                dependent_task.status = TaskStatus.QUEUED
                                await self._update_task_status(dependent_id, TaskStatus.QUEUED)
                                newly_available.append(dependent_id)
                                
                                logger.debug(f"Task became available: {dependent_id}")
                
                # Persist completion
                await self._persist_task_completion(task_id, result)
                
                logger.debug(f"Task completed: {task_id}, {len(newly_available)} tasks became available")
                
            except Exception as e:
                logger.error(f"Failed to mark task completed {task_id}: {e}")
                raise
            
            return newly_available
    
    async def mark_task_failed(self, task_id: str, error: str) -> None:
        """Mark task as failed"""
        async with self._queue_lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task.status = TaskStatus.FAILED
                task.error = error
                task.completed_at = datetime.utcnow()
                await self._update_task_status(task_id, TaskStatus.FAILED)
                
                # Persist failure
                await self._persist_task_failure(task_id, error)
                
                logger.warning(f"Task failed: {task_id} - {error}")
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task"""
        async with self._queue_lock:
            if task_id not in self.tasks:
                return False
            
            task = self.tasks[task_id]
            
            # Can only cancel pending or queued tasks
            if task.status in [TaskStatus.PENDING, TaskStatus.QUEUED]:
                task.status = TaskStatus.CANCELLED
                
                # Remove from queue if present
                for queue in self.queues.values():
                    if task_id in queue:
                        queue.remove(task_id)
                        break
                
                await self._update_task_status(task_id, TaskStatus.CANCELLED)
                logger.info(f"Task cancelled: {task_id}")
                return True
            
            return False
    
    async def get_pending_tasks_for_workflow(self, workflow_id: str) -> List[Task]:
        """Get all pending tasks for a workflow"""
        return [
            task for task in self.tasks.values()
            if task.workflow_id == workflow_id and task.status in [TaskStatus.PENDING, TaskStatus.QUEUED]
        ]
    
    async def get_workflow_progress(self, workflow_id: str) -> Dict:
        """Get progress statistics for a workflow"""
        workflow_tasks = [t for t in self.tasks.values() if t.workflow_id == workflow_id]
        
        if not workflow_tasks:
            return {}
        
        by_status = defaultdict(int)
        for task in workflow_tasks:
            by_status[task.status.value] += 1
        
        total = len(workflow_tasks)
        completed = by_status[TaskStatus.COMPLETED.value]
        
        return {
            'total': total,
            'by_status': dict(by_status),
            'progress_percent': (completed / total * 100) if total > 0 else 0
        }
    
    def _is_task_ready(self, task: Task) -> bool:
        """Check if task dependencies are satisfied"""
        if not task.dependencies:
            return True
        
        return all(dep_id in self.completed_tasks for dep_id in task.dependencies)
    
    def _is_compatible(self, task: Task, provider_capabilities: Set) -> bool:
        """Check if task is compatible with provider capabilities"""
        # Simple compatibility check - can be enhanced
        return task.task_type.value in provider_capabilities
    
    def _build_dependency_graph(self, tasks: List[Task]):
        """Build dependency graph for batch processing"""
        self.dependency_graph.clear()
        
        for task in tasks:
            if task.dependencies:
                for dep_id in task.dependencies:
                    if dep_id not in self.dependency_graph:
                        self.dependency_graph[dep_id] = set()
                    self.dependency_graph[dep_id].add(task.id)
    
    def _detect_cycles(self, tasks: List[Task]) -> List[List[str]]:
        """Detect circular dependencies using DFS"""
        visited = set()
        rec_stack = set()
        cycles = []
        
        def dfs(task_id: str, path: List[str]) -> bool:
            if task_id in rec_stack:
                # Found cycle
                cycle_start = path.index(task_id)
                cycles.append(path[cycle_start:] + [task_id])
                return True
            
            if task_id in visited:
                return False
            
            visited.add(task_id)
            rec_stack.add(task_id)
            
            # Check dependencies
            if task_id in self.task_dependencies:
                for dep_id in self.task_dependencies[task_id]:
                    if dfs(dep_id, path + [task_id]):
                        return True
            
            rec_stack.remove(task_id)
            return False
        
        for task in tasks:
            if task.id not in visited:
                dfs(task.id, [])
        
        return cycles
    
    async def _persist_task(self, task: Task):
        """Persist task to Redis"""
        await self.redis_client.store_task(task)
    
    async def _update_task_status(self, task_id: str, status: TaskStatus):
        """Update task status in Redis"""
        await self.redis_client.update_task_status(task_id, status)
    
    async def _persist_task_completion(self, task_id: str, result: any):
        """Persist task completion to Redis"""
        await self.redis_client.complete_task(task_id, result=result)
    
    async def _persist_task_failure(self, task_id: str, error: str):
        """Persist task failure to Redis"""
        await self.redis_client.complete_task(task_id, error=error)
    
    def get_queue_size(self) -> int:
        """Get total number of queued tasks"""
        return sum(len(queue) for queue in self.queues.values())
    
    def get_queue_stats(self) -> Dict:
        """Get queue statistics"""
        stats = {}
        for priority, queue in self.queues.items():
            stats[priority.value] = len(queue)
        
        return {
            'by_priority': stats,
            'total_queued': self.get_queue_size(),
            'total_tasks': len(self.tasks),
            'completed_tasks': len(self.completed_tasks),
            'pending_tasks': len([t for t in self.tasks.values() if t.status == TaskStatus.PENDING])
        }