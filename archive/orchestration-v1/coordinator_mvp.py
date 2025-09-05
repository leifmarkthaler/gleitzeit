"""
Minimal Workflow Coordinator for MVP implementation

Single-instance coordinator without leader election for testing
the orchestration architecture before scaling.
"""

import asyncio
import logging
import json
from typing import Dict, Optional, List, Set, Any
from datetime import datetime
from dataclasses import dataclass, field

from gleitzeit.core.models import Workflow, Task, WorkflowStatus, TaskStatus
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType

logger = logging.getLogger(__name__)


@dataclass
class WorkflowState:
    """Track workflow execution state"""
    workflow_id: str
    status: WorkflowStatus
    total_tasks: int
    completed_tasks: Set[str] = field(default_factory=set)
    failed_tasks: Set[str] = field(default_factory=set)
    task_states: Dict[str, TaskStatus] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class WorkflowCoordinatorMVP:
    """
    Minimal Workflow Coordinator - single instance version
    No leader election, direct coordination for MVP testing
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        event_bus: EventBus,
        node_id: str = "coordinator-mvp"
    ):
        self.persistence = persistence
        self.event_bus = event_bus
        self.node_id = node_id
        
        # In-memory tracking (will move to Redis later)
        self.active_workflows: Dict[str, Workflow] = {}
        self.workflow_states: Dict[str, WorkflowState] = {}
        
        # Simple task scheduler (embedded for MVP)
        self.task_scheduler = TaskSchedulerMVP(persistence, event_bus)
        
        # Track dependency graph for each workflow
        self.dependency_graphs: Dict[str, Dict[str, Set[str]]] = {}
        
        # Setup event handlers
        self._setup_event_handlers()
        
        logger.info(f"Initialized WorkflowCoordinatorMVP with node_id: {node_id}")
        
    def _setup_event_handlers(self):
        """Setup event subscriptions"""
        # Register async callable handlers
        self.event_bus.register(EventType.TASK_COMPLETED, self._handle_task_completed)
        self.event_bus.register(EventType.TASK_FAILED, self._handle_task_failed)
        self.event_bus.register(EventType.TASK_STARTED, self._handle_task_started)
        
        logger.debug("Registered event handlers for workflow coordination")
        
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit workflow for execution"""
        logger.info(f"Submitting workflow {workflow.id} with {len(workflow.tasks)} tasks")
        
        # Store workflow
        self.active_workflows[workflow.id] = workflow
        
        # Build dependency graph
        dep_graph = self._build_dependency_graph(workflow)
        self.dependency_graphs[workflow.id] = dep_graph
        
        # Initialize state
        state = WorkflowState(
            workflow_id=workflow.id,
            status=WorkflowStatus.PENDING,
            total_tasks=len(workflow.tasks),
            task_states={t.id: TaskStatus.PENDING for t in workflow.tasks}
        )
        self.workflow_states[workflow.id] = state
        
        # Persist workflow to backend
        await self.persistence.save_workflow(workflow)
        
        # Start coordination
        asyncio.create_task(self._coordinate_workflow(workflow.id))
        
        # Emit workflow submitted event
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.WORKFLOW_SUBMITTED,
            data={
                "workflow_id": workflow.id,
                "task_count": len(workflow.tasks),
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        return workflow.id
    
    def _build_dependency_graph(self, workflow: Workflow) -> Dict[str, Set[str]]:
        """Build dependency graph for workflow"""
        graph = {}
        for task in workflow.tasks:
            graph[task.id] = set(task.dependencies) if task.dependencies else set()
        return graph
    
    async def _coordinate_workflow(self, workflow_id: str):
        """Coordinate workflow execution"""
        workflow = self.active_workflows.get(workflow_id)
        state = self.workflow_states.get(workflow_id)
        
        if not workflow or not state:
            logger.error(f"Workflow {workflow_id} not found")
            return
            
        # Update state to running
        state.status = WorkflowStatus.RUNNING
        state.started_at = datetime.utcnow()
        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = state.started_at
        
        logger.info(f"Starting coordination for workflow {workflow_id}")
        
        # Emit workflow started event
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.WORKFLOW_STARTED,
            data={
                "workflow_id": workflow_id,
                "timestamp": state.started_at.isoformat()
            }
        ))
        
        # Find and schedule ready tasks
        await self._schedule_ready_tasks(workflow_id)
        
    async def _schedule_ready_tasks(self, workflow_id: str):
        """Schedule tasks with no pending dependencies"""
        workflow = self.active_workflows.get(workflow_id)
        state = self.workflow_states.get(workflow_id)
        dep_graph = self.dependency_graphs.get(workflow_id)
        
        if not workflow or not state or not dep_graph:
            return
            
        scheduled_count = 0
        
        for task in workflow.tasks:
            # Skip if not pending
            if state.task_states[task.id] != TaskStatus.PENDING:
                continue
                
            # Check if all dependencies are completed
            dependencies = dep_graph.get(task.id, set())
            deps_met = all(
                state.task_states.get(dep_id) == TaskStatus.COMPLETED
                for dep_id in dependencies
            )
            
            if deps_met:
                # Mark as queued
                state.task_states[task.id] = TaskStatus.QUEUED
                
                # Schedule task
                logger.info(f"Scheduling task {task.id} (deps: {dependencies})")
                await self.task_scheduler.schedule_task(task, workflow_id)
                scheduled_count += 1
                
                # Emit task ready event
                await self.event_bus.emit(GleitzeitEvent(
                    event_type=EventType.TASK_READY,
                    data={
                        "task_id": task.id,
                        "workflow_id": workflow_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                ))
        
        if scheduled_count > 0:
            logger.info(f"Scheduled {scheduled_count} ready tasks for workflow {workflow_id}")
    
    async def _handle_task_started(self, event: GleitzeitEvent):
        """Handle task started event"""
        data = event.data
        task_id = data.get("task_id")
        workflow_id = data.get("workflow_id")
        
        if not workflow_id or workflow_id not in self.workflow_states:
            return
            
        state = self.workflow_states[workflow_id]
        state.task_states[task_id] = TaskStatus.RUNNING
        
        logger.debug(f"Task {task_id} started in workflow {workflow_id}")
    
    async def _handle_task_completed(self, event: GleitzeitEvent):
        """Handle task completion"""
        data = event.data
        task_id = data.get("task_id")
        workflow_id = data.get("workflow_id")
        
        if not workflow_id or workflow_id not in self.workflow_states:
            return
            
        logger.info(f"Task {task_id} completed for workflow {workflow_id}")
        
        state = self.workflow_states[workflow_id]
        state.task_states[task_id] = TaskStatus.COMPLETED
        state.completed_tasks.add(task_id)
        
        # Update workflow progress
        await self._emit_workflow_progress(workflow_id)
        
        # Check for newly ready tasks
        await self._schedule_ready_tasks(workflow_id)
        
        # Check if workflow is complete
        if len(state.completed_tasks) == state.total_tasks:
            await self._complete_workflow(workflow_id)
    
    async def _handle_task_failed(self, event: GleitzeitEvent):
        """Handle task failure"""
        data = event.data
        task_id = data.get("task_id")
        workflow_id = data.get("workflow_id")
        error = data.get("error", "Unknown error")
        
        if not workflow_id or workflow_id not in self.workflow_states:
            return
            
        logger.error(f"Task {task_id} failed for workflow {workflow_id}: {error}")
        
        state = self.workflow_states[workflow_id]
        state.task_states[task_id] = TaskStatus.FAILED
        state.failed_tasks.add(task_id)
        
        # For MVP, fail the workflow on any task failure
        # In production, this would depend on workflow configuration
        await self._fail_workflow(workflow_id, f"Task {task_id} failed: {error}")
    
    async def _complete_workflow(self, workflow_id: str):
        """Mark workflow as completed"""
        logger.info(f"Workflow {workflow_id} completed successfully")
        
        state = self.workflow_states[workflow_id]
        workflow = self.active_workflows[workflow_id]
        
        state.status = WorkflowStatus.COMPLETED
        state.completed_at = datetime.utcnow()
        workflow.status = WorkflowStatus.COMPLETED
        workflow.completed_at = state.completed_at
        
        # Persist final state
        await self.persistence.update_workflow_status(
            workflow_id, 
            WorkflowStatus.COMPLETED
        )
        
        # Emit workflow completed event
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.WORKFLOW_COMPLETED,
            data={
                "workflow_id": workflow_id,
                "completed_tasks": len(state.completed_tasks),
                "duration": (state.completed_at - state.started_at).total_seconds() if state.started_at else 0,
                "timestamp": state.completed_at.isoformat()
            }
        ))
        
        # Cleanup (keep for debugging in MVP)
        # In production, would move to completed storage
        # del self.active_workflows[workflow_id]
    
    async def _fail_workflow(self, workflow_id: str, reason: str):
        """Mark workflow as failed"""
        logger.error(f"Workflow {workflow_id} failed: {reason}")
        
        state = self.workflow_states[workflow_id]
        workflow = self.active_workflows[workflow_id]
        
        state.status = WorkflowStatus.FAILED
        state.error = reason
        state.completed_at = datetime.utcnow()
        workflow.status = WorkflowStatus.FAILED
        workflow.completed_at = state.completed_at
        
        # Persist failure
        await self.persistence.update_workflow_status(
            workflow_id,
            WorkflowStatus.FAILED
        )
        
        # Emit workflow failed event
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.WORKFLOW_FAILED,
            data={
                "workflow_id": workflow_id,
                "reason": reason,
                "completed_tasks": len(state.completed_tasks),
                "failed_tasks": len(state.failed_tasks),
                "timestamp": state.completed_at.isoformat()
            }
        ))
    
    async def _emit_workflow_progress(self, workflow_id: str):
        """Emit workflow progress update"""
        state = self.workflow_states[workflow_id]
        progress = len(state.completed_tasks) / state.total_tasks if state.total_tasks > 0 else 0
        
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.WORKFLOW_PROGRESS,
            data={
                "workflow_id": workflow_id,
                "progress": progress,
                "completed_tasks": len(state.completed_tasks),
                "total_tasks": state.total_tasks,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
    
    def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get current workflow status"""
        state = self.workflow_states.get(workflow_id)
        if not state:
            return None
            
        return {
            "workflow_id": workflow_id,
            "status": state.status.value,
            "progress": len(state.completed_tasks) / state.total_tasks if state.total_tasks > 0 else 0,
            "completed_tasks": len(state.completed_tasks),
            "failed_tasks": len(state.failed_tasks),
            "total_tasks": state.total_tasks,
            "task_states": {k: v.value for k, v in state.task_states.items()},
            "started_at": state.started_at.isoformat() if state.started_at else None,
            "completed_at": state.completed_at.isoformat() if state.completed_at else None,
            "error": state.error
        }


class TaskSchedulerMVP:
    """
    Minimal Task Scheduler - embedded in coordinator for MVP
    Uses Redis queues for provider pull model
    """
    
    def __init__(self, persistence: PersistenceBackend, event_bus: EventBus):
        self.persistence = persistence
        self.event_bus = event_bus
        logger.info("Initialized TaskSchedulerMVP")
        
    async def schedule_task(self, task: Task, workflow_id: str):
        """Schedule task for execution via provider queue"""
        # Prepare task data for queue
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
        
        # Determine queue based on protocol
        queue_key = f"provider:queue:{task.protocol}"
        
        # Add to Redis queue for providers to pull
        # Using LPUSH for FIFO ordering (providers BRPOP from other end)
        if hasattr(self.persistence, 'redis'):
            # Direct Redis access
            await self.persistence.redis.lpush(queue_key, json.dumps(task_data))
        else:
            # Fallback to persistence backend method if available
            # For MVP, we assume Redis backend
            logger.warning(f"No Redis client available, task {task.id} may not be queued properly")
        
        # Persist task state
        task.status = TaskStatus.QUEUED
        await self.persistence.save_task(task)
        
        # Emit task queued event
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_QUEUED,
            data={
                "task_id": task.id,
                "workflow_id": workflow_id,
                "protocol": task.protocol,
                "queue": queue_key,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        logger.info(f"Task {task.id} queued to {queue_key} for protocol {task.protocol}")