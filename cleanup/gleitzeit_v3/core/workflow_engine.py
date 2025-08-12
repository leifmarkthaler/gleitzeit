"""
Event-Driven Workflow Engine for Gleitzeit V3

Pure event-driven workflow orchestration with:
- Reactive task scheduling
- Event-based state management
- Real-time dependency resolution
- Automatic parameter substitution
- Comprehensive audit trails
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional, Any, Set
from datetime import datetime

from ..events.bus import EventBus, EventFilter
from ..events.schemas import EventType, EventEnvelope, create_event, EventSeverity
from .models import Workflow, Task, TaskStatus, WorkflowStatus, Provider, TaskParameters

logger = logging.getLogger(__name__)


class EventDrivenWorkflowEngine:
    """
    Completely event-driven workflow engine.
    
    No polling, no manual state checking - everything is reactive to events.
    All workflow and task state changes happen through events.
    """
    
    def __init__(
        self,
        component_id: str = "workflow_engine",
        event_bus: Optional[EventBus] = None
    ):
        self.component_id = component_id
        self.event_bus = event_bus
        
        # Active workflows and tasks
        self.workflows: Dict[str, Workflow] = {}
        self.tasks: Dict[str, Task] = {}
        self.providers: Dict[str, Provider] = {}
        
        # Dependency tracking
        self.task_dependencies: Dict[str, Set[str]] = {}  # task_id -> dependency_task_ids
        self.dependent_tasks: Dict[str, Set[str]] = {}    # task_id -> tasks_waiting_on_it
        
        # Assignment tracking
        self.pending_assignments: Set[str] = set()  # task_ids waiting for assignment
        
        # Running state
        self._running = False
        
        logger.info(f"EventDrivenWorkflowEngine initialized: {component_id}")
    
    async def start(self):
        """Start the workflow engine and subscribe to events"""
        if self._running:
            return
        
        if not self.event_bus:
            raise ValueError("Event bus not configured")
        
        # Subscribe to relevant events
        await self._setup_event_subscriptions()
        
        self._running = True
        logger.info("🚀 EventDrivenWorkflowEngine started")
        
        # Emit component started event
        await self._emit_event(
            EventType.COMPONENT_STARTED,
            {"component_id": self.component_id, "component_type": "workflow_engine"}
        )
    
    async def stop(self):
        """Stop the workflow engine"""
        if not self._running:
            return
        
        self._running = False
        logger.info("🛑 EventDrivenWorkflowEngine stopped")
        
        # Emit component stopped event
        await self._emit_event(
            EventType.COMPONENT_STOPPED,
            {"component_id": self.component_id}
        )
    
    async def _setup_event_subscriptions(self):
        """Subscribe to all relevant events"""
        
        # Workflow events
        self.event_bus.subscribe(
            self._handle_workflow_submitted,
            event_types=[EventType.WORKFLOW_SUBMITTED]
        )
        
        # Task events
        self.event_bus.subscribe(
            self._handle_task_completed,
            event_types=[EventType.TASK_COMPLETED]
        )
        
        self.event_bus.subscribe(
            self._handle_task_failed,
            event_types=[EventType.TASK_FAILED]
        )
        
        # Provider events
        self.event_bus.subscribe(
            self._handle_provider_registered,
            event_types=[EventType.PROVIDER_REGISTERED]
        )
        
        self.event_bus.subscribe(
            self._handle_provider_available,
            event_types=[EventType.PROVIDER_AVAILABLE]
        )
        
        self.event_bus.subscribe(
            self._handle_provider_disconnected,
            event_types=[EventType.PROVIDER_DISCONNECTED]
        )
        
        # Assignment events
        self.event_bus.subscribe(
            self._handle_assignment_requested,
            event_types=[EventType.ASSIGNMENT_REQUESTED]
        )
        
        self.event_bus.subscribe(
            self._handle_assignment_approved,
            event_types=[EventType.ASSIGNMENT_APPROVED]
        )
        
        # Task state events
        self.event_bus.subscribe(
            self._handle_task_ready,
            event_types=[EventType.TASK_READY]
        )
        
        # Parameter resolution events
        self.event_bus.subscribe(
            self._handle_parameters_resolve_requested,
            event_types=[EventType.PARAMETERS_RESOLVE_REQUESTED]
        )
        
        logger.info("Event subscriptions configured")
    
    async def _handle_task_ready(self, event: EventEnvelope):
        """Handle task ready events and trigger assignment"""
        task_id = event.task_id
        if task_id:
            logger.info(f"Task ready event received for: {task_id}")
            await self._check_for_assignment_opportunities()
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit a workflow for execution"""
        try:
            logger.info(f"Submitting workflow: {workflow.name} ({workflow.id})")
            
            # Configure models for event emission
            await self._configure_workflow_for_events(workflow)
            
            # Store workflow
            self.workflows[workflow.id] = workflow
            
            # Store tasks and build dependency graph
            await self._process_workflow_tasks(workflow)
            
            # Set workflow status to queued
            await workflow.set_status(WorkflowStatus.QUEUED)
            
            # Emit workflow submitted event
            await self._emit_event(
                EventType.WORKFLOW_SUBMITTED,
                {
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "task_count": len(workflow.tasks),
                    "client_id": "system",  # TODO: get from context
                    "priority": workflow.priority
                },
                workflow_id=workflow.id
            )
            
            # Start workflow execution
            await workflow.set_status(WorkflowStatus.RUNNING)
            await self._check_workflow_for_ready_tasks(workflow.id)
            
            logger.info(f"Workflow submitted successfully: {workflow.id}")
            return workflow.id
            
        except Exception as e:
            logger.error(f"Failed to submit workflow {workflow.id}: {e}")
            if workflow.id in self.workflows:
                await self.workflows[workflow.id].set_status(WorkflowStatus.FAILED)
            raise
    
    async def _configure_workflow_for_events(self, workflow: Workflow):
        """Configure workflow and tasks to emit events"""
        workflow.set_event_bus(self.event_bus, self.component_id)
        
        for task in workflow.tasks:
            task.set_event_bus(self.event_bus, self.component_id)
    
    async def _process_workflow_tasks(self, workflow: Workflow):
        """Process workflow tasks and build dependency graph"""
        for task in workflow.tasks:
            # Store task
            self.tasks[task.id] = task
            
            # Build dependency graph
            if task.dependencies:
                self.task_dependencies[task.id] = set(task.dependencies)
                
                # Build reverse dependency mapping
                for dep_id in task.dependencies:
                    if dep_id not in self.dependent_tasks:
                        self.dependent_tasks[dep_id] = set()
                    self.dependent_tasks[dep_id].add(task.id)
            
            # Emit task created event
            await self._emit_event(
                EventType.TASK_CREATED,
                {
                    "task_id": task.id,
                    "task_name": task.name,
                    "function": task.parameters.get('function', 'unknown'),
                    "workflow_id": workflow.id,
                    "dependencies": task.dependencies,
                    "priority": task.priority
                },
                task_id=task.id,
                workflow_id=workflow.id
            )
    
    async def _check_workflow_for_ready_tasks(self, workflow_id: str):
        """Check workflow for tasks that are ready to execute"""
        if workflow_id not in self.workflows:
            return
        
        workflow = self.workflows[workflow_id]
        ready_tasks = []
        
        for task in workflow.tasks:
            if task.status == TaskStatus.CREATED:
                if await self._are_task_dependencies_satisfied(task.id):
                    ready_tasks.append(task)
        
        # Mark ready tasks as ready (this will emit events)
        for task in ready_tasks:
            await task.set_status(TaskStatus.READY)
            logger.info(f"Task {task.id} is ready for execution")
    
    async def _are_task_dependencies_satisfied(self, task_id: str) -> bool:
        """Check if all task dependencies are completed"""
        if task_id not in self.task_dependencies:
            return True  # No dependencies
        
        workflow_id = self.tasks[task_id].workflow_id
        if not workflow_id or workflow_id not in self.workflows:
            return False
        
        workflow = self.workflows[workflow_id]
        
        for dep_id in self.task_dependencies[task_id]:
            if dep_id not in workflow.completed_tasks:
                return False
        
        return True
    
    # Event Handlers
    
    async def _handle_workflow_submitted(self, event: EventEnvelope):
        """Handle workflow submitted event from external sources"""
        # This might be called if workflows are submitted through other channels
        pass
    
    async def _handle_task_completed(self, event: EventEnvelope):
        """Handle task completion events"""
        task_id = event.task_id
        workflow_id = event.workflow_id
        
        if not task_id or not workflow_id:
            logger.warning(f"Task completed event missing IDs: {event.event_id}")
            return
        
        logger.info(f"Handling task completion: {task_id}")
        
        try:
            # Update workflow state
            if workflow_id in self.workflows:
                workflow = self.workflows[workflow_id]
                
                if task_id not in workflow.completed_tasks:
                    workflow.completed_tasks.append(task_id)
                
                # Store task result
                if task_id in self.tasks:
                    task = self.tasks[task_id]
                    workflow.task_results[task_id] = task.result
                
                # Check for newly ready tasks
                await self._check_dependent_tasks(task_id)
                
                # Check if workflow is complete
                if workflow.is_complete():
                    await workflow.set_status(WorkflowStatus.COMPLETED)
                    await self._emit_audit_event("workflow_completed", {
                        "workflow_id": workflow_id,
                        "duration_seconds": (
                            (workflow.completed_at - workflow.started_at).total_seconds()
                            if workflow.started_at and workflow.completed_at else 0
                        )
                    })
            
        except Exception as e:
            logger.error(f"Error handling task completion {task_id}: {e}")
    
    async def _handle_task_failed(self, event: EventEnvelope):
        """Handle task failure events"""
        task_id = event.task_id
        workflow_id = event.workflow_id
        
        if not task_id or not workflow_id:
            logger.warning(f"Task failed event missing IDs: {event.event_id}")
            return
        
        logger.warning(f"Handling task failure: {task_id}")
        
        try:
            # Update workflow state
            if workflow_id in self.workflows:
                workflow = self.workflows[workflow_id]
                
                if task_id not in workflow.failed_tasks:
                    workflow.failed_tasks.append(task_id)
                
                # Handle based on error strategy
                if workflow.error_strategy == "stop":
                    await workflow.set_status(WorkflowStatus.FAILED)
                elif workflow.error_strategy == "continue":
                    # Check if workflow can still complete
                    if workflow.is_complete():
                        await workflow.set_status(WorkflowStatus.COMPLETED)
                
                await self._emit_audit_event("task_failed", {
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "error_strategy": workflow.error_strategy
                })
        
        except Exception as e:
            logger.error(f"Error handling task failure {task_id}: {e}")
    
    async def _check_dependent_tasks(self, completed_task_id: str):
        """Check tasks that depend on the completed task"""
        if completed_task_id not in self.dependent_tasks:
            return
        
        # Check each task that depends on this one
        for dependent_task_id in self.dependent_tasks[completed_task_id]:
            if dependent_task_id in self.tasks:
                task = self.tasks[dependent_task_id]
                
                if task.status == TaskStatus.CREATED:
                    # Check if all dependencies are now satisfied
                    if await self._are_task_dependencies_satisfied(dependent_task_id):
                        await task.set_status(TaskStatus.READY)
                        logger.info(f"Task {dependent_task_id} became ready after {completed_task_id} completion")
    
    async def _handle_provider_registered(self, event: EventEnvelope):
        """Handle provider registration events"""
        payload = event.payload
        provider_id = payload.get("provider_id")
        
        if not provider_id:
            return
        
        # Create or update provider object
        if provider_id not in self.providers:
            provider = Provider(
                id=provider_id,
                name=payload.get("provider_name", f"Provider_{provider_id}"),
                provider_type=payload.get("provider_type", "unknown"),
                supported_functions=set(payload.get("supported_functions", [])),
                version=payload.get("version", "1.0.0")
            )
            provider.set_event_bus(self.event_bus, self.component_id)
            self.providers[provider_id] = provider
        else:
            # Update existing provider with latest info
            provider = self.providers[provider_id]
            provider.name = payload.get("provider_name", provider.name)
            provider.provider_type = payload.get("provider_type", provider.provider_type)
            provider.supported_functions = set(payload.get("supported_functions", []))
            provider.version = payload.get("version", provider.version)
        
        logger.info(f"Provider registered: {provider_id}")
        
        # Trigger assignment check for waiting tasks
        await self._check_for_assignment_opportunities()
    
    async def _handle_provider_available(self, event: EventEnvelope):
        """Handle provider available events"""
        provider_id = event.provider_id
        
        if provider_id and provider_id in self.providers:
            provider = self.providers[provider_id]
            logger.info(f"Provider available: {provider_id} (status: {provider.status}, functions: {provider.supported_functions})")
            await self._check_for_assignment_opportunities()
    
    async def _handle_provider_disconnected(self, event: EventEnvelope):
        """Handle provider disconnection events"""
        provider_id = event.provider_id
        
        if provider_id and provider_id in self.providers:
            # Mark provider as disconnected
            provider = self.providers[provider_id]
            await provider.set_status(provider.status.DISCONNECTED)
            
            # Reassign any running tasks from this provider
            await self._reassign_provider_tasks(provider_id)
            
            logger.warning(f"Provider disconnected: {provider_id}")
    
    async def _reassign_provider_tasks(self, provider_id: str):
        """Reassign tasks from a disconnected provider"""
        # Find tasks assigned to this provider
        tasks_to_reassign = [
            task for task in self.tasks.values()
            if task.provider_id == provider_id and task.status in [TaskStatus.ASSIGNED, TaskStatus.RUNNING]
        ]
        
        for task in tasks_to_reassign:
            # Reset task status
            task.provider_id = None
            await task.set_status(TaskStatus.READY, reason="provider_disconnected")
            logger.info(f"Reassigning task {task.id} due to provider disconnection")
    
    async def _check_for_assignment_opportunities(self):
        """Check if any ready tasks can be assigned to available providers"""
        # Get ready tasks
        ready_tasks = [
            task for task in self.tasks.values()
            if task.status == TaskStatus.READY and task.id not in self.pending_assignments
        ]
        
        # Also check pending assignments that couldn't be assigned before
        pending_tasks = [
            task for task in self.tasks.values()
            if task.id in self.pending_assignments and task.status == TaskStatus.READY
        ]
        
        all_tasks_to_check = ready_tasks + pending_tasks
        logger.info(f"Checking assignments: {len(ready_tasks)} new ready tasks, {len(pending_tasks)} pending tasks, {len(self.providers)} providers")
        
        if not all_tasks_to_check:
            return
        
        # Emit assignment requests for all tasks to check
        for task in all_tasks_to_check:
            await self._request_task_assignment(task)
    
    async def _request_task_assignment(self, task: Task):
        """Request assignment for a task"""
        # Only add to pending if not already there (to avoid duplicate requests)
        was_pending = task.id in self.pending_assignments
        self.pending_assignments.add(task.id)
        
        if was_pending:
            logger.info(f"Retrying assignment for pending task: {task.id}")
        else:
            logger.info(f"Requesting assignment for new task: {task.id}")
        
        await self._emit_event(
            EventType.ASSIGNMENT_REQUESTED,
            {
                "task_id": task.id,
                "function": task.parameters.get('function', 'unknown'),
                "requirements": {
                    "function": task.parameters.get('function'),
                    "priority": task.priority
                },
                "priority": task.priority
            },
            task_id=task.id,
            workflow_id=task.workflow_id
        )
    
    async def _handle_assignment_requested(self, event: EventEnvelope):
        """Handle assignment request events"""
        task_id = event.task_id
        
        if not task_id or task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        
        # Find suitable providers
        suitable_providers = []
        for provider in self.providers.values():
            if provider.can_handle_task(task):
                # Calculate compatibility score
                score = self._calculate_compatibility_score(task, provider)
                suitable_providers.append((provider, score))
        
        if not suitable_providers:
            logger.warning(f"No suitable providers found for task {task_id} - keeping in pending assignments")
            # Keep task in pending_assignments so it can be retried when providers become available
            return
        
        # Sort by score (highest first)
        suitable_providers.sort(key=lambda x: x[1], reverse=True)
        best_provider, score = suitable_providers[0]
        
        # Emit candidate found event
        await self._emit_event(
            EventType.ASSIGNMENT_CANDIDATE_FOUND,
            {
                "task_id": task_id,
                "provider_id": best_provider.id,
                "compatibility_score": score
            },
            task_id=task_id,
            workflow_id=task.workflow_id,
            provider_id=best_provider.id
        )
        
        # For now, auto-approve the best candidate
        await self._approve_assignment(task_id, best_provider.id)
    
    def _calculate_compatibility_score(self, task: Task, provider: Provider) -> float:
        """Calculate compatibility score between task and provider"""
        base_score = 0.5
        
        # Function compatibility
        function_name = task.parameters.get('function')
        if function_name and function_name in provider.supported_functions:
            base_score += 0.3
        
        # Load factor (prefer less loaded providers)
        load_factor = 1.0 - (provider.current_tasks / provider.max_concurrent_tasks)
        base_score += load_factor * 0.2
        
        # Health score
        base_score += provider.health_score * 0.1
        
        # Success rate
        base_score += provider.success_rate * 0.1
        
        return min(base_score, 1.0)
    
    async def _approve_assignment(self, task_id: str, provider_id: str):
        """Approve a task assignment"""
        await self._emit_event(
            EventType.ASSIGNMENT_APPROVED,
            {
                "task_id": task_id,
                "provider_id": provider_id,
                "assignment_timestamp": datetime.utcnow().isoformat()
            },
            task_id=task_id,
            workflow_id=self.tasks[task_id].workflow_id,
            provider_id=provider_id
        )
    
    async def _handle_assignment_approved(self, event: EventEnvelope):
        """Handle assignment approval events"""
        task_id = event.task_id
        provider_id = event.provider_id
        
        if not task_id or not provider_id:
            return
        
        if task_id not in self.tasks or provider_id not in self.providers:
            return
        
        task = self.tasks[task_id]
        provider = self.providers[provider_id]
        
        # Remove from pending assignments
        self.pending_assignments.discard(task_id)
        
        # Assign task to provider
        await task.assign_to_provider(provider_id)
        
        # Update provider load
        provider.current_tasks += 1
        if provider.current_tasks >= provider.max_concurrent_tasks:
            await provider.set_status(provider.status.BUSY)
        
        # Request parameter resolution
        await self._emit_event(
            EventType.PARAMETERS_RESOLVE_REQUESTED,
            {
                "task_id": task_id,
                "original_parameters": task.parameters.to_dict(),
                "dependency_tasks": task.dependencies
            },
            task_id=task_id,
            workflow_id=task.workflow_id
        )
        
        logger.info(f"Task {task_id} assigned to provider {provider_id}")
    
    async def _handle_parameters_resolve_requested(self, event: EventEnvelope):
        """Handle parameter resolution requests"""
        task_id = event.task_id
        
        if not task_id or task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        workflow_id = task.workflow_id
        
        if not workflow_id or workflow_id not in self.workflows:
            return
        
        workflow = self.workflows[workflow_id]
        
        try:
            # Perform parameter substitution
            original_params = task.parameters.to_dict()
            resolved_params = await self._substitute_parameters(
                original_params, 
                workflow.task_results
            )
            
            substitutions = {}
            if resolved_params != original_params:
                # Track what was substituted
                substitutions = self._find_substitutions(original_params, resolved_params)
            
            # Update task parameters
            task.parameters = TaskParameters(data=resolved_params)
            
            # Emit parameters resolved event
            await self._emit_event(
                EventType.PARAMETERS_RESOLVED,
                {
                    "task_id": task_id,
                    "original_parameters": original_params,
                    "resolved_parameters": resolved_params,
                    "substitutions_made": substitutions
                },
                task_id=task_id,
                workflow_id=workflow_id
            )
            
            # Execute the task
            await self._execute_task(task)
            
        except Exception as e:
            logger.error(f"Parameter resolution failed for task {task_id}: {e}")
            
            # Emit resolution failed event
            await self._emit_event(
                EventType.PARAMETERS_RESOLUTION_FAILED,
                {
                    "task_id": task_id,
                    "missing_dependencies": task.dependencies,
                    "error_message": str(e)
                },
                task_id=task_id,
                workflow_id=workflow_id,
                severity=EventSeverity.ERROR
            )
    
    async def _substitute_parameters(
        self, 
        params: Dict[str, Any], 
        task_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Substitute parameter patterns with actual values"""
        
        def substitute_string(text: str) -> str:
            if not isinstance(text, str):
                return text
            
            # Pattern: ${task_TASKID_result}
            pattern = r'\$\{task_([a-f0-9\-]+)_result\}'
            
            def replace_match(match):
                task_id = match.group(1)
                if task_id in task_results:
                    result = task_results[task_id]
                    return str(result) if result is not None else ''
                return match.group(0)  # Return original if not found
            
            return re.sub(pattern, replace_match, text)
        
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
        
        return substitute_recursive(params)
    
    def _find_substitutions(
        self, 
        original: Dict[str, Any], 
        resolved: Dict[str, Any]
    ) -> Dict[str, str]:
        """Find what substitutions were made"""
        substitutions = {}
        
        def compare_recursive(orig, res, path=""):
            if isinstance(orig, dict) and isinstance(res, dict):
                for key in orig:
                    new_path = f"{path}.{key}" if path else key
                    if key in res:
                        compare_recursive(orig[key], res[key], new_path)
            elif isinstance(orig, str) and isinstance(res, str) and orig != res:
                # Found a substitution
                pattern_match = re.search(r'\$\{task_([a-f0-9\-]+)_result\}', orig)
                if pattern_match:
                    substitutions[f"{path}:{orig}"] = res
        
        compare_recursive(original, resolved)
        return substitutions
    
    async def _execute_task(self, task: Task):
        """Execute a task by sending it to the assigned provider"""
        if not task.provider_id or task.provider_id not in self.providers:
            logger.error(f"Cannot execute task {task.id}: no valid provider")
            return
        
        provider = self.providers[task.provider_id]
        
        # Mark task as running
        await task.set_status(TaskStatus.RUNNING)
        
        # Emit assignment executed event
        await self._emit_event(
            EventType.ASSIGNMENT_EXECUTED,
            {
                "task_id": task.id,
                "provider_id": provider.id,
                "function": task.parameters.get('function', 'unknown'),
                "parameters": task.parameters.to_dict(),
                "execution_timestamp": datetime.utcnow().isoformat()
            },
            task_id=task.id,
            workflow_id=task.workflow_id,
            provider_id=provider.id
        )
        
        # TODO: Send task to provider via socket.io or other transport
        # For now, emit a placeholder event
        await self._emit_event(
            EventType.AUDIT_TASK_ASSIGNED,
            {
                "task_id": task.id,
                "provider_id": provider.id,
                "assignment_reason": "event_driven_scheduling",
                "assignment_context": {
                    "function": task.parameters.get('function', 'unknown'),
                    "parameters_resolved": True
                }
            },
            task_id=task.id,
            workflow_id=task.workflow_id,
            provider_id=provider.id
        )
        
        logger.info(f"Task {task.id} sent for execution to provider {provider.id}")
    
    async def _emit_event(self, event_type: EventType, payload: Dict[str, Any], **kwargs):
        """Emit an event through the event bus"""
        if self.event_bus:
            event = create_event(
                event_type=event_type,
                source_component=self.component_id,
                payload=payload,
                **kwargs
            )
            await self.event_bus.publish(event)
    
    async def _emit_audit_event(self, audit_type: str, context: Dict[str, Any]):
        """Emit an audit event"""
        event_type_map = {
            "workflow_completed": EventType.AUDIT_WORKFLOW_CREATED,
            "task_failed": EventType.AUDIT_ERROR_OCCURRED
        }
        
        event_type = event_type_map.get(audit_type, EventType.AUDIT_ERROR_OCCURRED)
        
        await self._emit_event(
            event_type,
            {
                "audit_type": audit_type,
                "context": context,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get workflow engine statistics"""
        return {
            "component_id": self.component_id,
            "running": self._running,
            "total_workflows": len(self.workflows),
            "active_workflows": len([
                w for w in self.workflows.values() 
                if w.status == WorkflowStatus.RUNNING
            ]),
            "total_tasks": len(self.tasks),
            "ready_tasks": len([
                t for t in self.tasks.values() 
                if t.status == TaskStatus.READY
            ]),
            "running_tasks": len([
                t for t in self.tasks.values() 
                if t.status == TaskStatus.RUNNING
            ]),
            "total_providers": len(self.providers),
            "available_providers": len([
                p for p in self.providers.values() 
                if p.status == p.status.AVAILABLE
            ]),
            "pending_assignments": len(self.pending_assignments)
        }