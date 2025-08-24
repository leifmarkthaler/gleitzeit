"""
Retry Manager for Gleitzeit V4

Handles failed task retry logic with exponential backoff,
jitter, and configurable retry strategies.

Uses persistence backend for all state management - no in-memory structures.
"""

import asyncio
import logging
import random
from typing import Dict, List, Optional, Set, Any
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
    - Persistent retry tracking via persistence backend
    - Automatic retry scheduling
    - No in-memory state management
    """
    
    def __init__(self, 
                 queue_manager: QueueManager,
                 persistence: PersistenceBackend,
                 scheduler: Optional['EventScheduler'] = None,
                 event_bus: Optional[Any] = None):
        self.queue_manager = queue_manager
        self.persistence = persistence
        self.scheduler = scheduler
        self.event_bus = event_bus
        
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        
        logger.info("Initialized event-driven RetryManager with persistence backend")
    
    async def start(self) -> None:
        """Start the retry manager monitoring"""
        if self._running:
            return
        
        self._running = True
        # Start both monitoring tasks
        self._monitor_task = asyncio.create_task(self._monitor_retry_tasks())
        self._stuck_monitor_task = asyncio.create_task(self._monitor_stuck_tasks())
        logger.info("RetryManager monitoring started")
    
    async def stop(self) -> None:
        """Stop the retry manager monitoring"""
        self._running = False
        
        # Cancel both monitoring tasks
        for task in [self._monitor_task, getattr(self, '_stuck_monitor_task', None)]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self._monitor_task = None
        self._stuck_monitor_task = None
        
        logger.info("RetryManager monitoring stopped")
    
    async def _monitor_retry_tasks(self) -> None:
        """Monitor for tasks that need to be retried based on their retry_at time"""
        check_interval = 2.0  # Check every 2 seconds
        
        while self._running:
            try:
                # Get all tasks with RETRY_PENDING status from persistence
                result = await self.persistence.list_tasks(status=TaskStatus.RETRY_PENDING)
                if isinstance(result, dict):
                    retry_tasks = result.get('tasks', [])
                else:
                    retry_tasks = result if isinstance(result, list) else []
                
                now = datetime.utcnow()
                
                for task in retry_tasks:
                    # Check if task has retry_at metadata
                    if task.metadata and 'retry_at' in task.metadata:
                        retry_at_str = task.metadata['retry_at']
                        retry_at = datetime.fromisoformat(retry_at_str)
                        
                        # If it's time to retry, re-queue the task
                        if now >= retry_at:
                            logger.info(f"Retrying task {task.id} (attempt {task.metadata.get('retry_count', 1)})")
                            
                            # Reset task for retry
                            task.status = TaskStatus.QUEUED
                            task.started_at = None
                            task.error_message = None
                            
                            # Save updated task
                            await self.persistence.save_task(task)
                            
                            # Re-enqueue for execution
                            await self.queue_manager.enqueue_task(task)
                
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"Error in retry monitor: {e}")
                await asyncio.sleep(check_interval)
    
    async def _monitor_stuck_tasks(self) -> None:
        """Monitor for stuck queued tasks and trigger retries"""
        check_interval = 5.0  # Check every 5 seconds
        stuck_threshold = timedelta(seconds=10)  # Consider task stuck after 10 seconds
        
        while self._running:
            try:
                # Get all queued tasks from persistence
                result = await self.persistence.list_tasks(status=TaskStatus.QUEUED)
                if isinstance(result, dict):
                    queued_tasks = result.get('tasks', [])
                else:
                    queued_tasks = result if isinstance(result, list) else []
                
                now = datetime.utcnow()
                
                for task in queued_tasks:
                    # Check if task has been queued for too long
                    if task.created_at:
                        time_in_queue = now - task.created_at
                        if time_in_queue > stuck_threshold:
                            # Check if task has already exceeded max retry attempts
                            retry_count = task.metadata.get('retry_count', 0) if task.metadata else 0
                            max_attempts = task.retry_config.max_attempts if task.retry_config else 3
                            
                            if retry_count >= max_attempts:
                                # Task has exceeded max retries - mark it as failed instead of re-enqueueing
                                logger.warning(f"Task {task.id} stuck in queue with max retries ({retry_count}/{max_attempts}) reached, marking as FAILED")
                                
                                task.status = TaskStatus.FAILED
                                task.completed_at = datetime.utcnow()
                                task.error_message = f"Max retry attempts ({max_attempts}) reached - task stuck in queue"
                                
                                if not task.metadata:
                                    task.metadata = {}
                                task.metadata['final_failure'] = True
                                task.metadata['max_retries_reached'] = True
                                task.metadata['stuck_in_queue'] = True
                                
                                # Save to persistence
                                await self.persistence.save_task(task)
                                
                                # Remove from queue
                                await self.queue_manager.mark_task_failed(task.id)
                            else:
                                logger.info(f"Task {task.id} has been queued for {time_in_queue.total_seconds():.1f}s, re-enqueueing")
                                
                                # Re-enqueue the task to trigger processing
                                await self.queue_manager.enqueue_task(task)
                
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                logger.error(f"Error in stuck task monitor: {e}")
                await asyncio.sleep(check_interval)
    
    async def schedule_retry(self, task: Task, error_message: Optional[str] = None) -> bool:
        """
        Schedule a failed task for retry using persistence backend
        
        Args:
            task: Failed task to retry
            error_message: Error message from the failure
            
        Returns:
            True if retry was scheduled, False if max attempts reached or error not retryable
        """
        if not task.retry_config:
            logger.debug(f"Task {task.id} cannot be retried (no retry config)")
            return False
        
        # Check if the error is retryable
        if error_message:
            # Most errors from providers are retryable except INVALID_PARAMS
            if "INVALID_PARAMS" in error_message or "Invalid parameter" in error_message:
                logger.debug(f"Task {task.id} cannot be retried (non-retryable error: {error_message})")
                return False
            
            # Don't retry resource exhausted errors immediately
            if "RESOURCE_EXHAUSTED" in error_message:
                logger.debug(f"Task {task.id} failed due to resource exhaustion, will retry with delay")
        
        # Get current retry count from task metadata
        retry_count = task.metadata.get('retry_count', 0) if task.metadata else 0
        max_attempts = task.retry_config.max_attempts
        
        if retry_count >= max_attempts:
            logger.info(f"Task {task.id} has reached max retry attempts ({retry_count}/{max_attempts})")
            
            # Mark task as permanently failed
            async with self._lock:
                # Get fresh task from persistence to avoid conflicts
                fresh_task = await self.persistence.get_task(task.id)
                if fresh_task:
                    fresh_task.status = TaskStatus.FAILED
                    fresh_task.completed_at = datetime.utcnow()
                    fresh_task.error_message = f"Max retry attempts ({max_attempts}) reached. Last error: {error_message}"
                    
                    # Update metadata with final failure info
                    if not fresh_task.metadata:
                        fresh_task.metadata = {}
                    fresh_task.metadata['final_failure'] = True
                    fresh_task.metadata['max_retries_reached'] = True
                    fresh_task.metadata['total_attempts'] = retry_count
                    fresh_task.metadata['last_error'] = error_message
                    
                    # Save to persistence
                    await self.persistence.save_task(fresh_task)
                    
                    # Also update the passed task object
                    task.status = TaskStatus.FAILED
                    task.completed_at = fresh_task.completed_at
                    task.error_message = fresh_task.error_message
                    task.metadata = fresh_task.metadata
                    
                    logger.info(f"Task {task.id} marked as FAILED after {retry_count} retry attempts")
                    
                    # Remove the task from the queue since it's permanently failed
                    await self.queue_manager.mark_task_failed(task.id)
            
            return False
        
        # Calculate retry delay
        retry_delay = self._calculate_retry_delay(task, retry_count)
        retry_at = datetime.utcnow() + retry_delay
        
        async with self._lock:
            # Update task metadata with retry information
            if not task.metadata:
                task.metadata = {}
            
            task.metadata['retry_count'] = retry_count + 1
            task.metadata['retry_at'] = retry_at.isoformat()
            task.metadata['last_error'] = error_message
            
            # Update task status for retry
            task.error_message = error_message
            task.status = TaskStatus.RETRY_PENDING
            
            # Save task state to persistence
            await self.persistence.save_task(task)
            
            # Use EventScheduler if available for additional scheduling
            if self.scheduler:
                await self.scheduler.schedule_task_retry(
                    task_id=task.id,
                    retry_delay=retry_delay,
                    attempt_count=retry_count + 1,
                    error_message=error_message or "Unknown error"
                )
        
        logger.info(f"Scheduled retry for task {task.id} (attempt {retry_count + 1}/{max_attempts}) in {retry_delay.total_seconds():.1f}s")
        return True
    
    def _calculate_retry_delay(self, task: Task, attempt_count: int) -> timedelta:
        """Calculate retry delay based on backoff strategy"""
        if not task.retry_config:
            return timedelta(seconds=1)
        
        config = task.retry_config
        # Increment attempt for calculation (0-based to 1-based)
        attempt = attempt_count + 1
        
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
            
            # Save updated task
            await self.persistence.save_task(task)
            
            # Re-queue the task
            await self.queue_manager.enqueue_task(task)
            
            retry_count = task.metadata.get('retry_count', 0) if task.metadata else 0
            logger.info(f"Re-queued task {task_id} for retry (attempt {retry_count})")
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
            # Get task from persistence
            task = await self.persistence.get_task(task_id)
            if not task:
                return False
            
            if task.status == TaskStatus.RETRY_PENDING:
                # Update task status to failed
                task.status = TaskStatus.FAILED
                await self.persistence.save_task(task)
                
                logger.info(f"Cancelled retry for task {task_id}")
                return True
        
        return False
    
    async def get_retry_stats(self) -> Dict[str, int]:
        """Get retry statistics from persistence"""
        async with self._lock:
            # Get all retry-pending tasks
            result = await self.persistence.list_tasks(status=TaskStatus.RETRY_PENDING)
            if isinstance(result, dict):
                retry_tasks = result.get('tasks', [])
            else:
                retry_tasks = result if isinstance(result, list) else []
            
            pending_retries = len(retry_tasks)
            
            # Count tasks by retry attempt
            attempt_counts = {}
            for task in retry_tasks:
                if task.metadata and 'retry_count' in task.metadata:
                    attempt = task.metadata['retry_count']
                    attempt_counts[f"attempt_{attempt}"] = attempt_counts.get(f"attempt_{attempt}", 0) + 1
        
        return {
            "pending_retries": pending_retries,
            **attempt_counts
        }
    
    async def get_pending_retries(self) -> List[Dict[str, any]]:
        """Get list of pending retry tasks with their retry times"""
        async with self._lock:
            # Get all retry-pending tasks from persistence
            result = await self.persistence.list_tasks(status=TaskStatus.RETRY_PENDING)
            if isinstance(result, dict):
                retry_tasks = result.get('tasks', [])
            else:
                retry_tasks = result if isinstance(result, list) else []
            
            retries = []
            for task in retry_tasks:
                if task.metadata:
                    retries.append({
                        "task_id": task.id,
                        "task_name": task.name,
                        "attempt": task.metadata.get('retry_count', 0),
                        "max_attempts": task.retry_config.max_attempts if task.retry_config else 3,
                        "retry_at": task.metadata.get('retry_at', ''),
                        "error_message": task.error_message or task.metadata.get('last_error', '')
                    })
            
            return sorted(retries, key=lambda x: x["retry_at"])
    
    async def cleanup_old_retries(self, cutoff_date: datetime) -> int:
        """Remove old retry tasks that are past their cutoff"""
        async with self._lock:
            # Get all retry-pending tasks
            result = await self.persistence.list_tasks(status=TaskStatus.RETRY_PENDING)
            if isinstance(result, dict):
                retry_tasks = result.get('tasks', [])
            else:
                retry_tasks = result if isinstance(result, list) else []
            
            old_count = 0
            for task in retry_tasks:
                if task.metadata and 'retry_at' in task.metadata:
                    retry_at = datetime.fromisoformat(task.metadata['retry_at'])
                    if retry_at < cutoff_date:
                        # Mark as failed
                        task.status = TaskStatus.FAILED
                        await self.persistence.save_task(task)
                        old_count += 1
        
        return old_count
    
    # Methods needed by ExecutionEngine for retry tracking
    async def increment_retry_count(self, task_id: str) -> int:
        """Increment retry count for a task using persistence backend"""
        # Get task from persistence
        task = await self.persistence.get_task(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found for retry count increment")
            return 1
        
        # Get current attempt from metadata
        current_attempt = 1
        if task.metadata and 'execution_count' in task.metadata:
            current_attempt = task.metadata['execution_count'] + 1
        
        # Update metadata
        if not task.metadata:
            task.metadata = {}
        task.metadata['execution_count'] = current_attempt
        
        # Save to persistence
        await self.persistence.save_task(task)
        
        logger.debug(f"Incremented execution count for task {task_id} to {current_attempt}")
        return current_attempt
    
    async def get_task_retry_info(self, task_id: str) -> Dict[str, int]:
        """Get retry information for a task from persistence"""
        # Get task from persistence
        task = await self.persistence.get_task(task_id)
        if not task:
            return {"count": 0, "task_id": task_id}
        
        # Get retry count from metadata
        retry_count = 0
        if task.metadata:
            retry_count = task.metadata.get('retry_count', 0)
        
        return {"count": retry_count, "task_id": task_id}