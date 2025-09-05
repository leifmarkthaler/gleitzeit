"""
Redis-based task queue for stateless task execution.

This module provides a simple, reliable task queue using Redis LIST
operations, eliminating the need for complex event registration.
"""

import asyncio
import logging
import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from gleitzeit.core.models import Task, TaskStatus, WorkflowStatus
from gleitzeit.persistence.atomic_operations import AtomicPersistenceOperations

logger = logging.getLogger(__name__)


class RedisTaskQueue:
    """
    Simple Redis-based task queue for stateless operation.
    
    Uses Redis LIST for queue operations:
    - LPUSH to add tasks
    - BRPOP to consume tasks (blocking pop)
    - Automatic retry on failure
    """
    
    def __init__(self, redis_client, persistence, atomic_ops: Optional[AtomicPersistenceOperations] = None):
        """
        Initialize Redis task queue.
        
        Args:
            redis_client: Redis client instance
            persistence: Persistence adapter for task/workflow data
            atomic_ops: Optional atomic operations instance
        """
        self.redis = redis_client
        self.persistence = persistence
        self.atomic_ops = atomic_ops or AtomicPersistenceOperations(redis_client, persistence)
        
        # Queue keys
        self.READY_QUEUE = "gleitzeit:queue:ready"  # Tasks ready to execute
        self.PROCESSING_SET = "gleitzeit:queue:processing"  # Tasks being processed
        self.COMPLETED_SET = "gleitzeit:queue:completed"  # Completed tasks
        self.FAILED_QUEUE = "gleitzeit:queue:failed"  # Failed tasks for retry
        
        logger.info("Initialized RedisTaskQueue")
    
    async def submit_workflow(self, workflow_id: str) -> int:
        """
        Submit a workflow by enqueueing all ready tasks.
        
        Args:
            workflow_id: ID of workflow to submit
            
        Returns:
            Number of tasks enqueued
        """
        # Get workflow
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            logger.error(f"Workflow {workflow_id} not found")
            return 0
        
        # Find tasks with no dependencies
        ready_count = 0
        for task in workflow.tasks:
            if not task.dependencies:
                await self.enqueue_task(task.id, workflow_id)
                ready_count += 1
                logger.info(f"Enqueued task {task.id} (no dependencies)")
        
        logger.info(f"Submitted workflow {workflow_id} with {ready_count} initial tasks")
        return ready_count
    
    async def enqueue_task(self, task_id: str, workflow_id: str) -> bool:
        """
        Add a task to the ready queue.
        
        Args:
            task_id: Task ID to enqueue
            workflow_id: Workflow ID the task belongs to
            
        Returns:
            True if enqueued successfully
        """
        # Create queue entry
        entry = json.dumps({
            'task_id': task_id,
            'workflow_id': workflow_id,
            'enqueued_at': datetime.utcnow().isoformat()
        })
        
        # Add to queue
        await self.redis.lpush(self.READY_QUEUE, entry)
        
        # Update task status
        task = await self.persistence.get_task(task_id)
        if task:
            task.status = TaskStatus.QUEUED
            await self.persistence.save_task(task)
        
        logger.debug(f"Enqueued task {task_id}")
        return True
    
    async def dequeue_task(self, worker_id: str, timeout: int = 1) -> Optional[Dict[str, Any]]:
        """
        Get next task from queue (blocking).
        
        Args:
            worker_id: ID of worker dequeuing the task
            timeout: Blocking timeout in seconds
            
        Returns:
            Task entry dict or None if timeout
        """
        # Blocking pop from ready queue
        result = await self.redis.brpop(self.READY_QUEUE, timeout=timeout)
        
        if not result:
            return None
        
        # Parse entry
        _, entry_data = result
        entry = json.loads(entry_data)
        task_id = entry['task_id']
        
        # Try to claim the task atomically
        if self.atomic_ops:
            claimed = await self.atomic_ops.claim_task(task_id, worker_id)
            if not claimed:
                logger.debug(f"Failed to claim task {task_id}")
                return None
        
        # Add to processing set
        await self.redis.sadd(self.PROCESSING_SET, task_id)
        
        logger.info(f"Worker {worker_id} dequeued task {task_id}")
        return entry
    
    async def complete_task(self, task_id: str, workflow_id: str) -> None:
        """
        Mark task as completed and check for newly ready tasks.
        
        Args:
            task_id: Completed task ID
            workflow_id: Workflow ID
        """
        # Remove from processing set
        await self.redis.srem(self.PROCESSING_SET, task_id)
        
        # Add to completed set
        await self.redis.sadd(self.COMPLETED_SET, task_id)
        
        # Update task status
        task = await self.persistence.get_task(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            await self.persistence.save_task(task)
        
        # Check for newly ready tasks
        await self._check_newly_ready_tasks(workflow_id, task_id)
        
        # Check if workflow is complete
        await self._check_workflow_completion(workflow_id)
        
        logger.info(f"Task {task_id} completed")
    
    async def fail_task(self, task_id: str, error: str) -> None:
        """
        Mark task as failed and add to retry queue.
        
        Args:
            task_id: Failed task ID
            error: Error message
        """
        # Remove from processing set
        await self.redis.srem(self.PROCESSING_SET, task_id)
        
        # Add to failed queue for retry
        entry = json.dumps({
            'task_id': task_id,
            'error': error,
            'failed_at': datetime.utcnow().isoformat()
        })
        await self.redis.lpush(self.FAILED_QUEUE, entry)
        
        # Update task status
        task = await self.persistence.get_task(task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error_message = error
            await self.persistence.save_task(task)
        
        logger.error(f"Task {task_id} failed: {error}")
    
    async def _check_newly_ready_tasks(self, workflow_id: str, completed_task_id: str) -> None:
        """
        Check if any tasks are now ready after a task completion.
        
        Args:
            workflow_id: Workflow ID
            completed_task_id: Task that just completed
        """
        # Get all tasks for workflow
        tasks = await self.persistence.get_tasks_by_workflow(workflow_id)
        
        for task in tasks:
            # Skip if already processed
            if task.status in [TaskStatus.COMPLETED, TaskStatus.EXECUTING, TaskStatus.QUEUED]:
                continue
            
            # Check if this task depends on the completed one
            if completed_task_id in task.dependencies:
                # Check if ALL dependencies are now complete
                all_deps_complete = True
                for dep_id in task.dependencies:
                    dep_task = await self.persistence.get_task(dep_id)
                    if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                        all_deps_complete = False
                        break
                
                if all_deps_complete:
                    # This task is now ready
                    await self.enqueue_task(task.id, workflow_id)
                    logger.info(f"Task {task.id} now ready (all dependencies complete)")
    
    async def _check_workflow_completion(self, workflow_id: str) -> None:
        """
        Check if workflow is complete.
        
        Args:
            workflow_id: Workflow to check
        """
        # Get all tasks
        tasks = await self.persistence.get_tasks_by_workflow(workflow_id)
        
        # Check if all complete
        all_complete = all(
            task.status == TaskStatus.COMPLETED 
            for task in tasks
        )
        
        if all_complete:
            # Update workflow status
            workflow = await self.persistence.get_workflow(workflow_id)
            if workflow:
                workflow.status = WorkflowStatus.COMPLETED
                workflow.completed_at = datetime.utcnow()
                await self.persistence.save_workflow(workflow)
                logger.info(f"Workflow {workflow_id} completed")
    
    async def get_queue_stats(self) -> Dict[str, int]:
        """
        Get queue statistics.
        
        Returns:
            Dict with queue sizes
        """
        ready = await self.redis.llen(self.READY_QUEUE)
        processing = await self.redis.scard(self.PROCESSING_SET)
        completed = await self.redis.scard(self.COMPLETED_SET)
        failed = await self.redis.llen(self.FAILED_QUEUE)
        
        return {
            'ready': ready,
            'processing': processing,
            'completed': completed,
            'failed': failed
        }