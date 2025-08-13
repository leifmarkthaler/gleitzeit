"""
Distributed components for Gleitzeit

All components are Socket.IO clients that connect to the Central Hub.
Each component implements specific functionality while communicating
purely through events.
"""

from .queue_manager import QueueManagerClient, run_queue_manager
from .dependency_resolver import DependencyResolverClient, run_dependency_resolver
from .execution_engine import ExecutionEngineClient, run_execution_engine
# from .protocol_registry import ProtocolRegistryClient
# from .provider import ProviderClient

__all__ = [
    "QueueManagerClient",
    "run_queue_manager", 
    "DependencyResolverClient",
    "run_dependency_resolver",
    "ExecutionEngineClient", 
    "run_execution_engine"
]