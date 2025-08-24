"""
Enhanced Memory Persistence Adapter with Event-Driven Architecture

Extends the base in-memory adapter with full event support for real-time coordination.
"""

import logging
import asyncio
import uuid
from typing import Dict, List, Optional, Any, Callable, Set
from datetime import datetime
from collections import defaultdict

from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.core.models import Task, TaskStatus, Workflow, WorkflowStatus, TaskResult
from gleitzeit.core.events import (
    GleitzeitEvent, EventType, EventSeverity,
    create_task_started_event, create_task_completed_event,
    create_task_failed_event, create_workflow_completed_event
)

logger = logging.getLogger(__name__)


class UnifiedMemoryEventsAdapter(UnifiedInMemoryAdapter):
    """
    In-memory adapter with full event-driven architecture support.
    
    Features:
    - Event publishing via in-memory pub/sub
    - Event subscription and handling
    - Atomic workflow completion checking
    - Simple in-memory locking for coordination
    """
    
    def __init__(self, *args, event_bus=None, **kwargs):
        """
        Initialize with event support.
        
        Args:
            event_bus: Optional EventBus for local event distribution
            *args, **kwargs: Passed to parent UnifiedInMemoryAdapter
        """
        super().__init__()
        self.event_bus = event_bus
        
        # In-memory pub/sub system
        self._event_channels: Dict[str, List[Callable]] = defaultdict(list)
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._subscription_task = None
        self._event_handlers: Dict[str, List[Callable]] = {}
        
        # Locking mechanism
        self._locks: Dict[str, str] = {}  # resource_id -> lock_token
        
        logger.info("Initialized UnifiedMemoryEventsAdapter with event support")
    
    # =========================================================================
    # Event Publishing
    # =========================================================================
    
    async def emit_event(self, event: GleitzeitEvent) -> None:
        """
        Emit an event via in-memory pub/sub and local event bus.
        
        Args:
            event: The event to emit
        """
        if not self._initialized:
            logger.warning("Memory adapter not initialized, cannot emit event")
            return
        
        try:
            # Get the string representation of event type
            if hasattr(event.event_type, 'value'):
                event_type_str = event.event_type.value
            elif isinstance(event.event_type, str):
                event_type_str = event.event_type
            else:
                event_type_str = str(event.event_type).replace('EventType.', '')
            
            # Prepare event data
            event_data = {
                'event_type': event_type_str,
                'severity': str(event.severity.value if hasattr(event.severity, 'value') else event.severity),
                'data': event.data,
                'source': event.source,
                'tags': event.tags,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Put event in queue for async processing
            await self._event_queue.put(event_data)
            
            logger.debug(f"Published {event_data['event_type']} event to memory queue")
            
            # Also emit to local event bus if available
            if self.event_bus:
                await self.event_bus.emit(event)
                
        except Exception as e:
            logger.error(f"Failed to emit event {event.event_type}: {e}")
    
    # =========================================================================
    # Enhanced Task Operations with Events
    # =========================================================================
    
    async def save_task(self, task: Task) -> None:
        """Save task and emit appropriate events"""
        # Get previous status for event decisions
        existing_task = self.tasks.get(task.id)
        old_status = existing_task.status if existing_task else None
        
        # Save using parent method
        await super().save_task(task)
        
        # Emit events based on status changes
        if old_status != task.status:
            if task.status == TaskStatus.EXECUTING:
                event = create_task_started_event(
                    task_id=task.id,
                    task_name=task.name,
                    protocol=task.protocol,
                    method=task.method,
                    workflow_id=task.workflow_id,
                    source="memory_persistence"
                )
                await self.emit_event(event)
                
            elif task.status == TaskStatus.COMPLETED:
                event = create_task_completed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    duration=(task.completed_at - task.started_at).total_seconds() if task.started_at and task.completed_at else 0,
                    source="memory_persistence"
                )
                await self.emit_event(event)
                
            elif task.status == TaskStatus.FAILED:
                event = create_task_failed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    error=task.error_message,
                    source="memory_persistence"
                )
                await self.emit_event(event)
    
    async def save_task_result(self, result: TaskResult) -> None:
        """Save task result and emit completion event"""
        # Save using parent method
        await super().save_task_result(result)
        
        # Emit task completed event with result
        event = GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            severity=EventSeverity.INFO,
            data={
                'task_id': result.task_id,
                'workflow_id': result.workflow_id,
                'status': str(result.status.value if hasattr(result.status, 'value') else result.status),
                'result': result.result,
                'error': result.error,
                'has_result': True
            },
            source="memory_persistence",
            tags={'component': 'persistence', 'with_result': 'true'}
        )
        await self.emit_event(event)
    
    # =========================================================================
    # Atomic Workflow Completion
    # =========================================================================
    
    async def check_and_complete_workflow(self, workflow_id: str) -> bool:
        """
        Atomically check if workflow is complete and emit event if so.
        
        Uses simple locking for atomic operation to prevent race conditions.
        
        Args:
            workflow_id: The workflow to check
            
        Returns:
            True if workflow was completed, False otherwise
        """
        if not self._initialized:
            return False
        
        # Simple lock acquisition
        lock_token = str(uuid.uuid4())
        lock_key = f"workflow_completion_{workflow_id}"
        
        # Try to acquire lock
        if lock_key in self._locks:
            logger.debug(f"Workflow {workflow_id} completion check already in progress")
            return False
        
        self._locks[lock_key] = lock_token
        
        try:
            # Get workflow
            workflow = self.workflows.get(workflow_id)
            if not workflow:
                return False
            
            # Check if already completed
            if workflow.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                return False
            
            # Get all tasks for this workflow
            workflow_tasks = [task for task in self.tasks.values() 
                            if task.workflow_id == workflow_id]
            
            if not workflow_tasks:
                return False
            
            # Check status of all tasks
            completed_count = 0
            failed_count = 0
            pending_count = 0
            task_results = {}
            
            for task in workflow_tasks:
                if task.status == TaskStatus.COMPLETED:
                    completed_count += 1
                    # Get task result if available
                    task_result = self.task_results.get(task.id)
                    if task_result:
                        task_results[task.id] = {
                            'status': 'completed',
                            'result': task_result.result,
                            'error': task_result.error
                        }
                elif task.status == TaskStatus.FAILED:
                    failed_count += 1
                    task_result = self.task_results.get(task.id)
                    if task_result:
                        task_results[task.id] = {
                            'status': 'failed',
                            'result': task_result.result,
                            'error': task_result.error
                        }
                elif task.status not in [TaskStatus.CANCELLED]:
                    pending_count += 1
            
            # Check if workflow is complete
            if pending_count > 0:
                return False  # Still have pending tasks
            
            # Workflow is complete - update status
            final_status = WorkflowStatus.COMPLETED if failed_count == 0 else WorkflowStatus.FAILED
            
            # Update workflow status atomically
            workflow.status = final_status
            workflow.completed_at = datetime.utcnow()
            if not hasattr(workflow, 'completed_tasks'):
                workflow.completed_tasks = []
            if not hasattr(workflow, 'failed_tasks'):
                workflow.failed_tasks = []
            
            # Update task lists
            workflow.completed_tasks = [t.id for t in workflow_tasks if t.status == TaskStatus.COMPLETED]
            workflow.failed_tasks = [t.id for t in workflow_tasks if t.status == TaskStatus.FAILED]
            
            # Save updated workflow
            self.workflows[workflow_id] = workflow
            
            # Emit workflow completed event
            event = GleitzeitEvent(
                event_type=EventType.WORKFLOW_COMPLETED,
                severity=EventSeverity.INFO,
                data={
                    'workflow_id': workflow_id,
                    'workflow_name': workflow.name,
                    'status': final_status.value if hasattr(final_status, 'value') else str(final_status),
                    'completed_tasks': completed_count,
                    'failed_tasks': failed_count,
                    'total_tasks': len(workflow_tasks),
                    'task_results': task_results,
                    'duration': (workflow.completed_at - workflow.created_at).total_seconds() if workflow.created_at else 0
                },
                source="memory_persistence",
                tags={'component': 'persistence', 'atomic': 'true'}
            )
            await self.emit_event(event)
            
            logger.info(f"Workflow {workflow_id} completed with status {final_status}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to check workflow completion for {workflow_id}: {e}")
            return False
        finally:
            # Release lock
            if self._locks.get(lock_key) == lock_token:
                del self._locks[lock_key]
    
    # =========================================================================
    # Event Subscription and Handling
    # =========================================================================
    
    async def start_event_subscription(self, event_types: List[str] = None) -> None:
        """
        Start processing events from the in-memory queue.
        
        Args:
            event_types: List of event types to process (None = all)
        """
        if not self._initialized:
            await self.initialize()
        
        if self._subscription_task and not self._subscription_task.done():
            logger.warning("Event subscription already running")
            return
        
        # Default to all event types
        if event_types is None:
            event_types = [
                'TASK_STARTED', 'TASK_COMPLETED', 'TASK_FAILED',
                'WORKFLOW_STARTED', 'WORKFLOW_COMPLETED', 'WORKFLOW_FAILED'
            ]
        
        # Start subscription task
        self._subscription_task = asyncio.create_task(
            self._event_subscription_loop(event_types)
        )
        logger.info(f"Started event subscription for {len(event_types)} event types")
    
    async def _event_subscription_loop(self, event_types: List[str]) -> None:
        """
        Main event subscription loop for in-memory events.
        
        Args:
            event_types: Event types to process
        """
        try:
            logger.info(f"Started in-memory event processing loop")
            
            while True:
                try:
                    # Get event from queue with timeout
                    event_data = await asyncio.wait_for(
                        self._event_queue.get(), 
                        timeout=1.0
                    )
                    
                    event_type = event_data.get('event_type')
                    
                    # Check if we should process this event type
                    if event_type not in event_types:
                        continue
                    
                    # Call registered handlers
                    if event_type in self._event_handlers:
                        for handler in self._event_handlers[event_type]:
                            try:
                                await handler(event_data)
                            except Exception as e:
                                logger.error(f"Event handler error for {event_type}: {e}")
                                
                except asyncio.TimeoutError:
                    # No events in queue, continue
                    continue
                except Exception as e:
                    logger.error(f"Error processing event: {e}")
                    
        except asyncio.CancelledError:
            logger.info("Event subscription cancelled")
            raise
        except Exception as e:
            logger.error(f"Event subscription loop error: {e}")
    
    def register_event_handler(self, event_type: str, handler: Callable) -> None:
        """
        Register a handler for an event type.
        
        Args:
            event_type: The event type to handle
            handler: Async function to handle the event
        """
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)
        logger.debug(f"Registered handler for {event_type}")
    
    async def stop_event_subscription(self) -> None:
        """Stop event subscription"""
        if self._subscription_task and not self._subscription_task.done():
            self._subscription_task.cancel()
            try:
                await self._subscription_task
            except asyncio.CancelledError:
                pass
            self._subscription_task = None
            logger.info("Stopped event subscription")
    
    # =========================================================================
    # Simple Locking
    # =========================================================================
    
    async def acquire_lock(self, resource_id: str, timeout_ms: int = 5000) -> Optional[str]:
        """
        Acquire a simple in-memory lock.
        
        Args:
            resource_id: Resource to lock
            timeout_ms: Lock timeout in milliseconds (not implemented for simplicity)
            
        Returns:
            Lock token if acquired, None otherwise
        """
        if not self._initialized:
            return None
        
        lock_key = f"lock_{resource_id}"
        
        # Check if already locked
        if lock_key in self._locks:
            logger.debug(f"Failed to acquire lock for {resource_id} (already locked)")
            return None
        
        # Acquire lock
        lock_token = str(uuid.uuid4())
        self._locks[lock_key] = lock_token
        
        logger.debug(f"Acquired lock for {resource_id}")
        return lock_token
    
    async def release_lock(self, resource_id: str, lock_token: str) -> bool:
        """
        Release an in-memory lock if we own it.
        
        Args:
            resource_id: Resource to unlock
            lock_token: Token received when lock was acquired
            
        Returns:
            True if lock was released, False otherwise
        """
        if not self._initialized:
            return False
        
        lock_key = f"lock_{resource_id}"
        
        # Check if we own the lock
        if self._locks.get(lock_key) == lock_token:
            del self._locks[lock_key]
            logger.debug(f"Released lock for {resource_id}")
            return True
        else:
            logger.debug(f"Failed to release lock for {resource_id} (not owner)")
            return False
    
    # =========================================================================
    # Lifecycle Override
    # =========================================================================
    
    async def shutdown(self) -> None:
        """Shutdown with event cleanup"""
        # Stop event subscription
        await self.stop_event_subscription()
        
        # Clear event queue
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except:
                break
        
        # Clear locks
        self._locks.clear()
        
        # Call parent shutdown if it exists
        if hasattr(super(), 'shutdown'):
            await super().shutdown()
        
        logger.info("UnifiedMemoryEventsAdapter shutdown complete")