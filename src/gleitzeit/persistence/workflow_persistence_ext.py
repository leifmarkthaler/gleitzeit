"""
Extended persistence methods for stateless workflow management.

These extensions provide additional persistence operations needed for
stateless workflow and dependency management.
"""

import logging
from typing import Dict, List, Set, Optional, Any
from datetime import datetime

from gleitzeit.core.models import TaskStatus, WorkflowStatus

logger = logging.getLogger(__name__)


class WorkflowPersistenceExtensions:
    """
    Extensions for workflow persistence operations.
    
    These methods can be mixed into existing persistence backends
    or used as a wrapper around them.
    """
    
    def __init__(self, base_persistence):
        """
        Initialize with a base persistence backend.
        
        Args:
            base_persistence: The underlying persistence backend
        """
        self.base = base_persistence
    
    async def get_task_statuses(self, workflow_id: str) -> Dict[str, TaskStatus]:
        """
        Get all task statuses for a workflow.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            Dictionary mapping task IDs to their statuses
        """
        try:
            # Use base persistence to list tasks
            tasks = await self.base.list_tasks(workflow_id=workflow_id)
            
            statuses = {}
            for task in tasks:
                if isinstance(task, dict):
                    task_id = task.get('id')
                    status = task.get('status', 'pending')
                else:
                    task_id = task.id
                    status = task.status
                    
                if task_id:
                    statuses[task_id] = TaskStatus(status) if isinstance(status, str) else status
            
            return statuses
            
        except Exception as e:
            logger.error(f"Error getting task statuses: {e}")
            return {}
    
    async def get_completed_task_ids(self, workflow_id: str) -> Set[str]:
        """
        Get IDs of all completed tasks in a workflow.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            Set of completed task IDs
        """
        statuses = await self.get_task_statuses(workflow_id)
        return {
            task_id for task_id, status in statuses.items()
            if status == TaskStatus.COMPLETED
        }
    
    async def get_failed_task_ids(self, workflow_id: str) -> Set[str]:
        """
        Get IDs of all failed tasks in a workflow.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            Set of failed task IDs
        """
        statuses = await self.get_task_statuses(workflow_id)
        return {
            task_id for task_id, status in statuses.items()
            if status == TaskStatus.FAILED
        }
    
    async def get_running_task_ids(self, workflow_id: str) -> Set[str]:
        """
        Get IDs of all currently running tasks.
        
        Args:
            workflow_id: Workflow ID
            
        Returns:
            Set of running task IDs
        """
        statuses = await self.get_task_statuses(workflow_id)
        return {
            task_id for task_id, status in statuses.items()
            if status == TaskStatus.EXECUTING
        }
    
    # Workflow execution tracking
    
    async def save_workflow_execution(
        self, 
        execution_id: str,
        workflow_id: str,
        status: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Save workflow execution state to persistence.
        
        Args:
            execution_id: Unique execution ID
            workflow_id: Workflow being executed
            status: Current execution status
            metadata: Additional execution metadata
        """
        execution_data = {
            'execution_id': execution_id,
            'workflow_id': workflow_id,
            'status': status,
            'metadata': metadata or {},
            'updated_at': datetime.utcnow().isoformat()
        }
        
        # Store in Redis or database
        key = f"workflow_execution:{execution_id}"
        await self.base.set(key, execution_data)
    
    async def get_workflow_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """
        Get workflow execution state from persistence.
        
        Args:
            execution_id: Execution ID to retrieve
            
        Returns:
            Execution data or None if not found
        """
        key = f"workflow_execution:{execution_id}"
        return await self.base.get(key)
    
    async def list_workflow_executions(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List workflow executions with optional filters.
        
        Args:
            workflow_id: Filter by workflow ID
            status: Filter by execution status
            
        Returns:
            List of execution records
        """
        # Get all execution keys
        pattern = "workflow_execution:*"
        keys = await self.base.keys(pattern)
        
        executions = []
        for key in keys:
            execution = await self.base.get(key)
            if execution:
                # Apply filters
                if workflow_id and execution.get('workflow_id') != workflow_id:
                    continue
                if status and execution.get('status') != status:
                    continue
                executions.append(execution)
        
        return executions
    
    # Workflow templates (for future use)
    
    async def save_workflow_template(
        self,
        template_id: str,
        template_data: Dict[str, Any]
    ) -> None:
        """
        Save a workflow template to persistence.
        
        Args:
            template_id: Unique template ID
            template_data: Template configuration
        """
        key = f"workflow_template:{template_id}"
        template_data['template_id'] = template_id
        template_data['saved_at'] = datetime.utcnow().isoformat()
        await self.base.set(key, template_data)
    
    async def get_workflow_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a workflow template from persistence.
        
        Args:
            template_id: Template ID to retrieve
            
        Returns:
            Template data or None if not found
        """
        key = f"workflow_template:{template_id}"
        return await self.base.get(key)
    
    async def list_workflow_templates(self) -> List[Dict[str, Any]]:
        """
        List all workflow templates.
        
        Returns:
            List of template records
        """
        pattern = "workflow_template:*"
        keys = await self.base.keys(pattern)
        
        templates = []
        for key in keys:
            template = await self.base.get(key)
            if template:
                templates.append(template)
        
        return templates
    
    # Scheduled workflows (for future use)
    
    async def save_scheduled_workflow(
        self,
        schedule_id: str,
        schedule_data: Dict[str, Any]
    ) -> None:
        """
        Save a scheduled workflow to persistence.
        
        Args:
            schedule_id: Unique schedule ID
            schedule_data: Schedule configuration
        """
        key = f"workflow_schedule:{schedule_id}"
        schedule_data['schedule_id'] = schedule_id
        schedule_data['created_at'] = datetime.utcnow().isoformat()
        await self.base.set(key, schedule_data)
    
    async def get_scheduled_workflow(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a scheduled workflow from persistence.
        
        Args:
            schedule_id: Schedule ID to retrieve
            
        Returns:
            Schedule data or None if not found
        """
        key = f"workflow_schedule:{schedule_id}"
        return await self.base.get(key)
    
    async def list_scheduled_workflows(
        self,
        due_before: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        List scheduled workflows, optionally filtering by due date.
        
        Args:
            due_before: Only return schedules due before this time
            
        Returns:
            List of schedule records
        """
        pattern = "workflow_schedule:*"
        keys = await self.base.keys(pattern)
        
        schedules = []
        for key in keys:
            schedule = await self.base.get(key)
            if schedule:
                # Check due date filter
                if due_before:
                    next_run = schedule.get('next_run')
                    if next_run:
                        if isinstance(next_run, str):
                            next_run = datetime.fromisoformat(next_run)
                        if next_run > due_before:
                            continue
                schedules.append(schedule)
        
        return schedules
    
    async def delete_scheduled_workflow(self, schedule_id: str) -> bool:
        """
        Delete a scheduled workflow.
        
        Args:
            schedule_id: Schedule ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        key = f"workflow_schedule:{schedule_id}"
        return await self.base.delete(key)