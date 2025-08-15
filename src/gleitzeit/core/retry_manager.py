"""
Retry Manager for Gleitzeit V4

Handles failed task retry logic with exponential backoff,
jitter, and configurable retry strategies.
"""

import asyncio
import logging
import random
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
from enum import Enum

from gleitzeit.core.models import Task, TaskStatus, RetryConfig
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.task_queue.task_queue import QueueManager

logger = logging.getLogger(__name__)


class BackoffStrategy(str, Enum):
    """Retry backoff strategies"""
    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


class RetryManager:
    """
    Manages task retry logic with configurable backoff strategies
    
    Features:
    - Exponential, linear, and fixed delay strategies
    - Jitter to prevent thundering herd
    - Maximum retry limits per task
    - Persistent retry queue
    - Automatic retry scheduling
    """
    
    def __init__(self, 
                 queue_manager: QueueManager,
                 persistence: PersistenceBackend,
                 scheduler: Optional['EventScheduler'] = None):
        self.queue_manager = queue_manager
        self.persistence = persistence
        self.scheduler = scheduler
        
        # In-memory retry tracking (for stats only)
        self._retry_tasks: Dict[str, datetime] = {}  # task_id -> retry_at
        self._lock = asyncio.Lock()
        
        logger.info("Initialized event-driven RetryManager")
    
    # RetryManager is now stateless - no background tasks needed
    # Retries are scheduled through EventScheduler
    
    async def schedule_retry(self, task: Task, error_message: Optional[str] = None) -> bool:
        """
        Schedule a failed task for retry using event-driven persistence
        
        Args:
            task: Failed task to retry
            error_message: Error message from the failure
            
        Returns:
            True if retry was scheduled, False if max attempts reached
        """
        if not task.retry_config:
            logger.debug(f"Task {task.id} cannot be retried (no retry config)")
            return False
            
        # Get current retry count from our own retry tracking
        retry_info = await self.get_task_retry_info(task.id)
        current_count = retry_info.get('count', 0)
        max_attempts = task.retry_config.max_attempts
        
        if current_count >= max_attempts:
            logger.debug(f"Task {task.id} cannot be retried (count={current_count}, max={max_attempts})")
            return False
        
        # Calculate retry delay
        retry_delay = self._calculate_retry_delay(task, current_count)
        retry_at = datetime.utcnow() + retry_delay
        
        async with self._lock:
            # Update task status for retry (don't modify attempt count - it's in persistence)
            task.error_message = error_message
            task.status = TaskStatus.RETRY_PENDING
            
            # Save task state
            await self.persistence.save_task(task)
            
            # Track retry for stats (optional)
            self._retry_tasks[task.id] = retry_at
            
            # Use EventScheduler for actual retry scheduling
            if self.scheduler:
                await self.scheduler.schedule_task_retry(
                    task_id=task.id,
                    retry_delay=retry_delay,
                    attempt_count=current_count,  # Use count from persistence
                    error_message=error_message or "Unknown error"
                )
            else:
                logger.warning("No scheduler available - retry will not be processed")
                return False
        
        logger.info(f"Scheduled retry for task {task.id} (attempt {current_count}) in {retry_delay}")
        return True
    
    def _calculate_retry_delay(self, task: Task, attempt_count: int) -> timedelta:
        """Calculate retry delay based on backoff strategy"""
        if not task.retry_config:
            return timedelta(seconds=1)
        
        config = task.retry_config
        attempt = attempt_count  # Use the passed attempt count from persistence
        
        if config.backoff_strategy == BackoffStrategy.FIXED:
            delay_seconds = config.base_delay
            
        elif config.backoff_strategy == BackoffStrategy.LINEAR:
            delay_seconds = config.base_delay * attempt
            
        elif config.backoff_strategy == BackoffStrategy.EXPONENTIAL:
            delay_seconds = config.base_delay * (2 ** (attempt - 1))
            
        else:
            # Default to exponential
            delay_seconds = config.base_delay * (2 ** (attempt - 1))
        
        # Apply maximum delay limit
        delay_seconds = min(delay_seconds, config.max_delay)
        
        # Add jitter if enabled
        if config.jitter:
            jitter = random.uniform(0.1, 0.3) * delay_seconds
            delay_seconds += jitter
        
        return timedelta(seconds=delay_seconds)
    
    async def handle_retry_event(self, task_id: str) -> bool:
        """Handle retry event triggered by EventScheduler"""
        try:
            # Get task from persistence
            task = await self.persistence.get_task(task_id)
            if not task:
                logger.warning(f"Task {task_id} not found for retry")
                return False
            
            if task.status != TaskStatus.RETRY_PENDING:
                logger.warning(f"Task {task_id} is not in retry_pending status: {task.status}")
                return False
            
            # Reset task for retry
            task.status = TaskStatus.QUEUED
            task.started_at = None
            task.error_message = None
            
            # Re-queue the task
            await self.queue_manager.enqueue_task(task)
            
            # Remove from retry tracking
            async with self._lock:
                self._retry_tasks.pop(task_id, None)
            
            logger.info(f"Re-queued task {task_id} for retry (attempt {task.attempt_count})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to retry task {task_id}: {e}")
            return False
    
    async def cancel_retry(self, task_id: str) -> bool:
        """
        Cancel a scheduled retry
        
        Args:
            task_id: ID of task to cancel retry for
            
        Returns:
            True if retry was cancelled, False if not found
        """
        async with self._lock:
            if task_id in self._retry_tasks:
                del self._retry_tasks[task_id]
                
                # Update task status
                task = await self.persistence.get_task(task_id)
                if task:
                    task.status = TaskStatus.FAILED
                    await self.persistence.save_task(task)
                
                logger.info(f"Cancelled retry for task {task_id}")
                return True
        
        return False
    
    async def get_retry_stats(self) -> Dict[str, int]:
        """Get retry statistics"""
        async with self._lock:
            pending_retries = len(self._retry_tasks)
            
            # Count tasks by retry attempt
            attempt_counts = {}
            for task_id in self._retry_tasks.keys():
                task = await self.persistence.get_task(task_id)
                if task:
                    attempt = task.attempt_count
                    attempt_counts[f"attempt_{attempt}"] = attempt_counts.get(f"attempt_{attempt}", 0) + 1
        
        return {
            "pending_retries": pending_retries,
            **attempt_counts
        }
    
    async def get_pending_retries(self) -> List[Dict[str, any]]:
        """Get list of pending retry tasks with their retry times"""
        async with self._lock:
            retries = []
            for task_id, retry_at in self._retry_tasks.items():
                task = await self.persistence.get_task(task_id)
                if task:
                    retries.append({
                        "task_id": task_id,
                        "task_name": task.name,
                        "attempt": task.attempt_count,
                        "max_attempts": task.retry_config.max_attempts if task.retry_config else 3,
                        "retry_at": retry_at.isoformat(),
                        "error_message": task.error_message
                    })
            
            return sorted(retries, key=lambda x: x["retry_at"])
    
    async def cleanup_old_retries(self, cutoff_date: datetime) -> int:
        """Remove old retry tasks that are past their cutoff"""
        async with self._lock:
            old_tasks = [
                task_id for task_id, retry_at in self._retry_tasks.items()
                if retry_at < cutoff_date
            ]
            
            for task_id in old_tasks:
                del self._retry_tasks[task_id]
        
        return len(old_tasks)
    
    # Methods needed by ExecutionEngine for retry tracking
    async def increment_retry_count(self, task_id: str) -> int:
        """Increment retry count for a task and return current attempt number"""
        # In-memory tracking of retry attempts
        if not hasattr(self, '_task_attempts'):
            self._task_attempts: Dict[str, int] = {}
        
        current_attempt = self._task_attempts.get(task_id, 0) + 1
        self._task_attempts[task_id] = current_attempt
        
        logger.debug(f"Incremented retry count for task {task_id} to {current_attempt}")
        return current_attempt
    
    async def get_task_retry_info(self, task_id: str) -> Dict[str, int]:
        """Get retry information for a task"""
        if not hasattr(self, '_task_attempts'):
            self._task_attempts: Dict[str, int] = {}
        
        count = self._task_attempts.get(task_id, 0)
        return {"count": count, "task_id": task_id}