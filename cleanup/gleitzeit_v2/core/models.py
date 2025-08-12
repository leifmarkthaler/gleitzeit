"""
Core data models for Gleitzeit V2

Clean, well-defined models for tasks, workflows, and providers.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStatus(Enum):
    """Workflow execution status"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class TaskType(Enum):
    """Task type classifications"""
    # LLM tasks
    LLM_GENERATE = "llm_generate"
    LLM_CHAT = "llm_chat"
    LLM_EMBED = "llm_embed"
    LLM_VISION = "llm_vision"
    
    # Processing tasks
    FUNCTION = "function"
    PYTHON = "python"
    SHELL = "shell"
    
    # Data tasks
    HTTP_REQUEST = "http_request"
    FILE_OPERATION = "file_operation"
    DATABASE = "database"
    
    # External services
    EXTERNAL_API = "external_api"
    WEBHOOK = "webhook"
    
    # MCP tasks
    MCP_FUNCTION = "mcp_function"
    MCP_QUERY = "mcp_query"
    MCP_TOOL = "mcp_tool"


class Priority(Enum):
    """Task priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class TaskParameters:
    """Parameters for task execution"""
    # LLM parameters
    prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    system_prompt: Optional[str] = None
    
    # File parameters
    image_path: Optional[str] = None
    file_path: Optional[str] = None
    
    # Function parameters
    function_name: Optional[str] = None
    args: Optional[List[Any]] = None
    kwargs: Optional[Dict[str, Any]] = None
    
    # HTTP parameters
    url: Optional[str] = None
    method: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    data: Optional[Any] = None
    
    # Provider-specific parameters
    provider: Optional[str] = None
    provider_params: Optional[Dict[str, Any]] = None
    
    # MCP parameters
    server: Optional[str] = None
    function: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    query: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    
    # General parameters
    timeout: Optional[int] = None
    retries: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values"""
        return {k: v for k, v in self.__dict__.items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskParameters':
        """Create from dictionary"""
        return cls(**data)


@dataclass
class Task:
    """Task definition"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    task_type: TaskType = TaskType.FUNCTION
    parameters: TaskParameters = field(default_factory=TaskParameters)
    dependencies: List[str] = field(default_factory=list)
    priority: Priority = Priority.NORMAL
    
    # Execution metadata
    workflow_id: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    assigned_provider: Optional[str] = None
    
    # Results
    result: Optional[Any] = None
    error: Optional[str] = None
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Execution limits
    max_retries: int = 3
    timeout: int = 300  # seconds
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = {
            'id': self.id,
            'name': self.name,
            'task_type': self.task_type.value,
            'parameters': self.parameters.to_dict(),
            'dependencies': self.dependencies,
            'priority': self.priority.value,
            'workflow_id': self.workflow_id,
            'status': self.status.value,
            'assigned_provider': self.assigned_provider,
            'result': self.result,
            'error': self.error,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'max_retries': self.max_retries,
            'timeout': self.timeout
        }
        return {k: v for k, v in data.items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """Create from dictionary"""
        # Parse enums
        data['task_type'] = TaskType(data.get('task_type', 'function'))
        data['priority'] = Priority(data.get('priority', 'normal'))
        data['status'] = TaskStatus(data.get('status', 'pending'))
        
        # Parse parameters
        if 'parameters' in data:
            data['parameters'] = TaskParameters.from_dict(data['parameters'])
        
        # Parse timestamps
        for field_name in ['created_at', 'started_at', 'completed_at']:
            if data.get(field_name):
                data[field_name] = datetime.fromisoformat(data[field_name])
        
        return cls(**data)
    
    def is_ready_to_execute(self, completed_tasks: List[str]) -> bool:
        """Check if task dependencies are satisfied"""
        if not self.dependencies:
            return True
        return all(dep_id in completed_tasks for dep_id in self.dependencies)


@dataclass
class Workflow:
    """Workflow definition"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    tasks: List[Task] = field(default_factory=list)
    
    # Execution control
    status: WorkflowStatus = WorkflowStatus.PENDING
    error_strategy: str = "stop"  # "stop", "continue", "retry"
    max_parallel: int = 10
    
    # Results tracking
    completed_tasks: List[str] = field(default_factory=list)
    failed_tasks: List[str] = field(default_factory=list)
    task_results: Dict[str, Any] = field(default_factory=dict)
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_task(self, task: Task) -> None:
        """Add task to workflow"""
        task.workflow_id = self.id
        self.tasks.append(task)
    
    def get_ready_tasks(self) -> List[Task]:
        """Get tasks that are ready to execute"""
        return [
            task for task in self.tasks
            if task.status == TaskStatus.PENDING and task.is_ready_to_execute(self.completed_tasks)
        ]
    
    def get_total_tasks(self) -> int:
        """Get total number of tasks"""
        return len(self.tasks)
    
    def get_progress(self) -> Dict[str, Any]:
        """Get workflow progress"""
        total = len(self.tasks)
        completed = len(self.completed_tasks)
        failed = len(self.failed_tasks)
        running = len([t for t in self.tasks if t.status == TaskStatus.RUNNING])
        
        return {
            'total': total,
            'completed': completed,
            'failed': failed,
            'running': running,
            'pending': total - completed - failed - running,
            'progress_percent': (completed / total * 100) if total > 0 else 0
        }
    
    def is_complete(self) -> bool:
        """Check if workflow is complete"""
        return len(self.completed_tasks) + len(self.failed_tasks) >= len(self.tasks)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'tasks': [task.to_dict() for task in self.tasks],
            'status': self.status.value,
            'error_strategy': self.error_strategy,
            'max_parallel': self.max_parallel,
            'completed_tasks': self.completed_tasks,
            'failed_tasks': self.failed_tasks,
            'task_results': self.task_results,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'tags': self.tags,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Workflow':
        """Create from dictionary"""
        # Parse status
        data['status'] = WorkflowStatus(data.get('status', 'pending'))
        
        # Extract tasks data separately and remove from data
        tasks_data = data.pop('tasks', [])
        
        # Parse timestamps
        for field_name in ['created_at', 'started_at', 'completed_at']:
            if data.get(field_name):
                data[field_name] = datetime.fromisoformat(data[field_name])
        
        # Create workflow instance without tasks
        workflow = cls(**data)
        
        # Add tasks one by one to ensure workflow_id gets assigned
        for task_data in tasks_data:
            task = Task.from_dict(task_data)
            workflow.add_task(task)
        
        return workflow


@dataclass
class ProviderCapabilities:
    """Provider capability definition"""
    task_types: List[TaskType] = field(default_factory=list)
    models: List[str] = field(default_factory=list)
    max_concurrent: int = 4
    features: List[str] = field(default_factory=list)
    
    def can_handle(self, task: Task) -> bool:
        """Check if provider can handle task"""
        if task.task_type not in self.task_types:
            return False
        
        # Check model compatibility (only for LLM tasks)
        if task.task_type in [TaskType.LLM_GENERATE, TaskType.LLM_CHAT, TaskType.LLM_VISION, TaskType.LLM_EMBED]:
            if task.parameters.model and task.parameters.model not in self.models:
                return False
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'task_types': [t.value for t in self.task_types],
            'models': self.models,
            'max_concurrent': self.max_concurrent,
            'features': self.features
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProviderCapabilities':
        """Create from dictionary"""
        if 'task_types' in data:
            data['task_types'] = [TaskType(t) for t in data['task_types']]
        return cls(**data)


@dataclass
class Provider:
    """Provider definition"""
    id: str
    name: str
    type: str  # "llm", "function", "external"
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    
    # Connection info
    socket_id: Optional[str] = None
    status: str = "inactive"  # "inactive", "active", "busy", "error"
    
    # Resource tracking
    current_tasks: int = 0
    max_concurrent: int = 4
    
    # Health tracking
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    health_status: Dict[str, Any] = field(default_factory=dict)
    
    # Statistics
    tasks_completed: int = 0
    tasks_failed: int = 0
    
    def is_available(self) -> bool:
        """Check if provider is available for new tasks"""
        return (
            self.status == "active" and
            self.current_tasks < self.max_concurrent
        )
    
    def can_handle_task(self, task: Task) -> bool:
        """Check if provider can handle the specific task"""
        return self.is_available() and self.capabilities.can_handle(task)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'capabilities': self.capabilities.to_dict(),
            'socket_id': self.socket_id,
            'status': self.status,
            'current_tasks': self.current_tasks,
            'max_concurrent': self.max_concurrent,
            'last_heartbeat': self.last_heartbeat.isoformat(),
            'health_status': self.health_status,
            'tasks_completed': self.tasks_completed,
            'tasks_failed': self.tasks_failed
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Provider':
        """Create from dictionary"""
        if 'capabilities' in data:
            data['capabilities'] = ProviderCapabilities.from_dict(data['capabilities'])
        
        if 'last_heartbeat' in data:
            data['last_heartbeat'] = datetime.fromisoformat(data['last_heartbeat'])
            
        return cls(**data)