"""
Resource management data models
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, Set, List
import uuid


class ResourceType(str, Enum):
    """Types of managed resources"""
    OLLAMA = "ollama"
    DOCKER = "docker"
    PYTHON = "python"
    GPU = "gpu"
    CUSTOM = "custom"


class ResourceStatus(str, Enum):
    """Resource instance status"""
    AVAILABLE = "available"
    BUSY = "busy"
    STARTING = "starting"
    STOPPING = "stopping"
    FAILED = "failed"
    MAINTENANCE = "maintenance"


@dataclass
class ResourceRequirements:
    """Requirements for task execution"""
    resource_type: ResourceType
    capabilities: Set[str] = field(default_factory=set)  # e.g., {"llama3.2", "gpu"}
    min_memory_mb: Optional[int] = None
    min_cpu_cores: Optional[int] = None
    preferred_instance: Optional[str] = None  # Specific instance ID
    exclusive: bool = False  # Require exclusive access
    timeout_seconds: int = 300  # Max time to wait for allocation
    
    def matches(self, instance: 'ResourceInstance') -> bool:
        """Check if instance satisfies requirements"""
        if instance.resource_type != self.resource_type:
            return False
        
        if self.capabilities and not self.capabilities.issubset(instance.capabilities):
            return False
            
        if self.min_memory_mb and instance.available_memory_mb < self.min_memory_mb:
            return False
            
        if self.min_cpu_cores and instance.available_cpu_cores < self.min_cpu_cores:
            return False
            
        if self.exclusive and instance.status != ResourceStatus.AVAILABLE:
            return False
            
        return True


@dataclass
class ResourceMetrics:
    """Metrics for a resource instance"""
    total_requests: int = 0
    active_requests: int = 0
    failed_requests: int = 0
    avg_response_time_ms: float = 0.0
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    last_used: Optional[datetime] = None
    uptime_seconds: float = 0.0
    
    def error_rate(self) -> float:
        """Calculate error rate"""
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests * 100


@dataclass
class ResourceInstance:
    """Represents a managed resource instance"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    resource_type: ResourceType = ResourceType.CUSTOM
    endpoint: str = ""  # Connection URL
    status: ResourceStatus = ResourceStatus.AVAILABLE
    capabilities: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Resource limits
    max_concurrent_tasks: int = 1
    available_memory_mb: float = 0
    available_cpu_cores: int = 1
    
    # Tracking
    current_tasks: Set[str] = field(default_factory=set)  # Task IDs using this resource
    metrics: ResourceMetrics = field(default_factory=ResourceMetrics)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_health_check: Optional[datetime] = None
    health_check_failures: int = 0
    
    def is_available(self) -> bool:
        """Check if resource can accept new tasks"""
        return (
            self.status == ResourceStatus.AVAILABLE and
            len(self.current_tasks) < self.max_concurrent_tasks
        )
    
    def allocate(self, task_id: str) -> bool:
        """Allocate resource to a task"""
        if not self.is_available():
            return False
        
        self.current_tasks.add(task_id)
        if len(self.current_tasks) >= self.max_concurrent_tasks:
            self.status = ResourceStatus.BUSY
        
        self.metrics.active_requests += 1
        self.metrics.total_requests += 1
        self.metrics.last_used = datetime.utcnow()
        return True
    
    def release(self, task_id: str) -> None:
        """Release resource from a task"""
        self.current_tasks.discard(task_id)
        if len(self.current_tasks) < self.max_concurrent_tasks:
            self.status = ResourceStatus.AVAILABLE
        self.metrics.active_requests = max(0, self.metrics.active_requests - 1)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'type': self.resource_type.value,
            'endpoint': self.endpoint,
            'status': self.status.value,
            'capabilities': list(self.capabilities),
            'current_tasks': list(self.current_tasks),
            'metrics': {
                'total_requests': self.metrics.total_requests,
                'active_requests': self.metrics.active_requests,
                'error_rate': self.metrics.error_rate(),
                'cpu_usage': self.metrics.cpu_usage_percent,
                'memory_usage_mb': self.metrics.memory_usage_mb
            }
        }