"""
Core task definitions for Gleitzeit Cluster
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field
import uuid


class TaskType(Enum):
    """Task types for unified Socket.IO architecture"""
    # All tasks are now external and route via Socket.IO services
    EXTERNAL_API = "external_api"           # External API calls
    EXTERNAL_ML = "external_ml"             # ML training/inference
    EXTERNAL_DATABASE = "external_database" # Database operations
    EXTERNAL_PROCESSING = "external_processing" # Data processing (Python tasks)
    EXTERNAL_WEBHOOK = "external_webhook"   # Webhook-based tasks
    EXTERNAL_CUSTOM = "external_custom"     # Custom external services (LLM tasks)
    


class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    QUEUED = "queued"
    ASSIGNED = "assigned" 
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Task priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskParameters(BaseModel):
    """Parameters for different task types"""
    
    # Common parameters
    prompt: Optional[str] = None
    model: Optional[str] = "llama3"
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    timeout_seconds: Optional[int] = 300
    
    # Vision task parameters
    image_path: Optional[str] = None
    
    # Python function parameters
    function_name: Optional[str] = None
    module_path: Optional[str] = None
    args: Optional[List[Any]] = Field(default_factory=list)
    kwargs: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    # HTTP request parameters
    url: Optional[str] = None
    method: Optional[str] = "GET"
    headers: Optional[Dict[str, str]] = Field(default_factory=dict)
    data: Optional[Any] = None
    
    # File operation parameters
    operation: Optional[str] = None  # read, write, delete, etc.
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    content: Optional[str] = None
    
    # External task parameters
    service_name: Optional[str] = None          # Target external service name
    service_url: Optional[str] = None           # External service URL (optional)
    external_task_type: Optional[str] = None    # Specific task type for external service
    external_parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)  # Service-specific params
    callback_url: Optional[str] = None          # Callback URL for async completion
    webhook_token: Optional[str] = None         # Authentication token for webhooks
    polling_interval: Optional[int] = 5         # Polling interval in seconds
    external_timeout: Optional[int] = 1800      # Extended timeout for external tasks (30 min default)


class TaskRequirements(BaseModel):
    """Resource requirements for task execution"""
    cpu_cores: Optional[float] = None
    memory_mb: Optional[int] = None
    gpu_memory_mb: Optional[int] = None
    requires_gpu: bool = False
    required_models: List[str] = Field(default_factory=list)
    node_tags: List[str] = Field(default_factory=list)


class TaskResult(BaseModel):
    """Task execution result"""
    task_id: str
    status: TaskStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_seconds: Optional[float] = None
    executor_node_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Task(BaseModel):
    """Core task representation"""
    
    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    workflow_id: Optional[str] = None
    
    # Task definition
    task_type: TaskType
    parameters: TaskParameters = Field(default_factory=TaskParameters)
    requirements: TaskRequirements = Field(default_factory=TaskRequirements)
    
    # Execution control
    priority: TaskPriority = TaskPriority.NORMAL
    max_retries: int = 3
    retry_count: int = 0
    timeout_seconds: int = 300
    
    # Dependencies
    dependencies: List[str] = Field(default_factory=list)
    depends_on_success: bool = True  # If False, runs even if deps failed
    
    # Status and tracking
    status: TaskStatus = TaskStatus.PENDING
    assigned_node_id: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Metadata
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization validation"""
        # Auto-detect requirements based on external task type
        if (self.task_type == TaskType.EXTERNAL_CUSTOM and 
            self.parameters.external_task_type == "vision"):
            self.requirements.requires_gpu = True
            
        if self.parameters.model:
            self.requirements.required_models.append(self.parameters.model)
    
    def update_status(self, status: TaskStatus, error: Optional[str] = None) -> None:
        """Update task status with timestamp"""
        self.status = status
        self.updated_at = datetime.utcnow()
        
        if error:
            self.error = error
            
        if status == TaskStatus.QUEUED:
            self.queued_at = datetime.utcnow()
        elif status == TaskStatus.PROCESSING:
            self.started_at = datetime.utcnow()
        elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            self.completed_at = datetime.utcnow()
    
    def is_ready_to_execute(self, completed_tasks: set[str]) -> bool:
        """Check if all dependencies are satisfied"""
        if not self.dependencies:
            return True
            
        return all(dep_id in completed_tasks for dep_id in self.dependencies)
    
    def can_retry(self) -> bool:
        """Check if task can be retried"""
        return (
            self.status in [TaskStatus.FAILED, TaskStatus.RETRYING] and
            self.retry_count < self.max_retries
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        return self.model_dump(mode="json")
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create task from dictionary"""
        return cls.model_validate(data)
    
    def __str__(self) -> str:
        return f"Task(id={self.id[:8]}, name={self.name}, status={self.status.value})"