"""
Error handling for Gleitzeit Easy Syntax.

Custom error classes for the easy client that leverage the comprehensive
Gleitzeit error system described in ERROR-SYSTEM-DOCUMENTATION.md.
"""

from typing import Optional, Dict, Any, List
from gleitzeit.core.errors import (
    GleitzeitError,
    WorkflowError,
    TaskError,
    ErrorCode
)


class EasyClientError(GleitzeitError):
    """Base error for all easy client errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        **kwargs
    ):
        super().__init__(message, code, **kwargs)


class TaskBuilderError(TaskError):
    """Error raised when building tasks with the easy syntax."""

    def __init__(
        self,
        message: str,
        task_id: Optional[str] = None,
        code: ErrorCode = ErrorCode.TASK_VALIDATION_FAILED,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if task_id:
            data["task_id"] = task_id
        super().__init__(message, code, data=data, **kwargs)


class WorkflowBuilderError(WorkflowError):
    """Error raised when building workflows with the easy syntax."""

    def __init__(
        self,
        message: str,
        workflow_name: Optional[str] = None,
        code: ErrorCode = ErrorCode.WORKFLOW_VALIDATION_FAILED,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if workflow_name:
            data["workflow_name"] = workflow_name
        super().__init__(message, code, data=data, **kwargs)


class InvalidProtocolFormatError(TaskBuilderError):
    """Error raised when protocol/method format is invalid."""

    def __init__(
        self,
        protocol_method: str,
        task_id: Optional[str] = None,
        **kwargs
    ):
        message = f"Invalid protocol/method format: '{protocol_method}'. Expected format: 'protocol/version:method'"
        data = kwargs.pop("data", {})
        data["protocol_method"] = protocol_method
        data["expected_format"] = "protocol/version:method"
        super().__init__(
            message,
            task_id=task_id,
            code=ErrorCode.TASK_VALIDATION_FAILED,
            data=data,
            **kwargs
        )


class InvalidDependencyError(TaskBuilderError):
    """Error raised when task dependencies are invalid."""

    def __init__(
        self,
        task_id: str,
        dependency: str,
        reason: str,
        **kwargs
    ):
        message = f"Invalid dependency '{dependency}' for task '{task_id}': {reason}"
        data = kwargs.pop("data", {})
        data["dependency"] = dependency
        data["reason"] = reason
        super().__init__(
            message,
            task_id=task_id,
            code=ErrorCode.TASK_DEPENDENCY_FAILED,
            data=data,
            **kwargs
        )


class DuplicateTaskError(WorkflowBuilderError):
    """Error raised when duplicate task IDs are found."""

    def __init__(
        self,
        duplicates: List[str],
        workflow_name: Optional[str] = None,
        **kwargs
    ):
        message = f"Duplicate task IDs found: {duplicates}"
        data = kwargs.pop("data", {})
        data["duplicate_task_ids"] = duplicates
        super().__init__(
            message,
            workflow_name=workflow_name,
            code=ErrorCode.WORKFLOW_VALIDATION_FAILED,
            data=data,
            **kwargs
        )


class CircularDependencyError(WorkflowBuilderError):
    """Error raised when circular dependencies are detected."""

    def __init__(
        self,
        cycle: List[str],
        workflow_name: Optional[str] = None,
        **kwargs
    ):
        message = f"Circular dependency detected: {' -> '.join(cycle)}"
        data = kwargs.pop("data", {})
        data["dependency_cycle"] = cycle
        super().__init__(
            message,
            workflow_name=workflow_name,
            code=ErrorCode.WORKFLOW_CIRCULAR_DEPENDENCY,
            data=data,
            **kwargs
        )


class EmptyWorkflowError(WorkflowBuilderError):
    """Error raised when workflow has no tasks."""

    def __init__(
        self,
        workflow_name: Optional[str] = None,
        **kwargs
    ):
        message = "Workflow must contain at least one task"
        super().__init__(
            message,
            workflow_name=workflow_name,
            code=ErrorCode.WORKFLOW_VALIDATION_FAILED,
            **kwargs
        )


class InvalidEventTypeError(TaskBuilderError):
    """Error raised when event type is invalid."""

    def __init__(
        self,
        event_type: str,
        task_id: Optional[str] = None,
        valid_types: Optional[List[str]] = None,
        **kwargs
    ):
        valid_types = valid_types or ["success", "failure", "error", "timeout", "finally"]
        message = f"Invalid event type: '{event_type}'. Valid types: {valid_types}"
        data = kwargs.pop("data", {})
        data["event_type"] = event_type
        data["valid_types"] = valid_types
        super().__init__(
            message,
            task_id=task_id,
            code=ErrorCode.TASK_VALIDATION_FAILED,
            data=data,
            **kwargs
        )


class InvalidParameterError(TaskBuilderError):
    """Error raised when task parameters are invalid."""

    def __init__(
        self,
        task_id: str,
        param_name: str,
        reason: str,
        **kwargs
    ):
        message = f"Invalid parameter '{param_name}' for task '{task_id}': {reason}"
        data = kwargs.pop("data", {})
        data["parameter_name"] = param_name
        data["reason"] = reason
        super().__init__(
            message,
            task_id=task_id,
            code=ErrorCode.TASK_VALIDATION_FAILED,
            data=data,
            **kwargs
        )


class InvalidConfigurationError(TaskBuilderError):
    """Error raised when task configuration is invalid."""

    def __init__(
        self,
        task_id: str,
        config_name: str,
        value: Any,
        reason: str,
        **kwargs
    ):
        message = f"Invalid configuration '{config_name}' for task '{task_id}': {reason}"
        data = kwargs.pop("data", {})
        data["config_name"] = config_name
        data["config_value"] = value
        data["reason"] = reason
        super().__init__(
            message,
            task_id=task_id,
            code=ErrorCode.TASK_VALIDATION_FAILED,
            data=data,
            **kwargs
        )


def validate_protocol_format(protocol_method: str, task_id: Optional[str] = None) -> tuple[Optional[str], str]:
    """
    Validate and parse protocol/method format.

    Supports three formats:
    1. "protocol/v1:method" - explicit protocol and method
    2. "namespace/action" - method only, protocol will be inferred as namespace/v1
    3. "protocol/v1" - protocol only, method defaults to "execute"

    Args:
        protocol_method: Protocol and/or method string
        task_id: Optional task ID for error context

    Returns:
        Tuple of (protocol_version, method)
        Protocol can be None if only method is provided

    Raises:
        InvalidProtocolFormatError: If format is invalid
    """
    if not protocol_method:
        raise InvalidProtocolFormatError("", task_id)

    # Check for completely invalid formats
    if protocol_method.count(':') > 1:
        raise InvalidProtocolFormatError(protocol_method, task_id)

    if ':' in protocol_method:
        # Format: "protocol/v1:method"
        parts = protocol_method.split(':', 1)
        protocol_version = parts[0]
        method = parts[1]

        if not protocol_version or not method:
            raise InvalidProtocolFormatError(protocol_method, task_id)

        # Validate protocol version format
        if '/' not in protocol_version:
            raise InvalidProtocolFormatError(
                protocol_method,
                task_id,
                data={"reason": "Protocol must include version (e.g., 'python/v1')"}
            )

        return protocol_version, method
    else:
        # No colon - could be just method or just protocol
        if '/' in protocol_method:
            # Check if it looks like a versioned protocol (ends with /v<number>)
            parts = protocol_method.split('/')
            if len(parts) == 2 and parts[1].startswith('v') and parts[1][1:].isdigit():
                # Format: "protocol/v1" - protocol only, default to execute method
                return protocol_method, "execute"
            else:
                # Format: "namespace/action" - method only, protocol will be inferred
                # Return None for protocol to indicate it should be extracted from method
                return None, protocol_method
        else:
            # Single word without slash - treat as simple method
            # Protocol will be inferred from context
            return None, protocol_method


def validate_task_id(task_id: str) -> None:
    """
    Validate task ID format.

    Args:
        task_id: Task ID to validate

    Raises:
        TaskBuilderError: If task ID is invalid
    """
    if not task_id:
        raise TaskBuilderError("Task ID cannot be empty")

    if not task_id.replace('_', '').replace('-', '').replace('.', '').isalnum():
        raise TaskBuilderError(
            f"Task ID '{task_id}' contains invalid characters. Use only alphanumeric, underscore, hyphen, and dot."
        )

    if len(task_id) > 255:
        raise TaskBuilderError(
            f"Task ID '{task_id}' is too long. Maximum length is 255 characters."
        )