"""
Error classes for Gleitzeit Easy Syntax.

Provides specific exceptions for different error cases in the easy client.
"""

from typing import Optional, List, Any, Dict
import re


class EasyClientError(Exception):
    """Base exception for all easy client errors."""

    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.data = data or {}


class TaskBuilderError(EasyClientError):
    """Error in task builder configuration."""
    pass


class WorkflowBuilderError(EasyClientError):
    """Error in workflow builder configuration."""
    pass


class InvalidProtocolFormatError(TaskBuilderError):
    """Invalid protocol format specified."""

    def __init__(self, protocol: str, task_id: str, expected_format: str = "protocol/version:method"):
        super().__init__(
            f"Invalid protocol format '{protocol}' for task '{task_id}'. "
            f"Expected format: {expected_format}",
            {"protocol": protocol, "task_id": task_id, "expected_format": expected_format}
        )


class InvalidDependencyError(WorkflowBuilderError):
    """Invalid dependency specified."""

    def __init__(self, task_id: str, dependency: str, available_tasks: List[str]):
        super().__init__(
            f"Task '{task_id}' depends on '{dependency}' which doesn't exist. "
            f"Available tasks: {', '.join(available_tasks)}",
            {"task_id": task_id, "dependency": dependency, "available_tasks": available_tasks}
        )


class DuplicateTaskError(WorkflowBuilderError):
    """Duplicate task ID in workflow."""

    def __init__(self, task_id: str):
        super().__init__(
            f"Duplicate task ID '{task_id}' in workflow",
            {"task_id": task_id}
        )


class CircularDependencyError(WorkflowBuilderError):
    """Circular dependency detected in workflow."""

    def __init__(self, cycle: List[str]):
        super().__init__(
            f"Circular dependency detected: {' -> '.join(cycle)}",
            {"cycle": cycle}
        )


class EmptyWorkflowError(WorkflowBuilderError):
    """Workflow has no tasks."""

    def __init__(self):
        super().__init__("Workflow must contain at least one task")


class InvalidEventTypeError(TaskBuilderError):
    """Invalid event type specified."""

    def __init__(self, event_type: str, task_id: str, valid_types: List[str]):
        super().__init__(
            f"Invalid event type '{event_type}' for task '{task_id}'. "
            f"Valid types: {', '.join(valid_types)}",
            {"event_type": event_type, "task_id": task_id, "valid_types": valid_types}
        )


class InvalidParameterError(TaskBuilderError):
    """Invalid parameter specified."""

    def __init__(self, param_name: str, param_value: Any, task_id: str, reason: str):
        super().__init__(
            f"Invalid parameter '{param_name}' = {param_value} for task '{task_id}': {reason}",
            {"param_name": param_name, "param_value": param_value, "task_id": task_id, "reason": reason}
        )


class InvalidConfigurationError(TaskBuilderError):
    """Invalid configuration specified."""

    def __init__(self, config_name: str, config_value: Any, task_id: str, reason: str):
        super().__init__(
            f"Invalid configuration '{config_name}' = {config_value} for task '{task_id}': {reason}",
            {"config_name": config_name, "config_value": config_value, "task_id": task_id, "reason": reason}
        )


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

    if not isinstance(task_id, str):
        raise TaskBuilderError(f"Task ID must be a string, got {type(task_id)}")

    # For 0.0.7, task IDs are used as names and can contain most characters
    # Just ensure they're not too long and don't have newlines
    if len(task_id) > 255:
        raise TaskBuilderError(f"Task ID '{task_id}' is too long (max 255 characters)")

    if '\n' in task_id or '\r' in task_id:
        raise TaskBuilderError(f"Task ID '{task_id}' cannot contain newlines")


def validate_protocol_format(protocol_method: str, task_id: str) -> tuple[str, str]:
    """
    Validate and parse protocol format.

    Args:
        protocol_method: Protocol and method string
        task_id: Task ID for error context

    Returns:
        Tuple of (protocol, method)

    Raises:
        InvalidProtocolFormatError: If format is invalid
    """
    # For 0.0.7, we support both old and new formats
    # Old: "protocol/version:method" -> "python/v1:execute"
    # New: "protocol/method" -> "python/execute"
    # Simple: just method -> "execute" (assumes python/v1)

    if not protocol_method:
        # Default to Python execution
        return "python/v1", "execute"

    # Check for new simple format (just method name)
    if '/' not in protocol_method and ':' not in protocol_method:
        # Just a method like "execute"
        return "python/v1", protocol_method

    # Try old format: protocol/version:method
    if ':' in protocol_method:
        parts = protocol_method.split(':')
        if len(parts) != 2:
            raise InvalidProtocolFormatError(protocol_method, task_id)
        protocol_version = parts[0]
        method = parts[1]

        if '/' not in protocol_version:
            # Like "python:execute" -> "python/v1:execute"
            protocol_version = f"{protocol_version}/v1"

        return protocol_version, method

    # Try new format: protocol/method
    if '/' in protocol_method:
        parts = protocol_method.split('/')
        if len(parts) == 2:
            # Assume it's protocol/method, add default version
            return f"{parts[0]}/v1", parts[1]
        elif len(parts) == 3:
            # It's protocol/version/method
            return f"{parts[0]}/{parts[1]}", parts[2]

    raise InvalidProtocolFormatError(protocol_method, task_id)