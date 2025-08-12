"""
Workflow Engine for Gleitzeit V2

Orchestrates workflow execution with task dependencies, provider coordination,
and event-driven completion tracking.
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional, Any, Set
from datetime import datetime

from .models import Workflow, Task, WorkflowStatus, TaskStatus
from .provider_manager import ProviderManager
from .task_queue import TaskQueue
from ..storage.redis_client import RedisClient

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    Orchestrates workflow execution
    
    Features:
    - Workflow lifecycle management
    - Task dependency resolution and scheduling
    - Provider assignment and coordination
    - Event-driven completion tracking
    - Error handling and recovery
    """
    
    def __init__(self, redis_client: RedisClient, task_queue: TaskQueue, provider_manager: ProviderManager):
        self.redis_client = redis_client
        self.task_queue = task_queue
        self.provider_manager = provider_manager
        
        # Active workflows
        self.workflows: Dict[str, Workflow] = {}
        self.task_to_workflow: Dict[str, str] = {}  # task_id -> workflow_id
        self.task_assignments: Dict[str, str] = {}  # task_id -> provider_id
        
        # Engine state
        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._scheduler_interval = 2.0  # seconds
        
        # Server reference (set by server)
        self._server = None
        
        logger.info("WorkflowEngine initialized")
    
    def set_server(self, server):
        """Set reference to server for event broadcasting"""
        self._server = server
    
    async def start(self):
        """Start the workflow engine"""
        if self._running:
            return
        
        self._running = True
        
        # Start task scheduler
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        
        logger.info("WorkflowEngine started")
    
    async def stop(self):
        """Stop the workflow engine"""
        if not self._running:
            return
        
        self._running = False
        
        # Stop scheduler
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        
        logger.info("WorkflowEngine stopped")
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit workflow for execution"""
        try:
            logger.info(f"Submitting workflow: {workflow.name} ({workflow.id})")
            logger.info(f"  Tasks: {len(workflow.tasks)}")
            
            # Store workflow
            self.workflows[workflow.id] = workflow
            workflow.status = WorkflowStatus.QUEUED
            workflow.started_at = datetime.utcnow()
            
            # Register task-to-workflow mapping
            for task in workflow.tasks:
                self.task_to_workflow[task.id] = workflow.id
            
            # Persist workflow
            await self.redis_client.store_workflow(workflow)
            
            # Enqueue tasks (handles dependencies automatically)
            logger.info(f"Enqueueing {len(workflow.tasks)} tasks for workflow {workflow.id}")
            await self.task_queue.enqueue_batch(workflow.tasks)
            logger.info(f"Tasks enqueued. Current queue size: {self.task_queue.get_queue_size()}")
            
            # Update workflow status
            workflow.status = WorkflowStatus.RUNNING
            await self._update_workflow_status(workflow.id, WorkflowStatus.RUNNING)
            
            logger.info(f"Workflow submitted: {workflow.id}")
            return workflow.id
            
        except Exception as e:
            logger.error(f"Failed to submit workflow {workflow.id}: {e}")
            workflow.status = WorkflowStatus.FAILED
            await self._update_workflow_status(workflow.id, WorkflowStatus.FAILED)
            raise
    
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a workflow"""
        if workflow_id not in self.workflows:
            return False
        
        workflow = self.workflows[workflow_id]
        
        # Cancel all pending/queued tasks
        cancelled_count = 0
        for task in workflow.tasks:
            if await self.task_queue.cancel_task(task.id):
                cancelled_count += 1
        
        # Update workflow status
        workflow.status = WorkflowStatus.CANCELLED
        workflow.completed_at = datetime.utcnow()
        await self._update_workflow_status(workflow_id, WorkflowStatus.CANCELLED)
        
        logger.info(f"Workflow cancelled: {workflow_id} ({cancelled_count} tasks cancelled)")
        return True
    
    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status and progress"""
        if workflow_id in self.workflows:
            workflow = self.workflows[workflow_id]
            progress = workflow.get_progress()
            
            return {
                'id': workflow.id,
                'name': workflow.name,
                'status': workflow.status.value,
                'progress': progress,
                'created_at': workflow.created_at.isoformat(),
                'started_at': workflow.started_at.isoformat() if workflow.started_at else None,
                'completed_at': workflow.completed_at.isoformat() if workflow.completed_at else None,
                'task_results': workflow.task_results
            }
        
        # Try to get from Redis
        workflow_data = await self.redis_client.get_workflow(workflow_id)
        return workflow_data or {}
    
    async def on_provider_available(self, provider_id: str):
        """Handle provider becoming available"""
        logger.debug(f"Provider available: {provider_id}")
        # Trigger scheduler to assign pending tasks
        # This is handled by the continuous scheduler loop
    
    async def on_task_accepted(self, task_id: str, provider_id: str):
        """Handle task acceptance by provider"""
        logger.debug(f"Task accepted: {task_id} by {provider_id}")
        
        # Track assignment
        self.task_assignments[task_id] = provider_id
        
        # Update provider load
        await self.provider_manager.mark_provider_busy(provider_id, task_id)
    
    async def on_task_completed(self, task_id: str, workflow_id: str, result: Any):
        """Handle task completion"""
        logger.debug(f"Task completed: {task_id}")
        
        try:
            # Mark task as completed in queue
            newly_available = await self.task_queue.mark_task_completed(task_id, result)
            
            # Update workflow
            if workflow_id in self.workflows:
                workflow = self.workflows[workflow_id]
                workflow.completed_tasks.append(task_id)
                workflow.task_results[task_id] = result
                
                # Update task in workflow
                for task in workflow.tasks:
                    if task.id == task_id:
                        task.result = result
                        task.status = TaskStatus.COMPLETED
                        task.completed_at = datetime.utcnow()
                        break
                
                # Check workflow completion
                logger.info(f"Task {task_id} completed. Workflow {workflow_id} status: completed_tasks={len(workflow.completed_tasks)}, total_tasks={len(workflow.tasks)}")
                if workflow.is_complete():
                    logger.info(f"Workflow {workflow_id} is complete, calling _complete_workflow")
                    await self._complete_workflow(workflow_id)
                else:
                    # Update workflow progress
                    logger.info(f"Workflow {workflow_id} not complete yet")
                    await self._update_workflow_progress(workflow_id)
            
            # Update provider availability
            if task_id in self.task_assignments:
                provider_id = self.task_assignments.pop(task_id)
                await self.provider_manager.mark_provider_available(provider_id, task_id, success=True)
            
            logger.debug(f"Task completed: {task_id}, {len(newly_available)} tasks became available")
            
        except Exception as e:
            logger.error(f"Error handling task completion {task_id}: {e}")
    
    async def on_task_failed(self, task_id: str, workflow_id: str, error: str):
        """Handle task failure"""
        logger.warning(f"Task failed: {task_id} - {error}")
        
        try:
            # Mark task as failed in queue
            await self.task_queue.mark_task_failed(task_id, error)
            
            # Update workflow
            if workflow_id in self.workflows:
                workflow = self.workflows[workflow_id]
                workflow.failed_tasks.append(task_id)
                
                # Update task in workflow
                for task in workflow.tasks:
                    if task.id == task_id:
                        task.error = error
                        task.status = TaskStatus.FAILED
                        task.completed_at = datetime.utcnow()
                        break
                
                # Handle based on error strategy
                if workflow.error_strategy == "stop":
                    await self._fail_workflow(workflow_id, f"Task failed: {task_id}")
                elif workflow.error_strategy == "continue":
                    # Check if workflow can still complete
                    if workflow.is_complete():
                        await self._complete_workflow(workflow_id)
                    else:
                        await self._update_workflow_progress(workflow_id)
            
            # Update provider availability
            if task_id in self.task_assignments:
                provider_id = self.task_assignments.pop(task_id)
                await self.provider_manager.mark_provider_available(provider_id, task_id, success=False)
            
        except Exception as e:
            logger.error(f"Error handling task failure {task_id}: {e}")
    
    async def _scheduler_loop(self):
        """Main scheduler loop - assigns tasks to providers"""
        try:
            while self._running:
                try:
                    await self._schedule_tasks()
                    await asyncio.sleep(self._scheduler_interval)
                except Exception as e:
                    logger.error(f"Error in scheduler loop: {e}")
                    await asyncio.sleep(self._scheduler_interval)
                    
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled")
            raise
    
    async def _schedule_tasks(self):
        """Assign available tasks to providers"""
        # Get available providers
        available_providers = self.provider_manager.get_available_providers()
        
        logger.debug(f"Scheduler: Found {len(available_providers)} available providers")
        logger.debug(f"Scheduler: Queue size: {self.task_queue.get_queue_size()}")
        
        if not available_providers:
            logger.debug("No available providers, skipping task assignment")
            return
        
        assignments_made = 0
        max_assignments = 10  # Limit per cycle
        
        # Try to assign tasks to providers
        for provider in available_providers:
            logger.info(f"Scheduler: Trying provider {provider.name} with capabilities {[t.value for t in provider.capabilities.task_types]}")
            
            if assignments_made >= max_assignments:
                break
            
            # Get next compatible task
            task = await self.task_queue.dequeue_task(
                provider_capabilities=set(t.value for t in provider.capabilities.task_types)
            )
            
            logger.info(f"Scheduler: Dequeued task: {task.id if task else 'None'}")
            
            if task:
                logger.info(f"Scheduler: Assigning task {task.id} to provider {provider.name}")
                await self._assign_task_to_provider(task, provider)
                assignments_made += 1
                logger.info(f"Scheduler: Task assignment completed")
            else:
                logger.info(f"Scheduler: No compatible tasks found for provider {provider.name}")
        
        if assignments_made > 0:
            logger.debug(f"Assigned {assignments_made} tasks to providers")
    
    async def _assign_task_to_provider(self, task: Task, provider):
        """Assign a task to a provider"""
        try:
            logger.info(f"🔄 Assigning task {task.id} to provider {provider.name}")
            
            # Update task status
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            
            # Substitute task parameters with results from completed dependent tasks
            await self._substitute_task_parameters(task)
            
            # Use orchestration server to assign task
            if self._server:
                await self._server.assign_task_to_provider(task, provider)
                logger.info(f"✅ Task assigned via orchestration server: {task.id} -> {provider.name}")
            else:
                logger.warning(f"No orchestration server available for task assignment")
                
                # Put task back in queue
                task.status = TaskStatus.QUEUED
                await self.task_queue.enqueue_task(task)
            
        except Exception as e:
            logger.error(f"Failed to assign task {task.id} to provider {provider.name}: {e}")
            
            # Put task back in queue
            task.status = TaskStatus.QUEUED
            await self.task_queue.enqueue_task(task)
    
    async def _substitute_task_parameters(self, task: Task):
        """Substitute task parameters with results from completed dependent tasks"""
        logger.info(f"Starting parameter substitution for task {task.id}")
        logger.info(f"Task workflow_id: {task.workflow_id}")
        
        if not task.workflow_id or task.workflow_id not in self.workflows:
            logger.warning(f"No workflow found for task {task.id} with workflow_id {task.workflow_id}")
            return
        
        workflow = self.workflows[task.workflow_id]
        logger.info(f"Found workflow with {len(workflow.task_results)} task results: {list(workflow.task_results.keys())}")
        
        # Get task parameters as dict
        params_dict = task.parameters.to_dict()
        logger.info(f"Original parameters: {params_dict}")
        
        # Look for substitution patterns in string values
        def substitute_string(text: str) -> str:
            if not isinstance(text, str):
                return text
            
            logger.info(f"Checking string for substitution patterns: {text}")
            
            # Pattern: ${task_TASKID_result}
            pattern = r'\$\{task_([a-f0-9\-]+)_result\}'
            matches = re.findall(pattern, text)
            logger.info(f"Found {len(matches)} substitution patterns: {matches}")
            
            def replace_match(match):
                task_id = match.group(1)
                logger.info(f"Looking for result for task_id: {task_id}")
                if task_id in workflow.task_results:
                    result = workflow.task_results[task_id]
                    logger.info(f"Found result for {task_id}: {result}")
                    # Convert result to string if it's not already
                    return str(result) if result is not None else ''
                else:
                    logger.warning(f"Task result not found for substitution: {task_id}")
                    logger.warning(f"Available task results: {list(workflow.task_results.keys())}")
                    return match.group(0)  # Return original if not found
            
            substituted = re.sub(pattern, replace_match, text)
            logger.info(f"String after substitution: {substituted}")
            return substituted
        
        # Recursively substitute in all string values
        def substitute_recursive(obj):
            if isinstance(obj, dict):
                return {k: substitute_recursive(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [substitute_recursive(item) for item in obj]
            elif isinstance(obj, str):
                return substitute_string(obj)
            else:
                return obj
        
        # Apply substitutions
        substituted_params = substitute_recursive(params_dict)
        logger.info(f"Parameters after substitution: {substituted_params}")
        
        # Update task parameters
        # We need to create new TaskParameters object with substituted values
        from .models import TaskParameters
        
        # Create new parameters object with substituted values
        task.parameters = TaskParameters(**substituted_params)
        
        logger.info(f"Parameter substitution completed for task {task.id}. Final parameters: {task.parameters.to_dict()}")
    
    async def _complete_workflow(self, workflow_id: str):
        """Handle workflow completion"""
        if workflow_id not in self.workflows:
            return
        
        workflow = self.workflows[workflow_id]
        
        # Determine final status
        if workflow.failed_tasks and workflow.error_strategy == "stop":
            final_status = WorkflowStatus.FAILED
        elif len(workflow.completed_tasks) + len(workflow.failed_tasks) >= len(workflow.tasks):
            final_status = WorkflowStatus.COMPLETED
        else:
            return  # Not actually complete
        
        # Update workflow
        workflow.status = final_status
        workflow.completed_at = datetime.utcnow()
        
        # Persist completion
        await self._update_workflow_status(workflow_id, final_status)
        
        # Broadcast completion via orchestration server
        if self._server:
            logger.info(f"Broadcasting workflow completion: {workflow_id}, status={final_status.value}, results={workflow.task_results}")
            await self._server.broadcast_workflow_completed(
                workflow_id=workflow_id,
                status=final_status.value,
                results=workflow.task_results
            )
        else:
            logger.warning(f"No server reference to broadcast workflow completion for {workflow_id}")
        
        logger.info(f"Workflow {final_status.value}: {workflow_id}")
    
    async def _fail_workflow(self, workflow_id: str, reason: str):
        """Handle workflow failure"""
        if workflow_id not in self.workflows:
            return
        
        workflow = self.workflows[workflow_id]
        workflow.status = WorkflowStatus.FAILED
        workflow.completed_at = datetime.utcnow()
        
        # Cancel remaining tasks
        await self.cancel_workflow(workflow_id)
        
        # Persist failure
        await self._update_workflow_status(workflow_id, WorkflowStatus.FAILED)
        
        # Broadcast failure
        if self._server:
            await self._server.broadcast_workflow_completed(
                workflow_id=workflow_id,
                status='failed',
                results={'error': reason}
            )
        
        logger.warning(f"Workflow failed: {workflow_id} - {reason}")
    
    async def _update_workflow_status(self, workflow_id: str, status: WorkflowStatus):
        """Update workflow status in Redis"""
        await self.redis_client.update_workflow_status(workflow_id, status)
    
    async def _update_workflow_progress(self, workflow_id: str):
        """Update workflow progress in Redis"""
        if workflow_id in self.workflows:
            workflow = self.workflows[workflow_id]
            progress = workflow.get_progress()
            await self.redis_client.update_workflow_progress(workflow_id, progress)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get workflow engine statistics"""
        active_workflows = len([w for w in self.workflows.values() if w.status == WorkflowStatus.RUNNING])
        completed_workflows = len([w for w in self.workflows.values() if w.status == WorkflowStatus.COMPLETED])
        failed_workflows = len([w for w in self.workflows.values() if w.status == WorkflowStatus.FAILED])
        
        return {
            'running': self._running,
            'total_workflows': len(self.workflows),
            'active_workflows': active_workflows,
            'completed_workflows': completed_workflows,
            'failed_workflows': failed_workflows,
            'task_assignments': len(self.task_assignments)
        }