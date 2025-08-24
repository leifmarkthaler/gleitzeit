"""
Event-driven SQLAlchemy persistence adapter.
Follows the same principles as the Redis event adapter for consistency.
"""

import logging
from typing import Optional, Any, Dict, List
from datetime import datetime
import asyncio

from .unified_sqlalchemy import UnifiedSQLAlchemyAdapter
from ..core.models import Task, TaskResult, TaskStatus, WorkflowStatus, Workflow
from ..core.events import (
    EventType, EventSeverity, GleitzeitEvent,
    create_task_started_event, create_task_completed_event,
    create_task_failed_event, create_workflow_started_event,
    create_workflow_completed_event
)

logger = logging.getLogger(__name__)


class UnifiedSQLAlchemyEventsAdapter(UnifiedSQLAlchemyAdapter):
    """
    Event-driven SQLAlchemy adapter that follows the same principles as Redis adapter.
    Emits events on state changes and handles distributed locking.
    """
    
    def __init__(self, *args, event_bus=None, **kwargs):
        """Initialize with optional event bus"""
        super().__init__(*args, **kwargs)
        self.event_bus = event_bus
        self._event_subscriptions = {}
        self._lock_tokens = {}  # Track our locks
        logger.info("Initialized event-driven SQLAlchemy adapter with event bus support")
    
    # =========================================================================
    # Event Management
    # =========================================================================
    
    async def emit_event(self, event: GleitzeitEvent) -> None:
        """Emit event via event bus if available"""
        if self.event_bus:
            try:
                await self.event_bus.emit(event)
                logger.debug(f"Emitted {event.event_type.value} event for {event.data.get('task_id', event.data.get('workflow_id'))}")
            except Exception as e:
                logger.error(f"Failed to emit event {event.event_type}: {e}")
    
    async def subscribe_to_event(self, event_type: EventType, callback: callable) -> str:
        """Subscribe to events (for compatibility with Redis adapter)"""
        subscription_id = f"sql_{event_type.value}_{id(callback)}"
        
        if self.event_bus:
            # Register with event bus
            self.event_bus.register(event_type, callback)
            self._event_subscriptions[subscription_id] = (event_type, callback)
            logger.debug(f"Subscribed to {event_type.value} events")
        
        return subscription_id
    
    async def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from events"""
        if subscription_id in self._event_subscriptions:
            event_type, callback = self._event_subscriptions.pop(subscription_id)
            if self.event_bus:
                self.event_bus.unregister(event_type, callback)
            logger.debug(f"Unsubscribed from {event_type.value} events")
    
    # =========================================================================
    # Enhanced Task Operations with Events
    # =========================================================================
    
    async def save_task(self, task: Task) -> None:
        """Save task and emit appropriate events based on status changes"""
        # Get previous status for event decisions
        existing_task = await self.get_task(task.id)
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
                    source="sql_persistence"
                )
                await self.emit_event(event)
                
            elif task.status == TaskStatus.COMPLETED:
                # Calculate duration if possible
                duration = 0
                if task.started_at and task.completed_at:
                    duration = (task.completed_at - task.started_at).total_seconds()
                
                event = create_task_completed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    duration=duration,
                    result_size=0,  # We don't have result size here
                    source="sql_persistence"
                )
                await self.emit_event(event)
                
            elif task.status == TaskStatus.FAILED:
                event = create_task_failed_event(
                    task_id=task.id,
                    workflow_id=task.workflow_id,
                    error_message=task.error_message or "Task failed",
                    source="sql_persistence"
                )
                await self.emit_event(event)
    
    async def save_task_result(self, result: TaskResult) -> None:
        """Save task result and emit completion event with result data"""
        # Save using parent method
        await super().save_task_result(result)
        
        # Emit task completed event with result data
        event = GleitzeitEvent(
            event_type=EventType.TASK_COMPLETED,
            severity=EventSeverity.INFO,
            data={
                'task_id': result.task_id,
                'workflow_id': result.workflow_id,
                'status': str(result.status.value if hasattr(result.status, 'value') else result.status),
                'result': result.result,
                'error': result.error,
                'has_result': True,
                'duration_seconds': result.duration_seconds
            },
            source="sql_persistence",
            tags={'type': 'task', 'action': 'completed', 'has_result': 'true'}
        )
        await self.emit_event(event)
    
    # =========================================================================
    # Enhanced Workflow Operations with Events
    # =========================================================================
    
    async def save_workflow(self, workflow: Workflow) -> None:
        """Save workflow and emit appropriate events"""
        # Get previous status for event decisions
        existing_workflow = await self.get_workflow(workflow.id)
        old_status = existing_workflow.status if existing_workflow else None
        
        # Save using parent method
        await super().save_workflow(workflow)
        
        # Emit events based on status changes
        if old_status != workflow.status:
            if workflow.status == WorkflowStatus.RUNNING and old_status != WorkflowStatus.RUNNING:
                event = create_workflow_started_event(
                    workflow_id=workflow.id,
                    workflow_name=workflow.name,
                    total_tasks=len(workflow.tasks),
                    execution_levels=1,  # We don't track levels in SQL
                    source="sql_persistence"
                )
                await self.emit_event(event)
                
            elif workflow.status == WorkflowStatus.COMPLETED:
                duration = 0
                if workflow.started_at and workflow.completed_at:
                    duration = (workflow.completed_at - workflow.started_at).total_seconds()
                
                event = create_workflow_completed_event(
                    workflow_id=workflow.id,
                    workflow_name=workflow.name,
                    total_tasks=len(workflow.tasks),
                    completed_tasks=len(workflow.completed_tasks),
                    failed_tasks=len(workflow.failed_tasks),
                    duration=duration,
                    source="sql_persistence"
                )
                await self.emit_event(event)
    
    # =========================================================================
    # Distributed Locking (simplified for SQL)
    # =========================================================================
    
    async def acquire_lock(self, resource_id: str, token: str, ttl_seconds: int = 30) -> bool:
        """
        Acquire a distributed lock (simplified for SQL).
        In production, this would use database-level locking.
        """
        lock_key = f"lock:{resource_id}"
        
        # For SQL, we'll use a simple in-memory lock tracking
        # In production, this should use SELECT FOR UPDATE or similar
        if lock_key not in self._lock_tokens:
            self._lock_tokens[lock_key] = {
                'token': token,
                'expires_at': datetime.utcnow().timestamp() + ttl_seconds
            }
            logger.debug(f"Acquired lock for {resource_id}")
            return True
        
        # Check if lock expired
        lock_info = self._lock_tokens[lock_key]
        if datetime.utcnow().timestamp() > lock_info['expires_at']:
            # Lock expired, acquire it
            self._lock_tokens[lock_key] = {
                'token': token,
                'expires_at': datetime.utcnow().timestamp() + ttl_seconds
            }
            logger.debug(f"Acquired expired lock for {resource_id}")
            return True
        
        # Lock held by someone else
        return False
    
    async def release_lock(self, resource_id: str, token: str) -> bool:
        """Release a distributed lock"""
        lock_key = f"lock:{resource_id}"
        
        if lock_key in self._lock_tokens:
            lock_info = self._lock_tokens[lock_key]
            if lock_info['token'] == token:
                del self._lock_tokens[lock_key]
                logger.debug(f"Released lock for {resource_id}")
                return True
        
        return False
    
    async def extend_lock(self, resource_id: str, token: str, ttl_seconds: int = 30) -> bool:
        """Extend a distributed lock"""
        lock_key = f"lock:{resource_id}"
        
        if lock_key in self._lock_tokens:
            lock_info = self._lock_tokens[lock_key]
            if lock_info['token'] == token:
                lock_info['expires_at'] = datetime.utcnow().timestamp() + ttl_seconds
                logger.debug(f"Extended lock for {resource_id}")
                return True
        
        return False
    
    # =========================================================================
    # Atomic Workflow Completion (similar to Redis)
    # =========================================================================
    
    async def check_and_complete_workflow_atomic(self, workflow_id: str) -> bool:
        """
        Atomically check and complete a workflow if all tasks are done.
        Returns True if workflow was completed, False otherwise.
        """
        # Acquire lock for this workflow
        lock_token = f"complete_{workflow_id}_{datetime.utcnow().timestamp()}"
        
        if not await self.acquire_lock(f"workflow:{workflow_id}", lock_token, ttl_seconds=10):
            logger.debug(f"Could not acquire lock for workflow {workflow_id}")
            return False
        
        try:
            # Get workflow and all its tasks
            workflow = await self.get_workflow(workflow_id)
            if not workflow:
                return False
            
            # Already completed?
            if workflow.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                return False
            
            # Get all tasks for this workflow
            tasks = await self.get_workflow_tasks(workflow_id)
            if not tasks:
                return False
            
            # Check task statuses
            completed_count = 0
            failed_count = 0
            pending_count = 0
            
            for task in tasks:
                if task.status == TaskStatus.COMPLETED:
                    completed_count += 1
                elif task.status == TaskStatus.FAILED:
                    failed_count += 1
                elif task.status not in [TaskStatus.CANCELLED]:
                    pending_count += 1
            
            # Not ready to complete if still have pending tasks
            if pending_count > 0:
                return False
            
            # Determine final status
            if failed_count > 0:
                workflow.status = WorkflowStatus.FAILED
            else:
                workflow.status = WorkflowStatus.COMPLETED
            
            workflow.completed_at = datetime.utcnow()
            workflow.completed_tasks = [t.id for t in tasks if t.status == TaskStatus.COMPLETED]
            workflow.failed_tasks = [t.id for t in tasks if t.status == TaskStatus.FAILED]
            
            # Save the updated workflow
            await self.save_workflow(workflow)
            
            logger.info(f"Workflow {workflow_id} marked as {workflow.status.value}")
            return True
            
        finally:
            # Always release lock
            await self.release_lock(f"workflow:{workflow_id}", lock_token)
    
    # =========================================================================
    # Cleanup
    # =========================================================================
    
    async def shutdown(self) -> None:
        """Clean shutdown with event cleanup"""
        # Unsubscribe from all events
        for subscription_id in list(self._event_subscriptions.keys()):
            await self.unsubscribe(subscription_id)
        
        # Clear locks
        self._lock_tokens.clear()
        
        # Call parent shutdown
        await super().shutdown()
        
        logger.info("Event-driven SQL adapter shut down cleanly")