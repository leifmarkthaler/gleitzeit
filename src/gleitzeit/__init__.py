"""
Gleitzeit 0.0.7 - Distributed Workflow Orchestration

A worker-based, horizontally scalable workflow orchestration system.
"""

__version__ = "0.0.7"

from .workers.base import BaseWorker, WorkerConfig
from .orchestrator.component_orchestrator import ComponentOrchestrator
from .core.sharding import ShardingStrategy, default_sharding

__all__ = [
    "BaseWorker",
    "WorkerConfig",
    "ComponentOrchestrator",
    "ShardingStrategy",
    "default_sharding",
]