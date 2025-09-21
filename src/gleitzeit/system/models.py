"""
Data models for the System Manager.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Set
from pydantic import BaseModel, Field


class ServiceType(str, Enum):
    """Types of services in the system."""
    PROVIDER = "provider"
    HUB = "hub"
    WORKER = "worker"
    API = "api"
    PERSISTENCE = "persistence"
    EVENT_BUS = "event_bus"
    RESOURCE_SERVICE = "resource_service"


class HealthStatus(str, Enum):
    """Health status of a component."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class DeploymentMode(str, Enum):
    """Deployment modes for the system."""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    KUBERNETES = "kubernetes"


@dataclass
class ServiceSpec:
    """Specification for a service in the system."""
    service_id: str
    service_type: ServiceType
    name: str
    version: str
    endpoint: Optional[str] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    health_check_endpoint: Optional[str] = None
    registered_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: Optional[datetime] = None
    

@dataclass
class ServiceStatus:
    """Current status of a service."""
    service_id: str
    health_status: HealthStatus
    is_active: bool
    last_check: datetime
    uptime_seconds: float
    error_count: int = 0
    success_count: int = 0
    average_response_time: float = 0.0
    current_load: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComponentHealth:
    """Health information for a component."""
    component_id: str
    component_type: ServiceType
    status: HealthStatus
    checks: Dict[str, bool] = field(default_factory=dict)
    dependencies_health: Dict[str, HealthStatus] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    last_check: datetime = field(default_factory=datetime.utcnow)
    error_message: Optional[str] = None
    recovery_attempts: int = 0
    

class SystemConfig(BaseModel):
    """Configuration for the System Manager."""
    # Deployment configuration
    deployment_mode: DeploymentMode = DeploymentMode.DEVELOPMENT
    environment: str = "dev"
    
    # Service discovery
    service_registry_backend: str = "memory"  # memory, redis, etcd
    service_registry_url: Optional[str] = None
    service_heartbeat_interval: int = 30  # seconds
    service_timeout: int = 60  # seconds before marking service as unhealthy
    
    # Health monitoring
    health_check_interval: int = 10  # seconds
    health_check_timeout: int = 5  # seconds
    max_recovery_attempts: int = 3
    recovery_backoff: float = 2.0  # exponential backoff multiplier
    
    # Resource coordination
    enable_resource_limits: bool = True
    max_workers: int = 10
    max_providers_per_protocol: int = 5
    resource_allocation_strategy: str = "round_robin"  # round_robin, least_loaded, best_fit
    
    # Configuration management
    config_reload_enabled: bool = True
    config_watch_interval: int = 30  # seconds
    config_validation_strict: bool = True
    
    # Deployment orchestration
    enable_rolling_updates: bool = True
    rolling_update_batch_size: int = 1
    deployment_timeout: int = 300  # seconds
    enable_auto_rollback: bool = True
    
    # Monitoring and metrics
    metrics_enabled: bool = True
    metrics_port: int = 9090
    alerting_enabled: bool = False
    alert_webhook_url: Optional[str] = None
    
    # Persistence
    persistence_backend: str = "unified"  # Use existing unified persistence
    
    # Event Transport Configuration - Instance-specific consumer group
    stream_consumer_group: Optional[str] = None  # Will be auto-generated if not provided
    
    # ProviderHub configuration
    provider_hub_port: int = 8090  # Port for ProviderHub HTTP server
    
    # API configuration
    api_client_pool_size: int = 20  # Max clients in SharedClientPool
    
    # Default providers to start
    default_providers: List[str] = Field(default_factory=lambda: ["python"])
    
    class Config:
        use_enum_values = True


@dataclass
class DeploymentSpec:
    """Specification for system deployment."""
    deployment_id: str
    version: str
    components: List[ServiceSpec]
    configuration: Dict[str, Any]
    rollout_strategy: str = "immediate"  # immediate, rolling, blue_green, canary
    health_checks: List[str] = field(default_factory=list)
    rollback_on_failure: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    

@dataclass
class ServiceCriteria:
    """Criteria for service discovery."""
    service_type: Optional[ServiceType] = None
    capabilities: Optional[Dict[str, Any]] = None
    version: Optional[str] = None
    health_status: Optional[HealthStatus] = None
    load_threshold: Optional[float] = None  # Max load percentage
    

@dataclass
class ResourcePolicy:
    """Resource allocation policy."""
    policy_id: str
    resource_type: str  # cpu, memory, connections, etc.
    min_value: float
    max_value: float
    allocation_strategy: str
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemMetrics:
    """System-wide metrics."""
    timestamp: datetime
    total_services: int
    healthy_services: int
    degraded_services: int
    unhealthy_services: int
    total_workflows: int
    active_workflows: int
    completed_workflows: int
    failed_workflows: int
    average_task_latency: float
    resource_utilization: Dict[str, float]
    error_rate: float
    throughput: float  # tasks per second