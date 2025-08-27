"""
Event-Driven Retry Manager for Gleitzeit

This retry manager responds to task failure events and schedules retries
according to the centralized event architecture where ExecutionEngine
is the sole source of task events.
"""

import asyncio
import logging
import random
from typing import Optional, Any, Dict
from datetime import datetime, timedelta
from enum import Enum

from gleitzeit.core.models import Task, TaskStatus, RetryConfig
from gleitzeit.core.events import EventType, GleitzeitEvent, create_custom_event
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.errors import is_retryable_error

logger = logging.getLogger(__name__)


class BackoffStrategy(str, Enum):
    """Retry backoff strategies"""
    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


class EventDrivenRetryManager:
    """
    Event-driven retry manager that responds to task failure events
    
    This manager:
    - Listens to TASK_FAILED events to schedule retries
    - Calculates backoff delays based on retry configuration
    - Emits RETRY_SCHEDULED events when retries are scheduled
    - Emits TASK_PERMANENTLY_FAILED events when max retries exceeded
    - Uses scheduler for delayed retry execution
    """
    
    def __init__(self, 
                 persistence: PersistenceBackend,
                 scheduler: Optional['EventScheduler'],
                 event_bus: Any):
        """Initialize with required event bus"""
        if not event_bus:
            raise ValueError("EventDrivenRetryManager requires an event bus")
        
        self.persistence = persistence
        self.scheduler = scheduler
        self.event_bus = event_bus
        self._monitoring_task = None
        self._shutdown_event = asyncio.Event()
        
        self._register_event_handlers()
        
        logger.info("Initialized event-driven RetryManager with persistence backend")
    
    def _register_event_handlers(self):
        """Register for events we care about"""
        # Task failure events
        self.event_bus.register(EventType.TASK_FAILED, self._on_task_failed)
        
        logger.debug("Registered retry manager event handlers")
    
    async def _on_task_failed(self, event: GleitzeitEvent):
        """Handle task failure - decide if task should be retried"""
        task_id = event.data.get('task_id')
        error_message = event.data.get('error_message', 'Unknown error')
        error_type = event.data.get('error_type')
        is_retryable = event.data.get('is_retryable', True)
        is_permanent = event.data.get('is_permanent', False)
        attempt_number = event.data.get('attempt_number', 1)
        
        logger.debug(f"Processing TASK_FAILED event for {task_id}, attempt {attempt_number}, permanent={is_permanent}")
        
        # Ignore permanent failure events (these are emitted by us)
        if is_permanent:
            logger.debug(f"Ignoring permanent failure event for {task_id}")
            return
        
        # Check if error is retryable
        if not is_retryable:
            logger.info(f"Task {task_id} failed with non-retryable error: {error_message}")
            await self._emit_permanent_failure(task_id, "Non-retryable error")
            return
        
        # Get task from persistence
        task = await self.persistence.get_task(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found in persistence")
            return
        
        # Check retry configuration
        retry_config = task.retry_config
        if not retry_config:
            logger.info(f"Task {task_id} has no retry configuration")
            await self._emit_permanent_failure(task_id, "No retry configuration")
            return
        
        # Check if we've exceeded max attempts
        if attempt_number >= retry_config.max_attempts:
            logger.info(f"Task {task_id} exceeded max retry attempts ({retry_config.max_attempts})")
            
            # Mark task as permanently failed
            task.status = TaskStatus.FAILED
            task.metadata = task.metadata or {}
            task.metadata['max_retries_reached'] = True
            task.metadata['final_error'] = error_message
            await self.persistence.save_task(task)
            
            await self._emit_permanent_failure(task_id, "Max retry attempts exceeded")
            return
        
        # Calculate retry delay
        delay = self._calculate_backoff(
            attempt_number,
            retry_config.backoff_strategy,
            retry_config.base_delay,
            retry_config.max_delay,
            retry_config.jitter
        )
        
        retry_at = datetime.utcnow() + timedelta(seconds=delay)
        
        # Update task for retry
        task.status = TaskStatus.RETRY_PENDING
        task.metadata = task.metadata or {}
        task.metadata['retry_attempt'] = attempt_number + 1
        task.metadata['retry_at'] = retry_at.isoformat()
        task.metadata['last_error'] = error_message
        await self.persistence.save_task(task)
        
        logger.info(f"Task {task_id} scheduled for retry #{attempt_number + 1} at {retry_at} (delay: {delay:.1f}s)")
        
        # Schedule the retry if we have a scheduler
        if self.scheduler and hasattr(self.scheduler, 'schedule_task_retry'):
            # Use the EventScheduler's task retry method
            from datetime import timedelta
            await self.scheduler.schedule_task_retry(
                task_id=task_id,
                retry_delay=timedelta(seconds=delay),
                attempt_count=attempt_number + 1,
                error_message=task.metadata.get('last_error', 'Unknown error') if task.metadata else 'Unknown error'
            )
        else:
            # Without scheduler or if method not available, use asyncio
            asyncio.create_task(self._delayed_retry(task_id, delay))
        
        # Emit retry scheduled event
        await self._emit_retry_scheduled(task_id, retry_at, attempt_number + 1)
    
    def _calculate_backoff(self, 
                          attempt: int, 
                          strategy: str,
                          base_delay: float,
                          max_delay: float = 300.0,
                          jitter: bool = True) -> float:
        """Calculate backoff delay based on strategy"""
        if strategy == BackoffStrategy.FIXED or strategy == "fixed":
            delay = base_delay
        elif strategy == BackoffStrategy.LINEAR or strategy == "linear":
            delay = base_delay * attempt
        elif strategy == BackoffStrategy.EXPONENTIAL or strategy == "exponential":
            delay = base_delay * (2 ** (attempt - 1))
        else:
            logger.warning(f"Unknown backoff strategy: {strategy}, using fixed")
            delay = base_delay
        
        # Cap at max delay
        delay = min(delay, max_delay)
        
        # Add jitter if enabled (±20% randomization)
        if jitter:
            jitter_amount = delay * 0.2
            delay = delay + random.uniform(-jitter_amount, jitter_amount)
        
        return max(0.1, delay)  # Minimum 100ms delay
    
    async def _delayed_retry(self, task_id: str, delay: float):
        """Simple delayed retry without scheduler"""
        await asyncio.sleep(delay)
        await self._trigger_retry(task_id)
    
    async def _trigger_retry(self, task_id: str):
        """Called when retry time arrives"""
        logger.debug(f"Triggering retry for task {task_id}")
        
        task = await self.persistence.get_task(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found for retry")
            return
        
        # Check if task is still in retry pending state
        if task.status != TaskStatus.RETRY_PENDING:
            logger.info(f"Task {task_id} no longer in retry pending state (status: {task.status})")
            return
        
        # Update status to QUEUED for re-execution
        task.status = TaskStatus.QUEUED
        await self.persistence.save_task(task)
        
        # Emit event to trigger re-execution
        await self._emit_task_ready_for_retry(task)
    
    async def _emit_retry_scheduled(self, task_id: str, retry_at: datetime, attempt_number: int):
        """Emit RETRY_SCHEDULED event"""
        if self.event_bus:
            event = create_custom_event(
                event_type=EventType.RETRY_SCHEDULED,
                data={
                    'task_id': task_id,
                    'retry_at': retry_at.isoformat(),
                    'attempt_number': attempt_number
                },
                source="retry_manager"
            )
            await self.event_bus.emit(event)
    
    async def _emit_task_ready_for_retry(self, task: Task):
        """Emit TASK_READY_FOR_RETRY event"""
        if self.event_bus:
            event = create_custom_event(
                event_type=EventType.TASK_READY_FOR_RETRY,
                data={
                    'task_id': task.id,
                    'workflow_id': task.workflow_id,
                    'attempt_number': task.metadata.get('retry_attempt', 1) if task.metadata else 1
                },
                source="retry_manager"
            )
            await self.event_bus.emit(event)
            logger.info(f"Emitted TASK_READY_FOR_RETRY event for {task.id}")
    
    async def _emit_permanent_failure(self, task_id: str, reason: str):
        """Emit event for permanent task failure"""
        if self.event_bus:
            # Create a custom event type if it doesn't exist
            event = create_custom_event(
                event_type=EventType.TASK_FAILED,  # Reuse TASK_FAILED with permanent flag
                data={
                    'task_id': task_id,
                    'reason': reason,
                    'is_permanent': True
                },
                source="retry_manager"
            )
            await self.event_bus.emit(event)
            logger.info(f"Task {task_id} permanently failed: {reason}")
    
    async def start_monitoring(self):
        """Start monitoring for retries that need to be triggered"""
        if self._monitoring_task:
            logger.warning("Retry monitoring already running")
            return
        
        self._shutdown_event.clear()
        self._monitoring_task = asyncio.create_task(self._monitor_retries())
        logger.info("RetryManager monitoring started")
    
    async def _monitor_retries(self):
        """Periodically check for retries that need to be triggered"""
        while not self._shutdown_event.is_set():
            try:
                # Check for any retry-pending tasks that are past their retry time
                # This is a backup mechanism in case scheduled retries fail
                
                # Get all tasks with RETRY_PENDING status
                # Note: This requires a method to query tasks by status
                # For now, we rely on the scheduler or asyncio delays
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in retry monitoring: {e}")
                await asyncio.sleep(1)
    
    async def stop_monitoring(self):
        """Stop the retry monitoring task"""
        if self._monitoring_task:
            self._shutdown_event.set()
            await self._monitoring_task
            self._monitoring_task = None
            logger.info("RetryManager monitoring stopped")
    
    # Public methods for backward compatibility
    
    async def start(self):
        """Start the retry manager (for API compatibility)"""
        # In event-driven mode, we just start monitoring
        await self.start_monitoring()
    
    async def stop(self):
        """Stop the retry manager (for API compatibility)"""
        await self.stop_monitoring()
    
    async def schedule_retry(self, task: Task, error_message: str) -> bool:
        """
        Schedule a retry for a failed task (backward compatibility)
        
        In the event-driven architecture, this is typically called
        indirectly via TASK_FAILED events.
        """
        # Create a synthetic event and process it
        event = GleitzeitEvent(
            event_type=EventType.TASK_FAILED,
            data={
                'task_id': task.id,
                'workflow_id': task.workflow_id,
                'error_message': error_message,
                'is_retryable': True,
                'attempt_number': task.metadata.get('retry_attempt', 1) if task.metadata else 1
            },
            source="manual"
        )
        
        await self._on_task_failed(event)
        
        # Check if retry was scheduled
        fresh_task = await self.persistence.get_task(task.id)
        return fresh_task and fresh_task.status == TaskStatus.RETRY_PENDING
    
    async def get_retry_count(self, task_id: str) -> int:
        """Get the current retry count for a task"""
        task = await self.persistence.get_task(task_id)
        if task and task.metadata:
            return task.metadata.get('retry_attempt', 0)
        return 0
    
    async def increment_retry_count(self, task_id: str) -> int:
        """Increment and return the retry count for a task"""
        task = await self.persistence.get_task(task_id)
        if task:
            task.metadata = task.metadata or {}
            current = task.metadata.get('retry_attempt', 0)
            task.metadata['retry_attempt'] = current + 1
            await self.persistence.save_task(task)
            return current + 1
        return 1
    
    async def get_task_retry_info(self, task_id: str) -> Dict[str, int]:
        """Get retry information for a task"""
        task = await self.persistence.get_task(task_id)
        if task and task.metadata:
            return {
                'current_attempt': task.metadata.get('retry_attempt', 0),
                'max_attempts': self.max_retries
            }
        return {
            'current_attempt': 0,
            'max_attempts': self.max_retries
        }