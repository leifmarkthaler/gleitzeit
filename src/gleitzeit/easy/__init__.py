"""
Gleitzeit Easy Syntax - Fluent Interface for Workflow Definition

This module provides a simplified, chainable interface for defining Gleitzeit workflows
with significantly less boilerplate code while maintaining full power and replayability.

Example:
    from gleitzeit.easy import t, w
    
    workflow = w(
        t("get_customer", "api/v1:fetch")
            .with_(customer_id="${input.customer_id}")
            .needs("validate_input")
            .retry(3)
            .timeout(10),
            
        t("process_payment", "payment/v1:charge")
            .needs("get_customer")
            .with_(amount="${input.amount}")
            .on_success()
                .run("send_receipt", "email/v1:send")
            .on_error("DECLINED")
                .run("notify_customer", "email/v1:send")
    )
"""

from .task_builder import TaskBuilder
from .workflow_builder import WorkflowBuilder
from .real_error_handler import add_real_error_methods, RealErrorHandler
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

# Add real error methods to TaskBuilder that use actual implemented errors
add_real_error_methods(TaskBuilder)


def t(task_id: str, protocol_method: str) -> TaskBuilder:
    """
    Create a new task with fluent interface.

    Args:
        task_id: Unique identifier for the task
        protocol_method: Protocol and method in format "protocol/version:method"

    Returns:
        TaskBuilder instance for chaining

    Raises:
        TaskBuilderError: If task_id is invalid
        InvalidProtocolFormatError: If protocol format is invalid

    Example:
        t("fetch_user", "api/v1:get")
            .with_(user_id="${input.id}")
            .retry(3)
            .timeout(30)

    Real error handling example (using actual implemented features):
        t("risky_api_call", "api/v1:fetch")
            .with_retry(max_attempts=3, delay=2.0)  # Uses actual retry system
            .with_timeout(30)  # Uses actual timeout system
    """
    return TaskBuilder(task_id, protocol_method)


def w(*tasks: TaskBuilder) -> WorkflowBuilder:
    """
    Create a new workflow from task builders.

    Args:
        *tasks: TaskBuilder instances to include in workflow

    Returns:
        WorkflowBuilder instance

    Raises:
        EmptyWorkflowError: If no tasks provided
        DuplicateTaskError: If duplicate task IDs found
        CircularDependencyError: If circular dependencies detected
        InvalidDependencyError: If invalid dependencies found

    Example:
        w(
            t("task1", "protocol/v1:method1"),
            t("task2", "protocol/v1:method2").needs("task1")
        )
    """
    return WorkflowBuilder(*tasks)


__all__ = [
    't', 'w',
    'TaskBuilder', 'WorkflowBuilder',
    'RealErrorHandler',
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