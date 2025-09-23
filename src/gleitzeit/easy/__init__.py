"""
Gleitzeit Easy Syntax - Fluent Interface for Workflow Definition (0.0.7)

This module provides a simplified, chainable interface for defining Gleitzeit workflows
with significantly less boilerplate code while maintaining full power and replayability.

Ported from 0.0.6 and adapted for the 0.0.7 worker-based architecture.

Example:
    from gleitzeit.easy import t, w

    workflow = w(
        t("get_data", "python/v1:execute")
            .with_(code="result = {'data': 42}")
            .retry(3)
            .timeout(10),

        t("process_data", "python/v1:execute")
            .needs("get_data")
            .with_(code="result = dependencies['get_data']['data'] * 2")
    ).submit()  # Submit directly to the API
"""

from .task_builder import TaskBuilder
from .workflow_builder import WorkflowBuilder
from .errors import (
    EasyClientError,
    TaskBuilderError,
    WorkflowBuilderError,
    InvalidProtocolFormatError,
    InvalidDependencyError,
    DuplicateTaskError,
    CircularDependencyError,
    EmptyWorkflowError,
    InvalidEventTypeError,
    InvalidParameterError,
    InvalidConfigurationError
)


def t(task_id: str, protocol_method: str = "python/v1:execute") -> TaskBuilder:
    """
    Create a new task with fluent interface.

    Args:
        task_id: Unique identifier for the task (will be the task name)
        protocol_method: Protocol and method (defaults to python/v1:execute)

    Returns:
        TaskBuilder instance for chaining

    Example:
        t("fetch_user")
            .with_(code="result = get_user(123)")
            .retry(3)
            .timeout(30)
    """
    return TaskBuilder(task_id, protocol_method)


def w(*tasks: TaskBuilder) -> WorkflowBuilder:
    """
    Create a new workflow from task builders.

    Args:
        *tasks: TaskBuilder instances to include in workflow

    Returns:
        WorkflowBuilder instance

    Example:
        w(
            t("task1").with_(code="result = 1"),
            t("task2").needs("task1").with_(code="result = dependencies['task1'] + 1")
        ).submit()
    """
    return WorkflowBuilder(*tasks)


__all__ = [
    't', 'w',
    'TaskBuilder', 'WorkflowBuilder',
    # Error classes
    'EasyClientError',
    'TaskBuilderError',
    'WorkflowBuilderError',
    'InvalidProtocolFormatError',
    'InvalidDependencyError',
    'DuplicateTaskError',
    'CircularDependencyError',
    'EmptyWorkflowError',
    'InvalidEventTypeError',
    'InvalidParameterError',
    'InvalidConfigurationError'
]