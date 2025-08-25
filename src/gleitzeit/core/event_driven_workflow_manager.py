"""
Event-Driven Workflow Manager for Gleitzeit

This workflow manager responds to workflow and task events to track
workflow state and emit workflow-level events according to the centralized
event architecture.
"""

import logging
from typing import Optional, Dict, Any, List, Set
from datetime import datetime

from gleitzeit.core.models import Workflow, WorkflowStatus, Task, TaskStatus
from gleitzeit.core.events import (
    EventType, 
    GleitzeitEvent,
    create_workflow_started_event,
    create_workflow_completed_event,
    create_workflow_failed_event,
    create_custom_event
)
from gleitzeit.persistence.base import PersistenceBackend

logger = logging.getLogger(__name__)


class EventDrivenWorkflowManager:
    """
    Event-driven workflow manager that tracks workflow state
    
    This manager:
    - Listens to WORKFLOW_SUBMITTED events to start tracking
    - Listens to TASK_STARTED/COMPLETED/FAILED events to update workflow progress
    - Emits WORKFLOW_STARTED when first task starts
    - Emits WORKFLOW_COMPLETED when all tasks complete
    - Emits WORKFLOW_FAILED when workflow fails
    - Tracks workflow metrics and progress
    """
    
    def __init__(self, persistence: PersistenceBackend, event_bus: Any):
        """Initialize with required event bus"""
        if not event_bus:
            raise ValueError("EventDrivenWorkflowManager requires an event bus")
        
        self.persistence = persistence
        self.event_bus = event_bus
        
        # Track workflows in progress to avoid duplicate processing
        self._processing_workflows: Set[str] = set()
        
        self._register_event_handlers()
        
        logger.info("Initialized EventDrivenWorkflowManager with event handlers")
    
    def _register_event_handlers(self):
        """Register for events we care about"""
        # Workflow events
        self.event_bus.register(EventType.WORKFLOW_SUBMITTED, self._on_workflow_submitted)
        
        # Task lifecycle events that affect workflow state
        self.event_bus.register(EventType.TASK_STARTED, self._on_task_started)
        self.event_bus.register(EventType.TASK_COMPLETED, self._on_task_completed)
        self.event_bus.register(EventType.TASK_FAILED, self._on_task_failed)
        
        logger.debug("Registered workflow manager event handlers")
    
    async def _on_workflow_submitted(self, event: GleitzeitEvent):
        """Handle workflow submission"""
        workflow_id = event.data.get('workflow_id')
        if not workflow_id:
            return
        
        logger.debug(f"Processing WORKFLOW_SUBMITTED event for {workflow_id}")
        
        # Get workflow from persistence
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            logger.warning(f"Workflow {workflow_id} not found in persistence")
            return
        
        # Update workflow status if needed
        if workflow.status == WorkflowStatus.PENDING:
            # Keep workflow as PENDING until first task starts
            # (We don't have a QUEUED status for workflows)
            workflow.metadata = workflow.metadata or {}
            workflow.metadata['submitted_at'] = datetime.utcnow().isoformat()
            await self.persistence.save_workflow(workflow)
            
            logger.info(f"Workflow {workflow_id} submission recorded")
    
    async def _on_task_started(self, event: GleitzeitEvent):
        """Handle task start - may trigger workflow start"""
        task_id = event.data.get('task_id')
        workflow_id = event.data.get('workflow_id')
        
        if not workflow_id:
            return
        
        # Prevent duplicate processing
        processing_key = f"{workflow_id}:start"
        if processing_key in self._processing_workflows:
            return
        
        self._processing_workflows.add(processing_key)
        
        try:
            logger.debug(f"Task {task_id} started in workflow {workflow_id}")
            
            # Get workflow from persistence
            workflow = await self.persistence.get_workflow(workflow_id)
            if not workflow:
                return
            
            # If workflow is not yet running, mark it as started
            if workflow.status == WorkflowStatus.PENDING:
                workflow.status = WorkflowStatus.RUNNING
                workflow.started_at = datetime.utcnow()
                await self.persistence.save_workflow(workflow)
                
                # Emit WORKFLOW_STARTED event
                started_event = create_workflow_started_event(
                    workflow_id=workflow_id,
                    workflow_name=workflow.name,
                    total_tasks=len(workflow.tasks),
                    source="workflow_manager"
                )
                await self.event_bus.emit(started_event)
                
                logger.info(f"Workflow {workflow_id} marked as RUNNING")
        
        finally:
            self._processing_workflows.discard(processing_key)
    
    async def _on_task_completed(self, event: GleitzeitEvent):
        """Handle task completion - may trigger workflow completion"""
        task_id = event.data.get('task_id')
        workflow_id = event.data.get('workflow_id')
        
        if not workflow_id:
            return
        
        logger.debug(f"Task {task_id} completed in workflow {workflow_id}")
        
        # Check workflow completion
        await self._check_workflow_completion(workflow_id)
    
    async def _on_task_failed(self, event: GleitzeitEvent):
        """Handle task failure - may trigger workflow failure"""
        task_id = event.data.get('task_id')
        workflow_id = event.data.get('workflow_id')
        is_permanent = event.data.get('is_permanent', False)
        
        if not workflow_id:
            return
        
        logger.debug(f"Task {task_id} failed in workflow {workflow_id} (permanent: {is_permanent})")
        
        if is_permanent:
            # Check if workflow should fail
            await self._check_workflow_failure(workflow_id)
        else:
            # Just update progress
            await self._update_workflow_progress(workflow_id)
    
    async def _check_workflow_completion(self, workflow_id: str):
        """Check if workflow is complete and emit event if so"""
        # Prevent duplicate processing
        processing_key = f"{workflow_id}:complete"
        if processing_key in self._processing_workflows:
            return
        
        self._processing_workflows.add(processing_key)
        
        try:
            workflow = await self.persistence.get_workflow(workflow_id)
            if not workflow:
                return
            
            # Already complete?
            if workflow.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                return
            
            # Get all task results
            all_complete = True
            completed_count = 0
            failed_count = 0
            
            for task in workflow.tasks:
                result = await self.persistence.get_task_result(task.id)
                if not result:
                    # Task not yet executed
                    all_complete = False
                elif result.status == TaskStatus.COMPLETED:
                    completed_count += 1
                elif result.status == TaskStatus.FAILED:
                    # Check if task has max retries reached
                    task_obj = await self.persistence.get_task(task.id)
                    if task_obj and task_obj.metadata and task_obj.metadata.get('max_retries_reached'):
                        failed_count += 1
                    else:
                        # Task may still be retried
                        all_complete = False
                else:
                    # Task in progress or queued
                    all_complete = False
            
            if all_complete:
                # Determine final status
                if failed_count > 0:
                    workflow.status = WorkflowStatus.FAILED
                else:
                    workflow.status = WorkflowStatus.COMPLETED
                
                workflow.completed_at = datetime.utcnow()
                await self.persistence.save_workflow(workflow)
                
                # Calculate duration
                duration = 0.0
                if workflow.started_at and workflow.completed_at:
                    duration = (workflow.completed_at - workflow.started_at).total_seconds()
                
                # Emit appropriate completion event
                if workflow.status == WorkflowStatus.COMPLETED:
                    completion_event = create_workflow_completed_event(
                        workflow_id=workflow_id,
                        workflow_name=workflow.name,
                        total_tasks=len(workflow.tasks),
                        completed_tasks=completed_count,
                        failed_tasks=failed_count,
                        duration=duration,
                        source="workflow_manager"
                    )
                else:
                    completion_event = create_workflow_failed_event(
                        workflow_id=workflow_id,
                        workflow_name=workflow.name,
                        total_tasks=len(workflow.tasks),
                        completed_tasks=completed_count,
                        failed_tasks=failed_count,
                        duration=duration,
                        error_message=f"{failed_count} task(s) failed permanently",
                        source="workflow_manager"
                    )
                
                await self.event_bus.emit(completion_event)
                
                logger.info(f"Workflow {workflow_id} completed with status {workflow.status} "
                          f"(completed: {completed_count}, failed: {failed_count})")
        
        finally:
            self._processing_workflows.discard(processing_key)
    
    async def _check_workflow_failure(self, workflow_id: str):
        """Check if workflow should be marked as failed due to critical task failure"""
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow or workflow.status not in [WorkflowStatus.RUNNING, WorkflowStatus.PENDING]:
            return
        
        # Check if any critical task has permanently failed
        has_critical_failure = False
        failed_tasks = []
        
        for task in workflow.tasks:
            task_obj = await self.persistence.get_task(task.id)
            if task_obj and task_obj.status == TaskStatus.FAILED:
                if task_obj.metadata and task_obj.metadata.get('max_retries_reached'):
                    has_critical_failure = True
                    failed_tasks.append(task.name or task.id)
        
        if has_critical_failure:
            # Mark workflow as failed
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = datetime.utcnow()
            await self.persistence.save_workflow(workflow)
            
            # Calculate duration
            duration = 0.0
            if workflow.started_at and workflow.completed_at:
                duration = (workflow.completed_at - workflow.started_at).total_seconds()
            
            # Emit workflow failed event
            failed_event = create_workflow_failed_event(
                workflow_id=workflow_id,
                workflow_name=workflow.name,
                total_tasks=len(workflow.tasks),
                completed_tasks=0,  # Will be updated when we count properly
                failed_tasks=len(failed_tasks),
                duration=duration,
                error_message=f"Critical task failures: {', '.join(failed_tasks)}",
                source="workflow_manager"
            )
            
            await self.event_bus.emit(failed_event)
            
            logger.info(f"Workflow {workflow_id} marked as FAILED due to critical task failures")
    
    async def _update_workflow_progress(self, workflow_id: str):
        """Update workflow progress metrics"""
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return
        
        # Count task statuses
        completed_count = 0
        failed_count = 0
        running_count = 0
        queued_count = 0
        
        for task in workflow.tasks:
            task_obj = await self.persistence.get_task(task.id)
            if task_obj:
                if task_obj.status == TaskStatus.COMPLETED:
                    completed_count += 1
                elif task_obj.status == TaskStatus.FAILED:
                    if task_obj.metadata and task_obj.metadata.get('max_retries_reached'):
                        failed_count += 1
                elif task_obj.status == TaskStatus.EXECUTING:
                    running_count += 1
                elif task_obj.status in [TaskStatus.QUEUED, TaskStatus.RETRY_PENDING, TaskStatus.PENDING]:
                    queued_count += 1
        
        # Update workflow metadata with progress
        if not workflow.metadata:
            workflow.metadata = {}
        
        workflow.metadata['progress'] = {
            'completed': completed_count,
            'failed': failed_count,
            'running': running_count,
            'queued': queued_count,
            'total': len(workflow.tasks),
            'percentage': round((completed_count / len(workflow.tasks)) * 100, 1) if workflow.tasks else 0
        }
        
        await self.persistence.save_workflow(workflow)
        
        # Emit progress update event
        progress_event = create_custom_event(
            event_type=EventType.WORKFLOW_PROGRESS,
            data={
                'workflow_id': workflow_id,
                'workflow_name': workflow.name,
                'progress': workflow.metadata['progress']
            },
            source="workflow_manager"
        )
        
        await self.event_bus.emit(progress_event)
        
        logger.debug(f"Workflow {workflow_id} progress updated: {workflow.metadata['progress']}")
    
    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed workflow status"""
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return None
        
        # Gather task statuses
        task_statuses = []
        for task in workflow.tasks:
            task_obj = await self.persistence.get_task(task.id)
            if task_obj:
                # Handle status as either enum or string
                status_value = task_obj.status.value if hasattr(task_obj.status, 'value') else str(task_obj.status)
                task_statuses.append({
                    'id': task.id,
                    'name': task.name,
                    'status': status_value,
                    'started_at': task_obj.started_at.isoformat() if task_obj.started_at else None,
                    'completed_at': task_obj.completed_at.isoformat() if task_obj.completed_at else None,
                    'error_message': task_obj.error_message
                })
        
        # Handle workflow status as either enum or string
        workflow_status_value = workflow.status.value if hasattr(workflow.status, 'value') else str(workflow.status)
        
        return {
            'workflow_id': workflow_id,
            'name': workflow.name,
            'status': workflow_status_value,
            'created_at': workflow.created_at.isoformat() if workflow.created_at else None,
            'started_at': workflow.started_at.isoformat() if workflow.started_at else None,
            'completed_at': workflow.completed_at.isoformat() if workflow.completed_at else None,
            'tasks': task_statuses,
            'metadata': workflow.metadata or {}
        }