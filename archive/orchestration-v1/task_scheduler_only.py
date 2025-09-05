"""
Minimal Task Scheduler that works with existing EventDrivenWorkflowManager

This component ONLY handles task scheduling and dependency resolution,
delegating all workflow state management to the existing EventDrivenWorkflowManager.
"""

import asyncio
import logging
import json
from typing import Dict, Set, List, Optional, Any
from datetime import datetime

from gleitzeit.core.models import Workflow, Task, TaskStatus
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType

logger = logging.getLogger(__name__)


class TaskSchedulerOnly:
    """
    Minimal task scheduler that works with existing workflow management.
    
    This component:
    - Listens for WORKFLOW_SUBMITTED events
    - Listens for TASK_COMPLETED events
    - Schedules tasks when dependencies are met
    - Does NOT track workflow state (EventDrivenWorkflowManager does that)
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        event_bus: EventBus,
        node_id: str = "scheduler-1"
    ):
        self.persistence = persistence
        self.event_bus = event_bus
        self.node_id = node_id
        
        # Track dependency graphs for active workflows
        self.dependency_graphs: Dict[str, Dict[str, Set[str]]] = {}
        
        # Register for events we need
        self._register_handlers()
        
        logger.info(f"TaskSchedulerOnly initialized: {node_id}")
    
    def _register_handlers(self):
        """Register event handlers"""
        self.event_bus.register(EventType.WORKFLOW_SUBMITTED, self._on_workflow_submitted)
        self.event_bus.register(EventType.TASK_COMPLETED, self._on_task_completed)
        self.event_bus.register(EventType.TASK_FAILED, self._on_task_failed)
        self.event_bus.register(EventType.WORKFLOW_COMPLETED, self._on_workflow_completed)
        self.event_bus.register(EventType.WORKFLOW_FAILED, self._on_workflow_failed)
        
    async def _on_workflow_submitted(self, event: GleitzeitEvent):
        """Handle workflow submission - build dependency graph and schedule initial tasks"""
        workflow_id = event.data.get('workflow_id')
        if not workflow_id:
            return
            
        logger.info(f"Scheduling tasks for workflow {workflow_id}")
        
        # Get workflow from persistence
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            logger.error(f"Workflow {workflow_id} not found")
            return
        
        # Build dependency graph
        dep_graph = self._build_dependency_graph(workflow)
        self.dependency_graphs[workflow_id] = dep_graph
        
        # Schedule tasks with no dependencies
        await self._schedule_ready_tasks(workflow_id)
    
    def _build_dependency_graph(self, workflow: Workflow) -> Dict[str, Set[str]]:
        """Build dependency graph for workflow"""
        graph = {}
        for task in workflow.tasks:
            graph[task.id] = set(task.dependencies) if task.dependencies else set()
        return graph
    
    async def _schedule_ready_tasks(self, workflow_id: str):
        """Schedule tasks that have their dependencies met"""
        dep_graph = self.dependency_graphs.get(workflow_id)
        if not dep_graph:
            return
            
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return
        
        scheduled_count = 0
        
        for task in workflow.tasks:
            # Skip if already processed
            task_result = await self.persistence.get_task_result(task.id)
            if task_result and task_result.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.EXECUTING]:
                continue
            
            # Check if task is already queued
            task_obj = await self.persistence.get_task(task.id)
            if task_obj and task_obj.status in [TaskStatus.QUEUED, TaskStatus.EXECUTING]:
                continue
            
            # Check dependencies
            dependencies = dep_graph.get(task.id, set())
            deps_met = await self._check_dependencies_met(dependencies)
            
            if deps_met:
                # Queue task for execution
                await self._queue_task(task, workflow_id)
                scheduled_count += 1
        
        if scheduled_count > 0:
            logger.info(f"Scheduled {scheduled_count} tasks for workflow {workflow_id}")
    
    async def _check_dependencies_met(self, dependencies: Set[str]) -> bool:
        """Check if all dependencies are completed"""
        if not dependencies:
            return True
            
        for dep_id in dependencies:
            result = await self.persistence.get_task_result(dep_id)
            if not result or result.status != TaskStatus.COMPLETED:
                return False
        return True
    
    async def _queue_task(self, task: Task, workflow_id: str):
        """Queue task for execution"""
        # Update task status
        task.status = TaskStatus.QUEUED
        await self.persistence.save_task(task)
        
        # Queue to provider-specific queue (if using Redis)
        if hasattr(self.persistence, 'redis'):
            task_data = {
                "task_id": task.id,
                "workflow_id": workflow_id,
                "protocol": task.protocol,
                "method": task.method,
                "params": task.params,
                "metadata": task.metadata or {},
                "timeout": task.timeout,
                "queued_at": datetime.utcnow().isoformat()
            }
            
            queue_key = f"provider:queue:{task.protocol}"
            await self.persistence.redis.lpush(queue_key, json.dumps(task_data))
            logger.debug(f"Queued task {task.id} to {queue_key}")
        
        # Emit TASK_READY event for compatibility
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_READY,
            data={
                "task_id": task.id,
                "workflow_id": workflow_id,
                "protocol": task.protocol,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
    
    async def _on_task_completed(self, event: GleitzeitEvent):
        """Handle task completion - check for newly ready tasks"""
        workflow_id = event.data.get('workflow_id')
        if not workflow_id or workflow_id not in self.dependency_graphs:
            return
        
        # Schedule any tasks that now have dependencies met
        await self._schedule_ready_tasks(workflow_id)
    
    async def _on_task_failed(self, event: GleitzeitEvent):
        """Handle task failure - may affect dependent tasks"""
        workflow_id = event.data.get('workflow_id')
        is_permanent = event.data.get('is_permanent', False)
        
        if not workflow_id or not is_permanent:
            return
        
        # If permanent failure, we might need to handle dependent tasks
        # For now, let EventDrivenWorkflowManager handle workflow failure
        logger.debug(f"Task permanently failed in workflow {workflow_id}")
    
    async def _on_workflow_completed(self, event: GleitzeitEvent):
        """Clean up when workflow completes"""
        workflow_id = event.data.get('workflow_id')
        if workflow_id in self.dependency_graphs:
            del self.dependency_graphs[workflow_id]
            logger.debug(f"Cleaned up dependency graph for completed workflow {workflow_id}")
    
    async def _on_workflow_failed(self, event: GleitzeitEvent):
        """Clean up when workflow fails"""
        workflow_id = event.data.get('workflow_id')
        if workflow_id in self.dependency_graphs:
            del self.dependency_graphs[workflow_id]
            logger.debug(f"Cleaned up dependency graph for failed workflow {workflow_id}")


class LightweightOrchestrator:
    """
    Lightweight orchestrator that combines existing components with new scheduler.
    
    Uses:
    - EventDrivenWorkflowManager for workflow state tracking
    - TaskSchedulerOnly for dependency resolution and task scheduling
    - ProviderPullAdapter for task execution
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        event_bus: EventBus,
        node_id: str = "orchestrator-1"
    ):
        self.persistence = persistence
        self.event_bus = event_bus
        self.node_id = node_id
        
        # Use existing workflow manager for state tracking
        from gleitzeit.core.event_driven_workflow_manager import EventDrivenWorkflowManager
        self.workflow_manager = EventDrivenWorkflowManager(persistence, event_bus)
        
        # Add our scheduler for task scheduling
        self.task_scheduler = TaskSchedulerOnly(persistence, event_bus, f"{node_id}-scheduler")
        
        logger.info(f"LightweightOrchestrator initialized: {node_id}")
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit workflow for execution"""
        # Save workflow to persistence
        await self.persistence.save_workflow(workflow)
        
        # Emit WORKFLOW_SUBMITTED event
        # Both EventDrivenWorkflowManager and TaskSchedulerOnly will handle it
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.WORKFLOW_SUBMITTED,
            data={
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "task_count": len(workflow.tasks),
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        logger.info(f"Submitted workflow {workflow.id} via lightweight orchestrator")
        return workflow.id
    
    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow status from persistence"""
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return None
        
        # Count task statuses
        total_tasks = len(workflow.tasks)
        completed_tasks = 0
        failed_tasks = 0
        running_tasks = 0
        
        for task in workflow.tasks:
            result = await self.persistence.get_task_result(task.id)
            if result:
                if result.status == TaskStatus.COMPLETED:
                    completed_tasks += 1
                elif result.status == TaskStatus.FAILED:
                    failed_tasks += 1
                elif result.status == TaskStatus.EXECUTING:
                    running_tasks += 1
        
        return {
            "workflow_id": workflow_id,
            "status": workflow.status.value,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "running_tasks": running_tasks,
            "progress": completed_tasks / total_tasks if total_tasks > 0 else 0,
            "started_at": workflow.started_at.isoformat() if workflow.started_at else None,
            "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None
        }