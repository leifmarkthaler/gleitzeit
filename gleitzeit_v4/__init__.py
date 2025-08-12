"""
Gleitzeit V4 - Protocol-Based Task Execution System

A distributed task execution system built on JSON-RPC 2.0 protocols
that enables universal integration with external services.

Key Features:
- Protocol-centric architecture with JSON-RPC 2.0 compliance
- Universal service integration (any JSON-RPC 2.0 service)
- MCP (Model Context Protocol) native support
- Priority-based task queuing with dependency management
- Advanced workflow orchestration and templates
- Health monitoring and load balancing
- Comprehensive CLI interface

Quick Start:
    from gleitzeit_v4 import Task, ExecutionEngine, ProtocolProviderRegistry
    
    # Create task
    task = Task(
        protocol="web-search/v1",
        method="search", 
        params={"query": "python async"}
    )
    
    # Setup system
    registry = ProtocolProviderRegistry()
    engine = ExecutionEngine(registry=registry, ...)
    
    # Execute
    await engine.submit_task(task)
    await engine.start()
"""

from .core import (
    Task, Workflow, TaskStatus, WorkflowStatus,
    ExecutionEngine, ExecutionMode,
    WorkflowManager, WorkflowTemplate, WorkflowExecutionPolicy,
    ProtocolSpec, MethodSpec,
    JSONRPCRequest, JSONRPCResponse, JSONRPCError
)

from .registry import ProtocolProviderRegistry
from .queue import TaskQueue, QueueManager, DependencyResolver
from .providers import ProtocolProvider, HTTPServiceProvider, WebSocketProvider

__version__ = "4.0.0"
__author__ = "Gleitzeit Development Team"

__all__ = [
    # Core Models
    "Task",
    "Workflow", 
    "TaskStatus",
    "WorkflowStatus",
    
    # Execution Components
    "ExecutionEngine",
    "ExecutionMode",
    "WorkflowManager",
    "WorkflowTemplate",
    "WorkflowExecutionPolicy",
    
    # Protocol System
    "ProtocolSpec",
    "MethodSpec",
    "JSONRPCRequest", 
    "JSONRPCResponse",
    "JSONRPCError",
    
    # Registry and Queue
    "ProtocolProviderRegistry",
    "TaskQueue",
    "QueueManager", 
    "DependencyResolver",
    
    # Provider Base Classes
    "ProtocolProvider",
    "HTTPServiceProvider",
    "WebSocketProvider"
]