"""
Gleitzeit System Manager - Centralized orchestration and lifecycle management.

The ONLY system manager to use is ModularStreamSystemManager.
It provides:
- Service discovery and registration
- Health monitoring across all components
- Configuration management
- Resource coordination
- Deployment orchestration
- Truly stateless architecture with NO loops
- Single unified StreamlinedEventBus
"""

from .models import (
    ServiceSpec,
    ServiceStatus,
    ComponentHealth,
    SystemConfig,
    DeploymentSpec,
    ServiceType,
    HealthStatus,
    DeploymentMode,
)
from .service_registry import ServiceRegistry
from .health_monitor import HealthMonitor
from .config_manager import ConfigurationManager
from .resource_coordinator import ResourceCoordinator
from .modular_stream_system_manager import ModularStreamSystemManager
from .manager import (
    get_system_manager,
    set_system_manager,
    create_system_manager,
    ensure_system_manager,
)

__all__ = [
    # Models
    "ServiceSpec",
    "ServiceStatus",
    "ComponentHealth",
    "SystemConfig",
    "DeploymentSpec",
    "ServiceType",
    "HealthStatus",
    "DeploymentMode",
    # Components
    "ServiceRegistry",
    "HealthMonitor",
    "ConfigurationManager",
    "ResourceCoordinator",
    "ModularStreamSystemManager",  # The ONLY system manager to use
    # Unified discovery functions
    "get_system_manager",
    "set_system_manager",
    "create_system_manager",
    "ensure_system_manager",
]