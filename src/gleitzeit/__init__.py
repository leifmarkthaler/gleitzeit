"""Gleitzeit - Protocol-based workflow orchestration system for LLM and task automation"""

__version__ = "0.0.6"

from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2 as ExecutionEngine
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.client import GleitzeitClient as Client

__all__ = [
    "Client",
    "ClientMode",
    "Task",
    "Workflow", 
    "TaskResult",
    "WorkflowExecution",
    "ExecutionEngine",
    "GleitzeitClient",
]