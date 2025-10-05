"""
Error classes for Gleitzeit Easy Syntax.

Provides specific exceptions for different error cases in the easy client.
All errors inherit from central Gleitzeit error system for consistency.
"""

from typing import Optional, List, Any, Dict
import re
import difflib
from ..core.errors import (
    GleitzeitError,
    ErrorCode,
    TaskError,
    WorkflowError,
    ProtocolError
)


# Easy Client uses central Gleitzeit errors as base
class EasyClientError(GleitzeitError):
    """Base exception for all easy client errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INVALID_REQUEST,
        data: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message, code, data)


class TaskBuilderError(TaskError):
    """Error in task builder configuration."""

    def __init__(self, message: str, task_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            code=ErrorCode.TASK_VALIDATION_FAILED,
            task_id=task_id,
            data=data
        )


class WorkflowBuilderError(WorkflowError):
    """Error in workflow builder configuration."""

    def __init__(self, message: str, workflow_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            code=ErrorCode.WORKFLOW_VALIDATION_FAILED,
            workflow_id=workflow_id,
            data=data
        )


class InvalidProtocolFormatError(TaskBuilderError):
    """Invalid protocol format specified."""

    def __init__(self, protocol: str, task_id: str, expected_format: str = "protocol/version:method"):
        super().__init__(
            f"Invalid protocol format '{protocol}' for task '{task_id}'. "
            f"Expected format: {expected_format}",
            task_id=task_id,
            data={"protocol": protocol, "expected_format": expected_format}
        )


class InvalidDependencyError(WorkflowBuilderError):
    """Invalid dependency specified."""

    def __init__(self, task_id: str, dependency: str, available_tasks: List[str]):
        super().__init__(
            f"Task '{task_id}' depends on '{dependency}' which doesn't exist. "
            f"Available tasks: {', '.join(available_tasks)}",
            workflow_id=None,
            data={"task_id": task_id, "dependency": dependency, "available_tasks": available_tasks}
        )


class DuplicateTaskError(WorkflowBuilderError):
    """Duplicate task ID in workflow."""

    def __init__(self, task_id: str):
        super().__init__(
            f"Duplicate task ID '{task_id}' in workflow",
            workflow_id=None,
            data={"task_id": task_id}
        )


class CircularDependencyError(WorkflowBuilderError):
    """Circular dependency detected in workflow."""

    def __init__(self, cycle: List[str]):
        super().__init__(
            f"Circular dependency detected: {' -> '.join(cycle)}",
            workflow_id=None,
            data={"cycle": cycle}
        )


class EmptyWorkflowError(WorkflowBuilderError):
    """Workflow has no tasks."""

    def __init__(self):
        super().__init__(
            "Workflow must contain at least one task",
            workflow_id=None
        )


class InvalidEventTypeError(TaskBuilderError):
    """Invalid event type specified."""

    def __init__(self, event_type: str, task_id: str, valid_types: List[str]):
        super().__init__(
            f"Invalid event type '{event_type}' for task '{task_id}'. "
            f"Valid types: {', '.join(valid_types)}",
            task_id=task_id,
            data={"event_type": event_type, "valid_types": valid_types}
        )


class InvalidParameterError(TaskBuilderError):
    """Invalid parameter specified."""

    def __init__(self, param_name: str, param_value: Any, task_id: str, reason: str):
        super().__init__(
            f"Invalid parameter '{param_name}' = {param_value} for task '{task_id}': {reason}",
            task_id=task_id,
            data={"param_name": param_name, "param_value": param_value, "reason": reason}
        )


class InvalidConfigurationError(TaskBuilderError):
    """Invalid configuration specified."""

    def __init__(self, config_name: str, config_value: Any, task_id: str, reason: str):
        super().__init__(
            f"Invalid configuration '{config_name}' = {config_value} for task '{task_id}': {reason}",
            task_id=task_id,
            data={"config_name": config_name, "config_value": config_value, "reason": reason}
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


# Enhanced Error Message Helpers

def find_closest_matches(target: str, candidates: List[str], n: int = 3, cutoff: float = 0.6) -> List[str]:
    """
    Find closest matches to target string from list of candidates.

    Args:
        target: Target string to match
        candidates: List of candidate strings
        n: Maximum number of matches to return
        cutoff: Similarity threshold (0-1)

    Returns:
        List of closest matching strings
    """
    return difflib.get_close_matches(target, candidates, n=n, cutoff=cutoff)


def format_suggestion(message: str, suggestions: List[str]) -> str:
    """
    Format error message with suggestions.

    Args:
        message: Base error message
        suggestions: List of suggestions

    Returns:
        Formatted error message with suggestions
    """
    if not suggestions:
        return message

    if len(suggestions) == 1:
        return f"{message}\n\nDid you mean: '{suggestions[0]}'?"
    else:
        suggestions_str = "\n".join(f"  - {s}" for s in suggestions)
        return f"{message}\n\nDid you mean one of these?\n{suggestions_str}"


class ProtocolNotFoundError(ProtocolError):
    """Protocol not found in registry - inherits from central ProtocolError."""

    def __init__(self, protocol: str, task_id: str, available_protocols: List[str]):
        # Find similar protocols
        suggestions = find_closest_matches(protocol, available_protocols)

        base_msg = f"Protocol '{protocol}' not found for task '{task_id}'"

        if suggestions:
            message = format_suggestion(base_msg, suggestions)
        else:
            protocols_str = ", ".join(available_protocols[:5])
            more = f" (and {len(available_protocols) - 5} more)" if len(available_protocols) > 5 else ""
            message = f"{base_msg}\n\nAvailable protocols: {protocols_str}{more}"

        super().__init__(
            message,
            code=ErrorCode.PROTOCOL_NOT_FOUND,
            protocol_id=protocol,
            data={
                "task_id": task_id,
                "available_protocols": available_protocols,
                "suggestions": suggestions
            }
        )


class MethodNotFoundError(ProtocolError):
    """Method not found for protocol - uses METHOD_NOT_SUPPORTED error code."""

    def __init__(self, method: str, protocol: str, task_id: str, available_methods: List[str]):
        # Find similar methods
        suggestions = find_closest_matches(method, available_methods)

        base_msg = f"Method '{method}' not found in protocol '{protocol}' for task '{task_id}'"

        if suggestions:
            message = format_suggestion(base_msg, suggestions)
        else:
            methods_str = ", ".join(available_methods)
            message = f"{base_msg}\n\nAvailable methods: {methods_str}"

        super().__init__(
            message,
            code=ErrorCode.METHOD_NOT_SUPPORTED,
            protocol_id=protocol,
            data={
                "method": method,
                "task_id": task_id,
                "available_methods": available_methods,
                "suggestions": suggestions
            }
        )


class ParameterSuggestionError(TaskBuilderError):
    """Parameter error with suggestions - uses TASK_PARAMETER_ERROR code."""

    def __init__(
        self,
        param_name: str,
        task_id: str,
        protocol: str,
        method: str,
        available_params: List[str],
        issue: str = "unknown"
    ):
        # Find similar parameters
        suggestions = find_closest_matches(param_name, available_params)

        base_msg = f"Parameter '{param_name}' {issue} for task '{task_id}' (protocol: {protocol}, method: {method})"

        if suggestions:
            message = format_suggestion(base_msg, suggestions)
        else:
            params_str = ", ".join(available_params)
            message = f"{base_msg}\n\nAvailable parameters: {params_str}"

        super().__init__(
            message,
            task_id=task_id,
            data={
                "param_name": param_name,
                "protocol": protocol,
                "method": method,
                "available_params": available_params,
                "suggestions": suggestions
            }
        )