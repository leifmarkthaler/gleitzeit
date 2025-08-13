"""
Core Models for Gleitzeit V3

Event-driven data models with built-in event emission for state changes.
All state modifications automatically generate appropriate events.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Set
from pydantic import BaseModel, Field

from ..events.schemas import EventType, create_event, EventSeverity


class WorkflowStatus(str, Enum):
    SUBMITTED = "submitted"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    CREATED = "created"
    BLOCKED = "blocked"
    READY = "ready"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"




class ProviderStatus(str, Enum):
    REGISTERING = "registering"
    AVAILABLE = "available"
    BUSY = "busy"
    OVERLOADED = "overloaded"
    UNHEALTHY = "unhealthy"
    DISCONNECTED = "disconnected"


class TaskParameters(BaseModel):
    """Task execution parameters"""
    data: Dict[str, Any] = Field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return self.data
    
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)
    
    def set(self, key: str, value: Any):
        self.data[key] = value


class EventEmittingModel(BaseModel):
    """Base model that emits events on state changes"""
    
    def __init__(self, **data):
        super().__init__(**data)
        self._event_bus = None
        self._component_id = None
    
    def set_event_bus(self, event_bus, component_id: str):
        """Set the event bus for automatic event emission"""
        self._event_bus = event_bus
        self._component_id = component_id
    
    async def _emit_event(self, event_type: EventType, payload: Dict[str, Any], **kwargs):
        """Emit an event if event bus is configured"""
        if self._event_bus and self._component_id:
            event = create_event(
                event_type=event_type,
                source_component=self._component_id,
                payload=payload,
                **kwargs
            )
            await self._event_bus.publish(event)


class Task(EventEmittingModel):
    """Event-driven task model"""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    parameters: TaskParameters = Field(default_factory=TaskParameters)
    dependencies: List[str] = Field(default_factory=list)
    priority: str = "normal"
    workflow_id: Optional[str] = None
    
    # Provider routing (optional - if not specified, system will find suitable provider)
    target_provider_id: Optional[str] = None
    
    # Status and timing
    status: TaskStatus = TaskStatus.CREATED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Execution details
    provider_id: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    timeout: int = 300  # seconds
    
    # Metadata
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    async def set_status(self, new_status: TaskStatus, reason: Optional[str] = None, **kwargs):
        """Set task status and emit event"""
        old_status = self.status
        self.status = new_status
        
        # Update timestamps
        if new_status == TaskStatus.RUNNING and not self.started_at:
            self.started_at = datetime.utcnow()
        elif new_status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            if not self.completed_at:
                self.completed_at = datetime.utcnow()
        
        # Emit state change event
        await self._emit_event(
            event_type=EventType.TASK_STATE_CHANGED,
            payload={
                "task_id": self.id,
                "old_status": old_status.value,
                "new_status": new_status.value,
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat()
            },
            task_id=self.id,
            workflow_id=self.workflow_id,
            **kwargs
        )
        
        # Emit specific status events
        if new_status == TaskStatus.READY:
            await self._emit_task_ready_event()
        elif new_status == TaskStatus.COMPLETED:
            await self._emit_task_completed_event()
        elif new_status == TaskStatus.FAILED:
            await self._emit_task_failed_event()
    
    async def _emit_task_ready_event(self):
        """Emit task ready event"""
        await self._emit_event(
            event_type=EventType.TASK_READY,
            payload={
                "task_id": self.id,
                "function": self.parameters.get('function', 'unknown'),
                "provider_requirements": {
                    "function": self.parameters.get('function'),
                    "priority": self.priority
                },
                "priority": self.priority
            },
            task_id=self.id,
            workflow_id=self.workflow_id
        )
    
    async def _emit_task_completed_event(self):
        """Emit task completed event"""
        duration = 0.0
        if self.started_at and self.completed_at:
            duration = (self.completed_at - self.started_at).total_seconds()
        
        await self._emit_event(
            event_type=EventType.TASK_COMPLETED,
            payload={
                "task_id": self.id,
                "provider_id": self.provider_id,
                "duration_seconds": duration,
                "result": self.result,
                "execution_metadata": self.metadata
            },
            task_id=self.id,
            workflow_id=self.workflow_id,
            provider_id=self.provider_id
        )
    
    async def _emit_task_failed_event(self):
        """Emit task failed event"""
        await self._emit_event(
            event_type=EventType.TASK_FAILED,
            payload={
                "task_id": self.id,
                "provider_id": self.provider_id,
                "error_code": "EXECUTION_ERROR",
                "error_message": self.error or "Unknown error",
                "retry_count": self.retry_count,
                "is_recoverable": self.retry_count < self.max_retries
            },
            task_id=self.id,
            workflow_id=self.workflow_id,
            provider_id=self.provider_id,
            severity=EventSeverity.ERROR
        )
    
    async def assign_to_provider(self, provider_id: str):
        """Assign task to a provider"""
        self.provider_id = provider_id
        await self.set_status(TaskStatus.ASSIGNED)
        
        # Emit assignment event
        await self._emit_event(
            event_type=EventType.TASK_ASSIGNED,
            payload={
                "task_id": self.id,
                "provider_id": provider_id,
                "assignment_timestamp": datetime.utcnow().isoformat()
            },
            task_id=self.id,
            workflow_id=self.workflow_id,
            provider_id=provider_id
        )
    
    async def complete_with_result(self, result: Any, execution_metadata: Optional[Dict[str, Any]] = None):
        """Mark task as completed with result"""
        self.result = result
        if execution_metadata:
            self.metadata.update(execution_metadata)
        await self.set_status(TaskStatus.COMPLETED)
    
    async def fail_with_error(self, error: str, is_retryable: bool = True):
        """Mark task as failed"""
        self.error = error
        if is_retryable and self.retry_count < self.max_retries:
            self.retry_count += 1
            await self.set_status(TaskStatus.READY, reason="retry_after_failure")
        else:
            await self.set_status(TaskStatus.FAILED)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "id": self.id,
            "name": self.name,
            "function": self.parameters.get('function', 'unknown'),
            "parameters": self.parameters.to_dict(),
            "dependencies": self.dependencies,
            "priority": self.priority,
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "provider_id": self.provider_id,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "tags": self.tags,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """Create from dictionary"""
        # Parse timestamps
        for field in ['created_at', 'started_at', 'completed_at']:
            if data.get(field):
                data[field] = datetime.fromisoformat(data[field])
        
        # Parse enums
        if 'status' in data:
            data['status'] = TaskStatus(data['status'])
        
        # Create TaskParameters
        if 'parameters' in data:
            if isinstance(data['parameters'], dict):
                data['parameters'] = TaskParameters(data=data['parameters'])
        
        return cls(**data)


class Workflow(EventEmittingModel):
    """Event-driven workflow model"""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    tasks: List[Task] = Field(default_factory=list)
    
    # Status and timing
    status: WorkflowStatus = WorkflowStatus.SUBMITTED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Execution tracking
    completed_tasks: List[str] = Field(default_factory=list)
    failed_tasks: List[str] = Field(default_factory=list)
    task_results: Dict[str, Any] = Field(default_factory=dict)
    
    # Configuration
    error_strategy: str = "stop"  # stop, continue
    max_parallel: int = 10
    priority: str = "normal"
    
    # Metadata
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    def add_task(self, task: Task):
        """Add a task to the workflow"""
        task.workflow_id = self.id
        self.tasks.append(task)
    
    async def set_status(self, new_status: WorkflowStatus, reason: Optional[str] = None):
        """Set workflow status and emit event"""
        old_status = self.status
        self.status = new_status
        
        # Update timestamps
        if new_status == WorkflowStatus.RUNNING and not self.started_at:
            self.started_at = datetime.utcnow()
        elif new_status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]:
            if not self.completed_at:
                self.completed_at = datetime.utcnow()
        
        # Emit state change event
        await self._emit_event(
            event_type=EventType.WORKFLOW_STATE_CHANGED,
            payload={
                "workflow_id": self.id,
                "old_state": old_status.value,
                "new_state": new_status.value,
                "reason": reason
            },
            workflow_id=self.id
        )
        
        # Emit specific status events
        if new_status == WorkflowStatus.COMPLETED:
            await self._emit_workflow_completed_event()
        elif new_status == WorkflowStatus.FAILED:
            await self._emit_workflow_failed_event()
    
    async def _emit_workflow_completed_event(self):
        """Emit workflow completed event"""
        duration = 0.0
        if self.started_at and self.completed_at:
            duration = (self.completed_at - self.started_at).total_seconds()
        
        await self._emit_event(
            event_type=EventType.WORKFLOW_COMPLETED,
            payload={
                "workflow_id": self.id,
                "duration_seconds": duration,
                "completed_tasks": len(self.completed_tasks),
                "failed_tasks": len(self.failed_tasks),
                "results": self.task_results
            },
            workflow_id=self.id
        )
    
    async def _emit_workflow_failed_event(self):
        """Emit workflow failed event"""
        await self._emit_event(
            event_type=EventType.WORKFLOW_FAILED,
            payload={
                "workflow_id": self.id,
                "failed_tasks": self.failed_tasks,
                "error_strategy": self.error_strategy
            },
            workflow_id=self.id,
            severity=EventSeverity.ERROR
        )
    
    def get_ready_tasks(self) -> List[Task]:
        """Get tasks that are ready to execute (dependencies satisfied)"""
        ready_tasks = []
        
        for task in self.tasks:
            if task.status == TaskStatus.CREATED:
                # Check if all dependencies are satisfied
                if self._are_dependencies_satisfied(task):
                    ready_tasks.append(task)
        
        return ready_tasks
    
    def _are_dependencies_satisfied(self, task: Task) -> bool:
        """Check if all task dependencies are satisfied"""
        if not task.dependencies:
            return True
        
        for dep_id in task.dependencies:
            if dep_id not in self.completed_tasks:
                return False
        
        return True
    
    def is_complete(self) -> bool:
        """Check if workflow is complete"""
        total_tasks = len(self.tasks)
        finished_tasks = len(self.completed_tasks) + len(self.failed_tasks)
        
        if self.error_strategy == "stop" and self.failed_tasks:
            return True  # Failed, so considered complete
        
        return finished_tasks >= total_tasks
    
    def get_progress(self) -> Dict[str, Any]:
        """Get workflow progress information"""
        total_tasks = len(self.tasks)
        completed_tasks = len(self.completed_tasks)
        failed_tasks = len(self.failed_tasks)
        running_tasks = len([t for t in self.tasks if t.status == TaskStatus.RUNNING])
        
        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "running_tasks": running_tasks,
            "percentage": (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
            "status": self.status.value
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tasks": [task.to_dict() for task in self.tasks],
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "task_results": self.task_results,
            "error_strategy": self.error_strategy,
            "max_parallel": self.max_parallel,
            "priority": self.priority,
            "tags": self.tags,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Workflow':
        """Create from dictionary with proper task handling"""
        # Extract tasks data
        tasks_data = data.pop('tasks', [])
        
        # Parse timestamps
        for field in ['created_at', 'started_at', 'completed_at']:
            if data.get(field):
                data[field] = datetime.fromisoformat(data[field])
        
        # Parse status
        if 'status' in data:
            data['status'] = WorkflowStatus(data['status'])
        
        # Create workflow without tasks first
        workflow = cls(**data)
        
        # Add tasks using add_task to ensure workflow_id is set
        for task_data in tasks_data:
            task = Task.from_dict(task_data)
            workflow.add_task(task)
        
        return workflow


class Provider(EventEmittingModel):
    """Event-driven provider model"""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    provider_type: str
    supported_functions: Set[str] = Field(default_factory=set)  # Functions this provider can handle
    
    # Connection details
    socket_id: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    
    # Status and health
    status: ProviderStatus = ProviderStatus.REGISTERING
    health_score: float = 1.0  # 0.0 to 1.0
    last_heartbeat: datetime = Field(default_factory=datetime.utcnow)
    
    # Capacity and load
    max_concurrent_tasks: int = 5
    current_tasks: int = 0
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    
    # Performance metrics
    average_task_duration: float = 0.0
    success_rate: float = 1.0
    
    # Metadata
    version: str = "1.0.0"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    async def set_status(self, new_status: ProviderStatus, reason: Optional[str] = None):
        """Set provider status and emit event"""
        old_status = self.status
        self.status = new_status
        
        # Emit appropriate events
        if new_status == ProviderStatus.AVAILABLE:
            await self._emit_provider_available_event()
        elif new_status == ProviderStatus.BUSY:
            await self._emit_provider_busy_event()
        elif new_status == ProviderStatus.OVERLOADED:
            await self._emit_provider_overloaded_event()
        elif new_status == ProviderStatus.DISCONNECTED:
            await self._emit_provider_disconnected_event()
    
    async def _emit_provider_available_event(self):
        """Emit provider available event"""
        await self._emit_event(
            event_type=EventType.PROVIDER_AVAILABLE,
            payload={
                "provider_id": self.id,
                "available_capacity": self.max_concurrent_tasks - self.current_tasks,
                "supported_functions": list(self.supported_functions),
                "current_load": self.get_load_percentage()
            },
            provider_id=self.id
        )
    
    async def _emit_provider_busy_event(self):
        """Emit provider busy event"""
        await self._emit_event(
            event_type=EventType.PROVIDER_BUSY,
            payload={
                "provider_id": self.id,
                "current_tasks": self.current_tasks,
                "max_capacity": self.max_concurrent_tasks
            },
            provider_id=self.id
        )
    
    async def _emit_provider_overloaded_event(self):
        """Emit provider overloaded event"""
        await self._emit_event(
            event_type=EventType.PROVIDER_OVERLOADED,
            payload={
                "provider_id": self.id,
                "current_tasks": self.current_tasks,
                "max_capacity": self.max_concurrent_tasks,
                "load_percentage": self.get_load_percentage()
            },
            provider_id=self.id,
            severity=EventSeverity.WARNING
        )
    
    async def _emit_provider_disconnected_event(self):
        """Emit provider disconnected event"""
        await self._emit_event(
            event_type=EventType.PROVIDER_DISCONNECTED,
            payload={
                "provider_id": self.id,
                "reason": "connection_lost",
                "active_tasks": self.current_tasks
            },
            provider_id=self.id,
            severity=EventSeverity.WARNING
        )
    
    async def emit_heartbeat(self):
        """Emit heartbeat event"""
        self.last_heartbeat = datetime.utcnow()
        
        await self._emit_event(
            event_type=EventType.PROVIDER_HEARTBEAT,
            payload={
                "provider_id": self.id,
                "health_status": self.get_health_status(),
                "current_tasks": self.current_tasks,
                "capacity_utilization": self.get_load_percentage(),
                "performance_metrics": {
                    "success_rate": self.success_rate,
                    "average_duration": self.average_task_duration,
                    "total_completed": self.total_tasks_completed,
                    "total_failed": self.total_tasks_failed
                }
            },
            provider_id=self.id
        )
    
    def get_load_percentage(self) -> float:
        """Get current load as percentage"""
        if self.max_concurrent_tasks == 0:
            return 0.0
        return (self.current_tasks / self.max_concurrent_tasks) * 100
    
    def get_health_status(self) -> str:
        """Get health status string"""
        if self.health_score >= 0.8:
            return "healthy"
        elif self.health_score >= 0.5:
            return "degraded"
        else:
            return "unhealthy"
    
    def can_handle_task(self, task: 'Task') -> bool:
        """Check if provider can handle a task"""
        if (self.status != ProviderStatus.AVAILABLE or
            self.current_tasks >= self.max_concurrent_tasks or
            self.health_score <= 0.3):
            return False
        
        # If task specifies a target provider, only that provider can handle it
        if task.target_provider_id:
            return task.target_provider_id == self.id
        
        # Check if provider supports the function being requested
        function_name = task.parameters.get('function')
        if function_name and self.supported_functions:
            return function_name in self.supported_functions
        
        # If no specific function requirements, any healthy provider can try
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "name": self.name,
            "provider_type": self.provider_type,
            "supported_functions": list(self.supported_functions),
            "socket_id": self.socket_id,
            "host": self.host,
            "port": self.port,
            "status": self.status.value,
            "health_score": self.health_score,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "current_tasks": self.current_tasks,
            "total_tasks_completed": self.total_tasks_completed,
            "total_tasks_failed": self.total_tasks_failed,
            "average_task_duration": self.average_task_duration,
            "success_rate": self.success_rate,
            "version": self.version,
            "metadata": self.metadata
        }