"""
Task Queue implementation for Gleitzeit V4

Priority-based task queuing with dependency management and workflow orchestration.
"""

import asyncio
import heapq
import logging
from typing import Dict, List, Optional, Set, Tuple, Any
from datetime import datetime, timedelta
from enum import IntEnum
from dataclasses import dataclass, field

from gleitzeit.core.models import Task, Workflow, TaskStatus, Priority
from gleitzeit.persistence.base import PersistenceBackend, InMemoryBackend

logger = logging.getLogger(__name__)


class QueuePriority(IntEnum):
    """Numeric priority values for heap sorting"""
    URGENT = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class QueuedTask:
    """Task wrapper for priority queue with ordering"""
    priority: int
    queued_at: datetime
    task: Task
    
    def __lt__(self, other):
        """Define ordering for heapq"""
        # Primary: priority (lower number = higher priority)
        if self.priority != other.priority:
            return self.priority < other.priority
        
        # Secondary: queued time (earlier = higher priority)
        return self.queued_at < other.queued_at


class TaskQueue:
    """
    Priority-based task queue with dependency management and persistence
    
    Features:
    - Priority-based ordering (urgent > high > normal > low)
    - FIFO within same priority level
    - Dependency checking before task dequeue
    - Workflow-aware task management
    - Persistent storage with recovery on restart
    """
    
    def __init__(self, name: str = "default", persistence: Optional[PersistenceBackend] = None):
        self.name = name
        self.persistence = persistence or InMemoryBackend()
        
        self._heap: List[QueuedTask] = []
        self._task_lookup: Dict[str, QueuedTask] = {}  # task_id -> QueuedTask
        self._workflow_tasks: Dict[str, Set[str]] = {}  # workflow_id -> set of task_ids
        self._completed_tasks: Set[str] = set()
        self._failed_tasks: Set[str] = set()
        self._lock = asyncio.Lock()
        
        # Statistics
        self.total_enqueued = 0
        self.total_dequeued = 0
        self.created_at = datetime.utcnow()
        self._initialized = False
        
        logger.info(f"Initialized TaskQueue: {name}")
    
    async def initialize(self) -> None:
        """Initialize persistence and recover queue state"""
        if self._initialized:
            return
        
        await self.persistence.initialize()
        await self._recover_from_persistence()
        self._initialized = True
        
        logger.info(f"TaskQueue {self.name} initialized with persistence")
    
    async def _recover_from_persistence(self) -> None:
        """Recover queue state from persistence"""
        try:
            # Recover tasks that should be queued
            queued_tasks = await self.persistence.get_all_queued_tasks()
            
            for task in queued_tasks:
                # Reset executing tasks to queued (they were interrupted)
                if task.status == TaskStatus.EXECUTING:
                    task.status = TaskStatus.QUEUED
                    await self.persistence.save_task(task)
                
                # Re-enqueue without persistence (already persisted)
                await self._enqueue_in_memory(task)
            
            # Recover queue statistics from persistence
            queue_state = await self.persistence.get_queue_state(self.name)
            if queue_state:
                self.total_enqueued = queue_state.get('total_enqueued', 0)
                self.total_dequeued = queue_state.get('total_dequeued', 0)
                self._completed_tasks = set(queue_state.get('completed_tasks', []))
                self._failed_tasks = set(queue_state.get('failed_tasks', []))
            
            logger.info(f"Recovered {len(queued_tasks)} tasks for queue {self.name}")
            
        except Exception as e:
            logger.error(f"Failed to recover queue {self.name} from persistence: {e}")
            # Continue with empty queue rather than failing
    
    async def _save_queue_state(self) -> None:
        """Save current queue state to persistence"""
        try:
            state = {
                'total_enqueued': self.total_enqueued,
                'total_dequeued': self.total_dequeued,
                'completed_tasks': list(self._completed_tasks),
                'failed_tasks': list(self._failed_tasks),
                'updated_at': datetime.utcnow().isoformat()
            }
            await self.persistence.save_queue_state(self.name, state)
        except Exception as e:
            logger.error(f"Failed to save queue state for {self.name}: {e}")
    
    async def enqueue(self, task: Task) -> None:
        """
        Add a task to the queue with persistence
        
        Args:
            task: Task to enqueue
        """
        async with self._lock:
            if task.id in self._task_lookup:
                logger.warning(f"Task {task.id} already in queue, skipping")
                return
            
            # Save to persistence first
            task.status = TaskStatus.QUEUED
            await self.persistence.save_task(task)
            
            # Then add to in-memory queue
            await self._enqueue_in_memory(task)
            
            # Save queue state periodically
            if self.total_enqueued % 10 == 0:  # Every 10 tasks
                await self._save_queue_state()
            
            logger.debug(f"Enqueued task {task.id} with priority {task.priority}")
    
    async def _enqueue_in_memory(self, task: Task) -> None:
        """Add task to in-memory queue structures (without persistence)"""
        # Convert priority to numeric value
        priority_map = {
            Priority.URGENT: QueuePriority.URGENT,
            Priority.HIGH: QueuePriority.HIGH,
            Priority.NORMAL: QueuePriority.NORMAL,
            Priority.LOW: QueuePriority.LOW
        }
        
        queued_task = QueuedTask(
            priority=priority_map[task.priority],
            queued_at=datetime.utcnow(),
            task=task
        )
        
        # Add to heap and lookup
        heapq.heappush(self._heap, queued_task)
        self._task_lookup[task.id] = queued_task
        
        # Track workflow tasks
        if task.workflow_id:
            if task.workflow_id not in self._workflow_tasks:
                self._workflow_tasks[task.workflow_id] = set()
            self._workflow_tasks[task.workflow_id].add(task.id)
        
        self.total_enqueued += 1
    
    async def dequeue(self, check_dependencies: bool = True) -> Optional[Task]:
        """
        Get the next available task from the queue
        
        Args:
            check_dependencies: Whether to check task dependencies
            
        Returns:
            Next available task or None if queue is empty or no tasks ready
        """
        async with self._lock:
            if not self._heap:
                return None
            
            # Find first task with satisfied dependencies
            available_tasks = []
            
            while self._heap:
                queued_task = heapq.heappop(self._heap)
                
                # Check if task still exists in lookup (might have been removed)
                if queued_task.task.id not in self._task_lookup:
                    continue
                
                # Check dependencies
                if check_dependencies and not self._are_dependencies_satisfied(queued_task.task):
                    available_tasks.append(queued_task)
                    continue
                
                # Found available task
                task = queued_task.task
                
                # Remove from lookup
                del self._task_lookup[task.id]
                
                # Re-queue tasks that weren't selected
                for queued in available_tasks:
                    heapq.heappush(self._heap, queued)
                
                # Update statistics
                self.total_dequeued += 1
                
                logger.debug(f"Dequeued task {task.id}")
                return task
            
            # No available tasks, re-queue all
            for queued in available_tasks:
                heapq.heappush(self._heap, queued)
            
            return None
    
    def _are_dependencies_satisfied(self, task: Task) -> bool:
        """Check if all task dependencies are completed"""
        if not task.dependencies:
            return True
        
        return all(dep_id in self._completed_tasks for dep_id in task.dependencies)
    
    async def remove_task(self, task_id: str) -> bool:
        """
        Remove a task from the queue
        
        Args:
            task_id: ID of task to remove
            
        Returns:
            True if task was removed, False if not found
        """
        async with self._lock:
            if task_id not in self._task_lookup:
                return False
            
            # Remove from lookup (heap entry will be ignored during dequeue)
            del self._task_lookup[task_id]
            
            # Remove from workflow tracking
            for workflow_id, task_ids in self._workflow_tasks.items():
                task_ids.discard(task_id)
            
            logger.debug(f"Removed task {task_id} from queue")
            return True
    
    async def mark_task_completed(self, task_id: str) -> None:
        """Mark a task as completed (satisfies dependencies)"""
        async with self._lock:
            self._completed_tasks.add(task_id)
            self._failed_tasks.discard(task_id)  # Remove from failed if it was there
            
            # Update task status in persistence
            task = await self.persistence.get_task(task_id)
            if task:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.utcnow()
                await self.persistence.save_task(task)
            
            logger.debug(f"Marked task {task_id} as completed")
    
    async def mark_task_failed(self, task_id: str) -> None:
        """Mark a task as failed"""
        async with self._lock:
            self._failed_tasks.add(task_id)
            self._completed_tasks.discard(task_id)  # Remove from completed if it was there
            
            # Update task status in persistence
            task = await self.persistence.get_task(task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.utcnow()
                await self.persistence.save_task(task)
            
            logger.debug(f"Marked task {task_id} as failed")
    
    async def get_ready_tasks(self, limit: Optional[int] = None) -> List[Task]:
        """
        Get list of tasks that are ready to execute (dependencies satisfied)
        
        Args:
            limit: Maximum number of tasks to return
            
        Returns:
            List of ready tasks
        """
        async with self._lock:
            ready_tasks = []
            
            for queued_task in sorted(self._heap):
                if limit and len(ready_tasks) >= limit:
                    break
                
                if queued_task.task.id in self._task_lookup:  # Still in queue
                    if self._are_dependencies_satisfied(queued_task.task):
                        ready_tasks.append(queued_task.task)
            
            return ready_tasks
    
    def size(self) -> int:
        """Get current queue size"""
        return len(self._task_lookup)
    
    def is_empty(self) -> bool:
        """Check if queue is empty"""
        return len(self._task_lookup) == 0
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        async with self._lock:
            priority_counts = {priority.name.lower(): 0 for priority in Priority}
            
            for queued_task in self._task_lookup.values():
                task_priority = queued_task.task.priority
                # Priority is already a string due to use_enum_values=True
                priority_counts[task_priority] += 1
            
            return {
                "name": self.name,
                "current_size": self.size(),
                "total_enqueued": self.total_enqueued,
                "total_dequeued": self.total_dequeued,
                "completed_tasks": len(self._completed_tasks),
                "failed_tasks": len(self._failed_tasks),
                "active_workflows": len(self._workflow_tasks),
                "priority_breakdown": priority_counts,
                "created_at": self.created_at.isoformat()
            }
    
    async def get_workflow_tasks(self, workflow_id: str) -> List[Task]:
        """Get all tasks for a specific workflow"""
        async with self._lock:
            task_ids = self._workflow_tasks.get(workflow_id, set())
            tasks = []
            
            for task_id in task_ids:
                if task_id in self._task_lookup:
                    tasks.append(self._task_lookup[task_id].task)
            
            return tasks
    
    async def clear(self) -> int:
        """Clear all tasks from the queue and return count of removed tasks"""
        async with self._lock:
            cleared_count = len(self._task_lookup)
            
            self._heap.clear()
            self._task_lookup.clear()
            self._workflow_tasks.clear()
            self._completed_tasks.clear()
            self._failed_tasks.clear()
            
            logger.info(f"Cleared {cleared_count} tasks from queue {self.name}")
            return cleared_count


class QueueManager:
    """
    Manager for multiple task queues with routing and load balancing
    """
    
    def __init__(self):
        self.queues: Dict[str, TaskQueue] = {}
        self.default_queue_name = "default"
        self._stats_lock = asyncio.Lock()
        
        # Create default queue
        self.queues[self.default_queue_name] = TaskQueue(self.default_queue_name)
        
        logger.info("Initialized QueueManager")
    
    def create_queue(self, name: str) -> TaskQueue:
        """Create a new task queue"""
        if name in self.queues:
            raise ValueError(f"Queue {name} already exists")
        
        queue = TaskQueue(name)
        self.queues[name] = queue
        
        logger.info(f"Created queue: {name}")
        return queue
    
    def get_queue(self, name: str) -> Optional[TaskQueue]:
        """Get a queue by name"""
        return self.queues.get(name)
    
    def get_default_queue(self) -> TaskQueue:
        """Get the default queue"""
        return self.queues[self.default_queue_name]
    
    async def enqueue_task(self, task: Task, queue_name: Optional[str] = None) -> None:
        """
        Enqueue a task to a specific queue or the default queue
        
        Args:
            task: Task to enqueue
            queue_name: Target queue name (uses default if None)
        """
        target_queue_name = queue_name or self.default_queue_name
        queue = self.get_queue(target_queue_name)
        
        if not queue:
            raise ValueError(f"Queue not found: {target_queue_name}")
        
        await queue.enqueue(task)
    
    async def dequeue_next_task(self, queue_names: Optional[List[str]] = None) -> Optional[Task]:
        """
        Get the next available task from specified queues (or all queues)
        
        Args:
            queue_names: List of queue names to check (all queues if None)
            
        Returns:
            Next available task with highest priority across all queues
        """
        target_queues = queue_names or list(self.queues.keys())
        available_tasks = []
        
        # Collect available tasks from all target queues
        for queue_name in target_queues:
            queue = self.get_queue(queue_name)
            if queue:
                ready_tasks = await queue.get_ready_tasks(limit=5)  # Get top 5 from each
                for task in ready_tasks:
                    available_tasks.append((task, queue_name))
        
        if not available_tasks:
            return None
        
        # Sort by priority and queue time
        available_tasks.sort(key=lambda x: (
            QueuePriority[x[0].priority.upper()].value,
            x[0].created_at
        ))
        
        # Dequeue the highest priority task
        best_task, best_queue_name = available_tasks[0]
        queue = self.get_queue(best_queue_name)
        
        if queue:
            # Try to dequeue the specific task
            dequeued_task = await queue.dequeue()
            if dequeued_task and dequeued_task.id == best_task.id:
                return dequeued_task
        
        return None
    
    async def mark_task_completed(self, task_id: str, queue_name: Optional[str] = None) -> None:
        """Mark a task as completed across all queues or specific queue"""
        if queue_name:
            queue = self.get_queue(queue_name)
            if queue:
                await queue.mark_task_completed(task_id)
        else:
            # Mark in all queues
            for queue in self.queues.values():
                await queue.mark_task_completed(task_id)
    
    async def mark_task_failed(self, task_id: str, queue_name: Optional[str] = None) -> None:
        """Mark a task as failed across all queues or specific queue"""
        if queue_name:
            queue = self.get_queue(queue_name)
            if queue:
                await queue.mark_task_failed(task_id)
        else:
            # Mark in all queues
            for queue in self.queues.values():
                await queue.mark_task_failed(task_id)
    
    async def get_global_stats(self) -> Dict[str, Any]:
        """Get statistics for all queues"""
        async with self._stats_lock:
            queue_stats = {}
            total_size = 0
            total_enqueued = 0
            total_dequeued = 0
            
            for name, queue in self.queues.items():
                stats = await queue.get_stats()
                queue_stats[name] = stats
                total_size += stats["current_size"]
                total_enqueued += stats["total_enqueued"]
                total_dequeued += stats["total_dequeued"]
            
            return {
                "total_queues": len(self.queues),
                "total_size": total_size,
                "total_enqueued": total_enqueued,
                "total_dequeued": total_dequeued,
                "queue_details": queue_stats
            }
    
    async def shutdown(self) -> None:
        """Shutdown all queues"""
        total_cleared = 0
        
        for queue in self.queues.values():
            cleared = await queue.clear()
            total_cleared += cleared
        
        logger.info(f"QueueManager shutdown complete, cleared {total_cleared} tasks")