"""
Gleitzeit Cluster - Professional Distributed Workflow Orchestration

A modern distributed workflow orchestration system with:
- Secure function execution with curated function library
- Real-time enterprise monitoring with professional GUI
- Multi-node cluster management with Socket.IO communication  
- Intelligent scheduling with multiple policies
- CLI-first design with streamlined commands
- Authentication and role-based access control

Quick Start:
    >>> import asyncio
    >>> from gleitzeit_cluster import GleitzeitCluster
    >>> 
    >>> # Start cluster
    >>> cluster = GleitzeitCluster()
    >>> await cluster.start()
    >>> 
    >>> # Or use CLI
    >>> # gleitzeit dev  # Start full development environment
    >>> # gleitzeit pro  # Launch professional monitoring

Core Components:
    - GleitzeitCluster: Main cluster orchestrator
    - Task: Individual work units with parameters
    - Workflow: Collections of dependent tasks
    - TaskExecutor: Secure task execution engine
    - GleitzeitScheduler: Intelligent task scheduling
    - Professional monitoring dashboard with real-time metrics
"""

__version__ = "0.0.1"
__author__ = "Leif Markthaler"
__license__ = "MIT"

# Core exports
from .core.cluster import GleitzeitCluster
from .core.task import Task, TaskType, TaskParameters, TaskStatus
from .core.workflow import Workflow, WorkflowStatus
from .execution.task_executor import TaskExecutor
from .scheduler.scheduler_node import GleitzeitScheduler
from .functions.registry import get_function_registry

# CLI entry point (for programmatic use)
from .cli import main as cli_main

__all__ = [
    # Version info
    "__version__",
    "__author__", 
    "__license__",
    
    # Core classes
    "GleitzeitCluster",
    "Task",
    "TaskType", 
    "TaskParameters",
    "TaskStatus",
    "Workflow",
    "WorkflowStatus",
    "TaskExecutor",
    "GleitzeitScheduler",
    
    # Functions
    "get_function_registry",
    
    # CLI
    "cli_main",
]