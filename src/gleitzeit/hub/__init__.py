"""
Gleitzeit Resource Hub - Unified resource management for compute instances

The hub architecture handles resource lifecycle management (start/stop, health checks, 
load balancing) while providers handle protocol execution. This separation of concerns
enables better scalability and cleaner architecture.
"""

from .base import ResourceHub, ResourceInstance, ResourceStatus, ResourceMetrics, ResourceType
from .configs import OllamaConfig, DockerConfig
from .ollama_hub import OllamaHub
from .docker_hub import DockerHub
# ResourceManager removed - use stateless resource coordination instead

__all__ = [
    'ResourceHub',
    'ResourceInstance', 
    'ResourceStatus',
    'ResourceType',
    'ResourceMetrics',
    'OllamaConfig',
    'DockerConfig',
    'OllamaHub',
    'DockerHub'
]