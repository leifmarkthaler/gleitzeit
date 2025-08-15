"""Gleitzeit - Protocol-based workflow orchestration system for LLM and task automation"""

__version__ = "0.0.4"

from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.client import GleitzeitClient

__all__ = [
    "Task",
    "Workflow", 
    "TaskResult",
    "WorkflowExecution",
    "ExecutionEngine",
    "GleitzeitClient",
]