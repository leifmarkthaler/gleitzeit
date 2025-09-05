"""
Stateless Workflow Manager for Gleitzeit.

A fully stateless implementation of workflow management that uses persistence
for all state storage, enabling horizontal scaling and distributed operation.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from uuid import uuid4

from gleitzeit.core.models import (
    Task, Workflow, WorkflowStatus, TaskStatus,
    Priority, TaskResult, RetryConfig
)
from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2 as ExecutionEngine
from gleitzeit.core.stateless_dependency_manager import StatelessDependencyManager
from gleitzeit.persistence.workflow_persistence_ext import WorkflowPersistenceExtensions
from gleitzeit.core.errors import WorkflowError, WorkflowValidationError
from gleitzeit.core.logging_mixin import LoggingMixin

logger = logging.getLogger(__name__)


class WorkflowExecutionPolicy(Enum):
    """Policies for workflow execution behavior."""
    FAIL_FAST = "fail_fast"
    CONTINUE_ON_ERROR = "continue_on_error"
    RETRY_FAILED = "retry_failed"


class WorkflowManager(LoggingMixin):
    """
    Workflow orchestration and management.
    
    All state is stored in persistence, no in-memory workflow tracking.
    This allows multiple instances to coordinate workflow execution.
    
    Features:
    - Workflow submission and execution
    - Template management (via persistence)
    - Scheduling (via persistence)
    - Execution monitoring (via persistence)
    - Fully horizontally scalable
    """
    
    def __init__(
        self,
        execution_engine: ExecutionEngine,
        dependency_manager: StatelessDependencyManager,
        persistence: Any,
        event_bus: Optional[Any] = None,
        template_directory: Optional[Path] = None
    ):
        """
        Initialize stateless workflow manager.
        
        Args:
            execution_engine: Engine for task execution
            dependency_manager: Stateless dependency manager
            persistence: Persistence backend for all state
            event_bus: Optional event bus for coordination
            template_directory: Optional directory for file-based templates
        """
        # Initialize LoggingMixin
        super().__init__()
        
        self.execution_engine = execution_engine
        self.dependency_manager = dependency_manager
        self.persistence = persistence
        self.event_bus = event_bus
        self.template_directory = template_directory
        
        # Wrap persistence with extensions
        self.workflow_persistence = WorkflowPersistenceExtensions(persistence)
        
        # Setup event handlers if event bus provided
        if event_bus:
            self._setup_event_handlers()
        
        logger.info("Initialized WorkflowManager")
    
    def _setup_event_handlers(self):
        """Setup event handlers for workflow events."""
        if not self.event_bus:
            return
        
        from gleitzeit.core.events import EventType
        
        # Register handlers
        self.event_bus.register(EventType.TASK_COMPLETED, self._on_task_completed)
        self.event_bus.register(EventType.TASK_FAILED, self._on_task_failed)
        self.event_bus.register(EventType.WORKFLOW_COMPLETED, self._on_workflow_completed)
        self.event_bus.register(EventType.WORKFLOW_FAILED, self._on_workflow_failed)
        
        logger.debug("Registered event handlers for workflow events")
    
    # Workflow execution methods
    
    async def execute_workflow(
        self,
        workflow: Workflow,
        policy: WorkflowExecutionPolicy = WorkflowExecutionPolicy.FAIL_FAST,
        execution_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a workflow with specified policy.
        
        All execution state is stored in persistence, not memory.
        
        Args:
            workflow: Workflow to execute
            policy: Execution policy
            execution_context: Optional execution context
            
        Returns:
            Execution information dictionary
        """
        # Generate execution ID
        execution_id = f"{workflow.id}-exec-{uuid4().hex[:8]}"
        
        await self.log_operation(
            "workflow_execution_start",
            workflow_id=workflow.id,
            execution_id=execution_id,
            policy=policy.value,
            task_count=len(workflow.tasks)
        )
        
        try:
            # Validate workflow dependencies
            await self.log_debug(
                "workflow_validation_start",
                f"Validating workflow {workflow.id} dependencies",
                workflow_id=workflow.id,
                execution_id=execution_id
            )
            
            validation_errors = await self.dependency_manager.validate_workflow(workflow)
            
            # Validate provider availability through the pooling adapter (where providers actually are)
            # The pooling adapter is available through the execution engine
            if hasattr(self.execution_engine, 'pooling_adapter') and self.execution_engine.pooling_adapter:
                pooling_adapter = self.execution_engine.pooling_adapter
                for task in workflow.tasks:
                    if task.protocol:
                        is_available, error_msg = await pooling_adapter.validate_provider_availability(task.protocol)
                        if not is_available:
                            validation_errors.append(f"Task '{task.name}': {error_msg}")
            
            if validation_errors:
                await self.log_error(
                    "workflow_validation_failed",
                    WorkflowValidationError(workflow.id, validation_errors),
                    workflow_id=workflow.id,
                    execution_id=execution_id,
                    validation_errors=validation_errors
                )
                raise WorkflowValidationError(
                    workflow_id=workflow.id,
                    validation_errors=validation_errors
                )
            
            await self.log_success(
                "workflow_validation_complete",
                workflow_id=workflow.id,
                execution_id=execution_id,
                description="Workflow validation completed successfully"
            )
            
            # Save execution state to persistence
            await self.log_debug(
                "workflow_persistence_save",
                "Saving workflow execution state to persistence",
                workflow_id=workflow.id,
                execution_id=execution_id,
                status="PENDING"
            )
            await self.workflow_persistence.save_workflow_execution(
                execution_id=execution_id,
                workflow_id=workflow.id,
                status=WorkflowStatus.PENDING.value,
                metadata={
                    'policy': policy.value,
                    'context': execution_context or {},
                    'started_at': datetime.utcnow().isoformat()
                }
            )
            
            # Update workflow status
            workflow.status = WorkflowStatus.RUNNING
            workflow.started_at = datetime.utcnow()
            # Save the updated workflow back to persistence
            await self.persistence.save_workflow(workflow)
            
            await self.log_operation(
                "workflow_status_update",
                workflow_id=workflow.id,
                execution_id=execution_id,
                status="RUNNING",
                started_at=workflow.started_at.isoformat()
            )
            
            logger.info(f"Starting workflow execution {execution_id}")
            
            # Submit to execution engine
            await self.log_operation(
                "workflow_engine_submit",
                workflow_id=workflow.id,
                execution_id=execution_id,
                message="Submitting workflow to execution engine"
            )
            await self.execution_engine.submit_workflow(workflow)
            
            # Update execution state
            await self.workflow_persistence.save_workflow_execution(
                execution_id=execution_id,
                workflow_id=workflow.id,
                status=WorkflowStatus.RUNNING.value,
                metadata={
                    'policy': policy.value,
                    'context': execution_context or {},
                    'started_at': workflow.started_at.isoformat()
                }
            )
            
            await self.log_success(
                "workflow_execution_started",
                workflow_id=workflow.id,
                execution_id=execution_id,
                status="RUNNING",
                description="Workflow execution started successfully"
            )
            
            return {
                'execution_id': execution_id,
                'workflow_id': workflow.id,
                'status': WorkflowStatus.RUNNING.value,
                'message': 'Workflow execution started'
            }
            
        except Exception as e:
            await self.log_error(
                "workflow_execution_failed",
                e,
                workflow_id=workflow.id,
                execution_id=execution_id
            )
            
            # Mark as failed in persistence
            await self.workflow_persistence.save_workflow_execution(
                execution_id=execution_id,
                workflow_id=workflow.id,
                status=WorkflowStatus.FAILED.value,
                metadata={
                    'error': str(e),
                    'failed_at': datetime.utcnow().isoformat()
                }
            )
            
            workflow.status = WorkflowStatus.FAILED
            await self.persistence.save_workflow(workflow)
            
            logger.error(f"Workflow execution {execution_id} failed: {e}")
            raise
    
    async def get_execution_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of a workflow execution from persistence.
        
        Args:
            execution_id: Execution ID to query
            
        Returns:
            Execution status information or None if not found
        """
        await self.log_debug(
            "execution_status_query",
            "Querying execution status",
            execution_id=execution_id
        )
        
        execution = await self.workflow_persistence.get_workflow_execution(execution_id)
        if not execution:
            await self.log_debug(
                "execution_status_not_found",
                "Execution not found",
                execution_id=execution_id
            )
            return None
        
        # Get current task statuses
        workflow_id = execution['workflow_id']
        task_statuses = await self.workflow_persistence.get_task_statuses(workflow_id)
        
        # Calculate progress
        total_tasks = len(task_statuses)
        completed_tasks = sum(1 for s in task_statuses.values() if s == TaskStatus.COMPLETED)
        failed_tasks = sum(1 for s in task_statuses.values() if s == TaskStatus.FAILED)
        
        result = {
            'execution_id': execution_id,
            'workflow_id': workflow_id,
            'status': execution['status'],
            'started_at': execution.get('metadata', {}).get('started_at'),
            'completed_at': execution.get('metadata', {}).get('completed_at'),
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'failed_tasks': failed_tasks,
            'progress': (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0.0,
            'policy': execution.get('metadata', {}).get('policy')
        }
        
        await self.log_debug(
            "execution_status_retrieved",
            "Retrieved execution status",
            execution_id=execution_id,
            workflow_id=workflow_id,
            status=execution['status'],
            progress=result['progress']
        )
        
        return result
    
    async def list_active_executions(self) -> List[Dict[str, Any]]:
        """
        List all active workflow executions from persistence.
        
        Returns:
            List of active execution summaries
        """
        executions = await self.workflow_persistence.list_workflow_executions(
            status=WorkflowStatus.RUNNING.value
        )
        
        return [
            {
                'execution_id': exec['execution_id'],
                'workflow_id': exec['workflow_id'],
                'status': exec['status'],
                'started_at': exec.get('metadata', {}).get('started_at')
            }
            for exec in executions
        ]
    
    # Template management
    
    async def save_template(self, template_id: str, template_data: Dict[str, Any]) -> None:
        """
        Save a workflow template to persistence.
        
        Args:
            template_id: Unique template identifier
            template_data: Template configuration
        """
        await self.log_operation(
            "template_save",
            template_id=template_id,
            name=template_data.get('name', 'Unknown'),
            task_count=len(template_data.get('tasks', []))
        )
        
        await self.workflow_persistence.save_workflow_template(template_id, template_data)
        
        await self.log_success(
            "template_saved",
            template_id=template_id,
            description="Workflow template saved successfully"
        )
        
        logger.info(f"Saved workflow template {template_id}")
    
    async def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a workflow template from persistence.
        
        Args:
            template_id: Template ID to retrieve
            
        Returns:
            Template data or None if not found
        """
        return await self.workflow_persistence.get_workflow_template(template_id)
    
    async def list_templates(self) -> List[Dict[str, Any]]:
        """
        List all workflow templates from persistence.
        
        Returns:
            List of template summaries
        """
        templates = await self.workflow_persistence.list_workflow_templates()
        return [
            {
                'id': t.get('template_id'),
                'name': t.get('name'),
                'description': t.get('description'),
                'version': t.get('version'),
                'task_count': len(t.get('tasks', []))
            }
            for t in templates
        ]
    
    async def create_workflow_from_template(
        self,
        template_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        workflow_id: Optional[str] = None
    ) -> Workflow:
        """
        Create a workflow instance from a template.
        
        Args:
            template_id: Template to use
            parameters: Template parameters
            workflow_id: Optional workflow ID
            
        Returns:
            Created workflow
        """
        await self.log_operation(
            "workflow_from_template_start",
            template_id=template_id,
            workflow_id=workflow_id,
            parameters=list(parameters.keys()) if parameters else []
        )
        
        template = await self.get_template(template_id)
        if not template:
            await self.log_error(
                "template_not_found",
                ValueError(f"Template {template_id} not found"),
                template_id=template_id
            )
            raise ValueError(f"Template {template_id} not found")
        
        # Generate workflow ID if not provided
        workflow_id = workflow_id or f"{template_id}-{uuid4().hex[:8]}"
        
        # Substitute parameters
        context = {**template.get('parameters', {}), **(parameters or {})}
        
        # Create tasks
        tasks = []
        for task_template in template.get('tasks', []):
            task = Task(
                id=task_template.get('id', f"{workflow_id}-task-{len(tasks)}"),
                name=task_template.get('name', f"Task {len(tasks) + 1}"),
                protocol=task_template['protocol'],
                method=task_template['method'],
                params=self._substitute_params(task_template.get('params', {}), context),
                dependencies=task_template.get('dependencies', []),
                priority=Priority(task_template.get('priority', 'normal')),
                workflow_id=workflow_id
            )
            tasks.append(task)
        
        # Create workflow
        workflow = Workflow(
            id=workflow_id,
            name=template.get('name', 'Workflow'),
            description=template.get('description'),
            tasks=tasks,
            metadata={
                'template_id': template_id,
                'created_from_template': True,
                'parameters': parameters
            }
        )
        
        await self.log_success(
            "workflow_from_template_complete",
            template_id=template_id,
            workflow_id=workflow_id,
            task_count=len(tasks),
            description="Created workflow from template successfully"
        )
        
        logger.info(f"Created workflow {workflow_id} from template {template_id}")
        return workflow
    
    def _substitute_params(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Substitute template variables in parameters.
        
        Simple ${var} substitution for now.
        """
        import re
        
        def substitute(value):
            if isinstance(value, str):
                pattern = r'\$\{([^}]+)\}'
                return re.sub(
                    pattern,
                    lambda m: str(context.get(m.group(1), m.group(0))),
                    value
                )
            elif isinstance(value, dict):
                return {k: substitute(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [substitute(item) for item in value]
            else:
                return value
        
        return substitute(params)
    
    # Scheduling methods
    
    async def schedule_workflow(
        self,
        template_id: str,
        schedule_time: datetime,
        parameters: Optional[Dict[str, Any]] = None,
        recurring_interval: Optional[int] = None
    ) -> str:
        """
        Schedule a workflow for future execution.
        
        Stores schedule in persistence for distributed processing.
        
        Args:
            template_id: Template to use
            schedule_time: When to run
            parameters: Template parameters
            recurring_interval: Optional recurrence in seconds
            
        Returns:
            Schedule ID
        """
        schedule_id = f"schedule-{uuid4().hex[:8]}"
        
        schedule_data = {
            'template_id': template_id,
            'parameters': parameters or {},
            'next_run': schedule_time.isoformat(),
            'recurring_interval': recurring_interval
        }
        
        await self.workflow_persistence.save_scheduled_workflow(schedule_id, schedule_data)
        
        logger.info(f"Scheduled workflow {template_id} for {schedule_time.isoformat()}")
        return schedule_id
    
    async def cancel_scheduled_workflow(self, schedule_id: str) -> bool:
        """
        Cancel a scheduled workflow.
        
        Args:
            schedule_id: Schedule to cancel
            
        Returns:
            True if cancelled, False if not found
        """
        return await self.workflow_persistence.delete_scheduled_workflow(schedule_id)
    
    async def list_scheduled_workflows(self) -> List[Dict[str, Any]]:
        """
        List all scheduled workflows.
        
        Returns:
            List of schedule information
        """
        schedules = await self.workflow_persistence.list_scheduled_workflows()
        return [
            {
                'schedule_id': s.get('schedule_id'),
                'template_id': s.get('template_id'),
                'next_run': s.get('next_run'),
                'recurring': s.get('recurring_interval') is not None
            }
            for s in schedules
        ]
    
    # Event handlers (update persistence, no memory state)
    
    async def _on_task_completed(self, event) -> None:
        """Handle task completion event."""
        task_id = event.data.get('task_id')
        workflow_id = event.data.get('workflow_id')
        
        if task_id and workflow_id:
            # Mark task complete in persistence
            await self.dependency_manager.mark_task_completed(workflow_id, task_id)
            logger.debug(f"Task {task_id} marked complete in persistence")
    
    async def _on_task_failed(self, event) -> None:
        """Handle task failure event."""
        task_id = event.data.get('task_id')
        workflow_id = event.data.get('workflow_id')
        
        if task_id and workflow_id:
            # Mark task failed in persistence
            await self.dependency_manager.mark_task_failed(workflow_id, task_id)
            logger.debug(f"Task {task_id} marked failed in persistence")
    
    async def _on_workflow_completed(self, event) -> None:
        """Handle workflow completion event."""
        workflow_id = event.data.get('workflow_id')
        
        if workflow_id:
            # Update workflow status in persistence
            workflow = await self.persistence.get_workflow(workflow_id)
            if workflow:
                workflow.status = WorkflowStatus.COMPLETED
                await self.persistence.save_workflow(workflow)
            
            # Update any executions for this workflow
            executions = await self.workflow_persistence.list_workflow_executions(workflow_id=workflow_id)
            for exec in executions:
                if exec['status'] == WorkflowStatus.RUNNING.value:
                    await self.workflow_persistence.save_workflow_execution(
                        execution_id=exec['execution_id'],
                        workflow_id=workflow_id,
                        status=WorkflowStatus.COMPLETED.value,
                        metadata={
                            **exec.get('metadata', {}),
                            'completed_at': datetime.utcnow().isoformat()
                        }
                    )
            
            logger.info(f"Workflow {workflow_id} marked complete in persistence")
    
    async def _on_workflow_failed(self, event) -> None:
        """Handle workflow failure event."""
        workflow_id = event.data.get('workflow_id')
        
        if workflow_id:
            # Update workflow status in persistence
            workflow = await self.persistence.get_workflow(workflow_id)
            if workflow:
                workflow.status = WorkflowStatus.FAILED
                await self.persistence.save_workflow(workflow)
            
            # Update executions
            executions = await self.workflow_persistence.list_workflow_executions(workflow_id=workflow_id)
            for exec in executions:
                if exec['status'] == WorkflowStatus.RUNNING.value:
                    await self.workflow_persistence.save_workflow_execution(
                        execution_id=exec['execution_id'],
                        workflow_id=workflow_id,
                        status=WorkflowStatus.FAILED.value,
                        metadata={
                            **exec.get('metadata', {}),
                            'failed_at': datetime.utcnow().isoformat()
                        }
                    )
            
            logger.info(f"Workflow {workflow_id} marked failed in persistence")