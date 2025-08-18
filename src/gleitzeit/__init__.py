"""Gleitzeit - Protocol-based workflow orchestration system for LLM and task automation"""

__version__ = "0.0.5"

from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.client import GleitzeitClient, create_client
from gleitzeit.client_v2 import GleitzeitClient as Client

__all__ = [
    "Client",
    "Task",
    "Workflow", 
    "TaskResult",
    "WorkflowExecution",
    "ExecutionEngine",
    "GleitzeitClient",  # Keep old client for backwards compatibility
    "create_client",
]