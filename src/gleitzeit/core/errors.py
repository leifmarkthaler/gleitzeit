"""
Centralized Error Definitions for Gleitzeit V4

Provides a consistent error hierarchy and error codes for the entire system,
including JSON-RPC 2.0 compliant error codes and domain-specific exceptions.
"""

from enum import IntEnum
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
import json
import traceback


class ErrorCode(IntEnum):
    """
    Standardized error codes for Gleitzeit V4
    
    Follows JSON-RPC 2.0 specification with custom extensions:
    - -32768 to -32000: Reserved for JSON-RPC protocol errors
    - -31999 to -31000: Gleitzeit system errors
    - -30999 to -30000: Provider and protocol errors
    - -29999 to -29000: Task execution errors
    - -28999 to -28000: Workflow errors
    - -27999 to -27000: Queue and scheduling errors
    - -26999 to -26000: Persistence errors
    - -25999 to -25000: Network and communication errors
    """
    
    # JSON-RPC 2.0 Standard Errors (-32768 to -32000)
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    
    # Gleitzeit System Errors (-31999 to -31000)
    SYSTEM_NOT_INITIALIZED = -31001
    SYSTEM_SHUTDOWN = -31002
    CONFIGURATION_ERROR = -31003
    RESOURCE_EXHAUSTED = -31004
    RATE_LIMIT_EXCEEDED = -31005
    RESOURCE_NOT_FOUND = -31006
    NOT_FOUND = -31006
    ALREADY_EXISTS = -31007
    FORBIDDEN = -31008
    ACCOUNT_LOCKED = -31009
    EMAIL_NOT_VERIFIED = -31010
    SESSION_LIMIT_EXCEEDED = -31011
    
    # Provider and Protocol Errors (-30999 to -30000)
    PROTOCOL_NOT_FOUND = -30001
    PROVIDER_NOT_FOUND = -30002
    PROVIDER_NOT_AVAILABLE = -30003
    PROVIDER_INITIALIZATION_FAILED = -30004
    PROVIDER_UNHEALTHY = -30005
    PROVIDER_TIMEOUT = -30006
    PROVIDER_OVERLOADED = -30007
    METHOD_NOT_SUPPORTED = -30008
    PROTOCOL_VERSION_MISMATCH = -30009
    PROVIDER_ERROR = -30010  # Generic provider error
    
    # Task Execution Errors (-29999 to -29000)
    TASK_VALIDATION_FAILED = -29001
    TASK_EXECUTION_FAILED = -29002
    TASK_TIMEOUT = -29003
    TASK_CANCELLED = -29004
    TASK_DEPENDENCY_FAILED = -29005
    TASK_PARAMETER_ERROR = -29006
    TASK_RESULT_INVALID = -29007
    TASK_RETRY_EXHAUSTED = -29008
    TASK_NOT_FOUND = -29009
    TASK_RETRY_ERROR = -29010
    
    # Workflow Errors (-28999 to -28000)
    WORKFLOW_VALIDATION_FAILED = -28001
    WORKFLOW_NOT_FOUND = -28002
    WORKFLOW_EXECUTION_FAILED = -28003
    WORKFLOW_TIMEOUT = -28004
    WORKFLOW_CANCELLED = -28005
    WORKFLOW_CIRCULAR_DEPENDENCY = -28006
    WORKFLOW_INVALID_STATE = -28007
    
    # Queue and Scheduling Errors (-27999 to -27000)
    QUEUE_NOT_FOUND = -27001
    QUEUE_FULL = -27002
    QUEUE_EMPTY = -27003
    SCHEDULING_FAILED = -27004
    SCHEDULER_NOT_RUNNING = -27005
    
    # Persistence Errors (-26999 to -26000)
    PERSISTENCE_CONNECTION_FAILED = -26001
    PERSISTENCE_WRITE_FAILED = -26002
    PERSISTENCE_READ_FAILED = -26003
    PERSISTENCE_TRANSACTION_FAILED = -26004
    PERSISTENCE_INTEGRITY_ERROR = -26005
    
    # Network and Communication Errors (-25999 to -25000)
    NETWORK_UNREACHABLE = -25001
    CONNECTION_REFUSED = -25002
    CONNECTION_TIMEOUT = -25003
    CONNECTION_LOST = -25004
    AUTHENTICATION_FAILED = -25005
    AUTHORIZATION_FAILED = -25006
    
    # SystemManager and Distributed System Errors (-24999 to -24000)
    SYSTEM_MANAGER_INITIALIZATION_FAILED = -24001
    
    # Workflow Loader Errors (-23999 to -23000)
    WORKFLOW_LOADER_ERROR = -23001
    FILE_SYSTEM_ERROR = -23002
    SECURITY_ERROR = -23003
    RESOURCE_LIMIT_ERROR = -23004
    SERVICE_DISCOVERY_FAILED = -24002
    RESOURCE_ALLOCATION_FAILED = -24003
    DISTRIBUTED_REGISTRY_ERROR = -24004
    CONFIG_VALIDATION_FAILED = -24005
    HEALTH_CHECK_FAILED = -24006
    SERVICE_REGISTRATION_FAILED = -24007
    CLIENT_POOL_EXHAUSTED = -24008
    CLIENT_POOL_ERROR = -24009
    PROVIDER_HUB_ERROR = -24010
    SHARED_RESOURCE_ERROR = -24011
    COORDINATION_ERROR = -24012


@dataclass
class ErrorDetail:
    """Structured error detail with code, message, and optional data"""
    code: ErrorCode
    message: str
    data: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {
            "code": self.code.value,
            "message": self.message
        }
        if self.data is not None:
            result["data"] = self.data
        return result
    
    def to_jsonrpc_error(self) -> Dict[str, Any]:
        """Convert to JSON-RPC 2.0 error format"""
        return {
            "code": self.code.value,
            "message": self.message,
            "data": self.data
        }


class GleitzeitError(Exception):
    """Base exception for all Gleitzeit errors"""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        data: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}
        self.cause = cause
        
        # Add cause information to data if available
        if cause:
            self.data["cause"] = str(cause)
            self.data["cause_type"] = type(cause).__name__
    
    def to_error_detail(self) -> ErrorDetail:
        """Convert to ErrorDetail"""
        return ErrorDetail(
            code=self.code,
            message=self.message,
            data=self.data
        )
    
    def __str__(self) -> str:
        """String representation"""
        if self.cause:
            return f"[{self.code.name}] {self.message} (caused by: {self.cause})"
        return f"[{self.code.name}] {self.message}"
    
    def to_context_dict(self) -> Dict[str, Any]:
        """
        Get comprehensive error context for logging and debugging.
        
        Returns a dictionary with:
        - Error code and message
        - Full traceback
        - Cause information
        - Additional data
        """
        context = {
            "code": self.code.value,
            "code_name": self.code.name,
            "message": self.message,
            "type": type(self).__name__,
            "data": self.data
        }
        
        # Add traceback if available
        tb = traceback.format_exc()
        if tb and tb != "NoneType: None\n":
            context["traceback"] = tb
            
        # Add cause information
        if self.cause:
            context["cause"] = {
                "message": str(self.cause),
                "type": type(self.cause).__name__
            }
            # If cause has its own traceback, include it
            if hasattr(self.cause, '__traceback__'):
                cause_tb = ''.join(traceback.format_tb(self.cause.__traceback__))
                if cause_tb:
                    context["cause"]["traceback"] = cause_tb
                    
        return context
    
    def to_json_string(self) -> str:
        """
        Get error context as a JSON string for storage.
        Handles non-serializable objects gracefully.
        """
        try:
            return json.dumps(self.to_context_dict(), indent=2, default=str)
        except Exception:
            # Fallback to simple string if serialization fails
            return str(self)


# System Errors
class SystemError(GleitzeitError):
    """System-level errors"""
    
    def __init__(self, message: str, code: ErrorCode = ErrorCode.INTERNAL_ERROR, **kwargs):
        super().__init__(message, code, **kwargs)


class ConfigurationError(SystemError):
    """Configuration-related errors"""
    
    def __init__(self, message: str, **kwargs):
        super().__init__(message, ErrorCode.CONFIGURATION_ERROR, **kwargs)


class ResourceExhaustedError(SystemError):
    """Resource exhaustion errors"""
    
    def __init__(self, message: str, resource_type: str, **kwargs):
        data = kwargs.pop("data", {})
        data["resource_type"] = resource_type
        super().__init__(message, ErrorCode.RESOURCE_EXHAUSTED, data=data, **kwargs)


# Provider and Protocol Errors
class ProviderError(GleitzeitError):
    """Provider-related errors"""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.PROVIDER_NOT_AVAILABLE,
        provider_id: Optional[str] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if provider_id:
            data["provider_id"] = provider_id
        super().__init__(message, code, data=data, **kwargs)


class ProtocolError(GleitzeitError):
    """Protocol-related errors"""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.PROTOCOL_NOT_FOUND,
        protocol_id: Optional[str] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if protocol_id:
            data["protocol_id"] = protocol_id
        super().__init__(message, code, data=data, **kwargs)


class ProviderNotFoundError(ProviderError):
    """Provider not found error"""
    
    def __init__(self, provider_id: str, **kwargs):
        super().__init__(
            f"Provider not found: {provider_id}",
            ErrorCode.PROVIDER_NOT_FOUND,
            provider_id=provider_id,
            **kwargs
        )


class ProviderTimeoutError(ProviderError):
    """Provider timeout error"""
    
    def __init__(self, provider_id: str, timeout: float, **kwargs):
        data = kwargs.pop("data", {})
        data["timeout_seconds"] = timeout
        super().__init__(
            f"Provider {provider_id} timed out after {timeout}s",
            ErrorCode.PROVIDER_TIMEOUT,
            provider_id=provider_id,
            data=data,
            **kwargs
        )


class MethodNotSupportedError(ProviderError):
    """Method not supported by provider"""
    
    def __init__(self, method: str, provider_id: str, **kwargs):
        super().__init__(
            f"Method '{method}' not supported by provider '{provider_id}'",
            ErrorCode.METHOD_NOT_SUPPORTED,
            provider_id=provider_id,
            **kwargs
        )


class ProviderNotAvailableError(ProviderError):
    """Provider not available error"""
    
    def __init__(self, provider_id: str, reason: Optional[str] = None, **kwargs):
        message = f"Provider '{provider_id}' is not available"
        if reason:
            message += f": {reason}"
        super().__init__(
            message,
            ErrorCode.PROVIDER_NOT_AVAILABLE,
            provider_id=provider_id,
            **kwargs
        )


# Task Execution Errors
class TaskError(GleitzeitError):
    """Task execution errors"""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.TASK_EXECUTION_FAILED,
        task_id: Optional[str] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if task_id:
            data["task_id"] = task_id
        super().__init__(message, code, data=data, **kwargs)


class TaskValidationError(TaskError):
    """Task validation error"""
    
    def __init__(self, task_id: str, validation_errors: list, **kwargs):
        data = kwargs.pop("data", {})
        data["validation_errors"] = validation_errors
        super().__init__(
            f"Task validation failed: {', '.join(validation_errors)}",
            ErrorCode.TASK_VALIDATION_FAILED,
            task_id=task_id,
            data=data,
            **kwargs
        )


class TaskTimeoutError(TaskError):
    """Task timeout error"""
    
    def __init__(self, task_id: str, timeout: float, **kwargs):
        data = kwargs.pop("data", {})
        data["timeout_seconds"] = timeout
        super().__init__(
            f"Task {task_id} timed out after {timeout}s",
            ErrorCode.TASK_TIMEOUT,
            task_id=task_id,
            data=data,
            **kwargs
        )


class TaskExecutionError(TaskError):
    """Task execution error"""
    
    def __init__(self, task_id: Optional[str] = None, message: Optional[str] = None, **kwargs):
        if not message:
            message = f"Task {task_id} execution failed" if task_id else "Task execution failed"
        super().__init__(
            message,
            ErrorCode.TASK_EXECUTION_FAILED,
            task_id=task_id,
            **kwargs
        )


class TaskDependencyError(TaskError):
    """Task dependency error"""
    
    def __init__(self, task_id: str, failed_dependencies: list, **kwargs):
        data = kwargs.pop("data", {})
        data["failed_dependencies"] = failed_dependencies
        super().__init__(
            f"Task {task_id} dependencies failed: {', '.join(failed_dependencies)}",
            ErrorCode.TASK_DEPENDENCY_FAILED,
            task_id=task_id,
            data=data,
            **kwargs
        )


class InvalidParameterError(TaskError):
    """Invalid parameter error"""
    
    def __init__(self, param_name: str, reason: str, task_id: Optional[str] = None, **kwargs):
        super().__init__(
            f"Invalid parameter '{param_name}': {reason}",
            ErrorCode.INVALID_PARAMS,
            task_id=task_id,
            data={"parameter": param_name, "reason": reason},
            **kwargs
        )


# Workflow Errors
class WorkflowError(GleitzeitError):
    """Workflow-related errors"""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.WORKFLOW_EXECUTION_FAILED,
        workflow_id: Optional[str] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if workflow_id:
            data["workflow_id"] = workflow_id
        super().__init__(message, code, data=data, **kwargs)


class WorkflowValidationError(WorkflowError):
    """Workflow validation error"""
    
    def __init__(self, workflow_id: str, validation_errors: list, **kwargs):
        data = kwargs.pop("data", {})
        data["validation_errors"] = validation_errors
        super().__init__(
            f"Workflow validation failed: {', '.join(validation_errors)}",
            ErrorCode.WORKFLOW_VALIDATION_FAILED,
            workflow_id=workflow_id,
            data=data,
            **kwargs
        )


class WorkflowCircularDependencyError(WorkflowError):
    """Circular dependency detected in workflow"""
    
    def __init__(self, workflow_id: str, cycle: list, **kwargs):
        data = kwargs.pop("data", {})
        data["dependency_cycle"] = cycle
        super().__init__(
            f"Circular dependency detected: {' -> '.join(cycle)}",
            ErrorCode.WORKFLOW_CIRCULAR_DEPENDENCY,
            workflow_id=workflow_id,
            data=data,
            **kwargs
        )


# Queue and Scheduling Errors
class QueueError(GleitzeitError):
    """Queue-related errors"""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.QUEUE_NOT_FOUND,
        queue_name: Optional[str] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if queue_name:
            data["queue_name"] = queue_name
        super().__init__(message, code, data=data, **kwargs)


class QueueNotFoundError(QueueError):
    """Queue not found error"""
    
    def __init__(self, queue_name: str, **kwargs):
        super().__init__(
            f"Queue '{queue_name}' not found",
            ErrorCode.QUEUE_NOT_FOUND,
            queue_name=queue_name,
            **kwargs
        )


class QueueFullError(QueueError):
    """Queue is full error"""
    
    def __init__(self, queue_name: str, max_size: int, **kwargs):
        data = kwargs.pop("data", {})
        data["max_size"] = max_size
        super().__init__(
            f"Queue {queue_name} is full (max size: {max_size})",
            ErrorCode.QUEUE_FULL,
            queue_name=queue_name,
            data=data,
            **kwargs
        )


# Persistence Errors
class PersistenceError(GleitzeitError):
    """Persistence-related errors"""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.PERSISTENCE_CONNECTION_FAILED,
        backend: Optional[str] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if backend:
            data["backend"] = backend
        super().__init__(message, code, data=data, **kwargs)


class PersistenceConnectionError(PersistenceError):
    """Database connection error"""
    
    def __init__(self, backend: str, connection_string: str, **kwargs):
        data = kwargs.pop("data", {})
        data["connection_string"] = connection_string
        super().__init__(
            f"Failed to connect to {backend}: {connection_string}",
            ErrorCode.PERSISTENCE_CONNECTION_FAILED,
            backend=backend,
            data=data,
            **kwargs
        )


# Network and Communication Errors
class NetworkError(GleitzeitError):
    """Network-related errors"""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.NETWORK_UNREACHABLE,
        endpoint: Optional[str] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if endpoint:
            data["endpoint"] = endpoint
        super().__init__(message, code, data=data, **kwargs)


class ConnectionTimeoutError(NetworkError):
    """Connection timeout error"""
    
    def __init__(self, endpoint: str, timeout: float, **kwargs):
        data = kwargs.pop("data", {})
        data["timeout_seconds"] = timeout
        super().__init__(
            f"Connection to {endpoint} timed out after {timeout}s",
            ErrorCode.CONNECTION_TIMEOUT,
            endpoint=endpoint,
            data=data,
            **kwargs
        )


class AuthenticationError(NetworkError):
    """Authentication failed error"""
    
    def __init__(self, endpoint: str, auth_method: str, **kwargs):
        data = kwargs.pop("data", {})
        data["auth_method"] = auth_method
        super().__init__(
            f"Authentication failed for {endpoint} using {auth_method}",
            ErrorCode.AUTHENTICATION_FAILED,
            endpoint=endpoint,
            data=data,
            **kwargs
        )


class AuthorizationError(NetworkError):
    """Authorization failed error"""
    
    def __init__(self, resource: str, action: str, reason: Optional[str] = None, **kwargs):
        data = kwargs.pop("data", {})
        data["resource"] = resource
        data["action"] = action
        message = f"Authorization failed: {action} on {resource}"
        if reason:
            message += f" - {reason}"
            data["reason"] = reason
        super().__init__(
            message,
            ErrorCode.AUTHORIZATION_FAILED,
            data=data,
            **kwargs
        )


# Error handling utilities
def error_to_jsonrpc(error: Union[Exception, GleitzeitError]) -> Dict[str, Any]:
    """
    Convert an exception to JSON-RPC 2.0 error format
    
    Args:
        error: The error to convert
        
    Returns:
        JSON-RPC error dictionary
    """
    if isinstance(error, GleitzeitError):
        return error.to_error_detail().to_jsonrpc_error()
    
    # Map standard Python exceptions to error codes
    error_mapping = {
        ValueError: ErrorCode.INVALID_PARAMS,
        TypeError: ErrorCode.INVALID_PARAMS,
        KeyError: ErrorCode.INVALID_REQUEST,
        AttributeError: ErrorCode.INVALID_REQUEST,
        NotImplementedError: ErrorCode.METHOD_NOT_FOUND,
        TimeoutError: ErrorCode.TASK_TIMEOUT,
        ConnectionError: ErrorCode.CONNECTION_REFUSED,
        PermissionError: ErrorCode.AUTHORIZATION_FAILED,
    }
    
    error_code = ErrorCode.INTERNAL_ERROR
    for exc_type, code in error_mapping.items():
        if isinstance(error, exc_type):
            error_code = code
            break
    
    return {
        "code": error_code.value,
        "message": str(error),
        "data": {
            "exception_type": type(error).__name__
        }
    }


def is_retryable_error(error: Union[Exception, GleitzeitError]) -> bool:
    """
    Determine if an error is retryable
    
    Args:
        error: The error to check
        
    Returns:
        True if the error is retryable
    """
    if isinstance(error, GleitzeitError):
        # Retryable error codes
        retryable_codes = {
            ErrorCode.PROVIDER_TIMEOUT,
            ErrorCode.PROVIDER_OVERLOADED,
            ErrorCode.TASK_TIMEOUT,
            ErrorCode.CONNECTION_TIMEOUT,
            ErrorCode.CONNECTION_LOST,
            ErrorCode.NETWORK_UNREACHABLE,
            ErrorCode.RESOURCE_EXHAUSTED,
            ErrorCode.RATE_LIMIT_EXCEEDED,
            ErrorCode.PERSISTENCE_CONNECTION_FAILED,
            ErrorCode.TASK_EXECUTION_FAILED,  # Python script failures, etc. can be transient
        }
        return error.code in retryable_codes
    
    # Check standard exceptions
    retryable_exceptions = (
        TimeoutError,
        ConnectionError,
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
    )
    return isinstance(error, retryable_exceptions)


def get_error_severity(error: Union[Exception, GleitzeitError]) -> str:
    """
    Get the severity level of an error
    
    Args:
        error: The error to check
        
    Returns:
        Severity level: 'critical', 'error', 'warning', 'info'
    """
    if isinstance(error, GleitzeitError):
        # Critical errors that require immediate attention
        critical_codes = {
            ErrorCode.SYSTEM_SHUTDOWN,
            ErrorCode.PERSISTENCE_INTEGRITY_ERROR,
            ErrorCode.AUTHENTICATION_FAILED,
            ErrorCode.AUTHORIZATION_FAILED,
        }
        
        # Warning-level errors that are expected sometimes
        warning_codes = {
            ErrorCode.QUEUE_FULL,
            ErrorCode.RATE_LIMIT_EXCEEDED,
            ErrorCode.PROVIDER_OVERLOADED,
            ErrorCode.TASK_CANCELLED,
            ErrorCode.WORKFLOW_CANCELLED,
        }
        
        if error.code in critical_codes:
            return "critical"
        elif error.code in warning_codes:
            return "warning"
        else:
            return "error"
    
    # Default to error for unknown exceptions
    return "error"


# Event System Errors
class EventError(GleitzeitError):
    """Event system errors"""
    
    def __init__(self, message: str, code: ErrorCode = ErrorCode.INTERNAL_ERROR, **kwargs):
        super().__init__(message, code, **kwargs)


class InvalidEventTypeError(EventError):
    """Invalid event type error"""
    
    def __init__(self, message: str, event_type: Optional[str] = None, **kwargs):
        data = kwargs.pop("data", {})
        if event_type:
            data["event_type"] = event_type
        super().__init__(
            message,
            ErrorCode.INVALID_PARAMS,
            data=data,
            **kwargs
        )


# SystemManager and Distributed System Errors
class SystemManagerError(SystemError):
    """SystemManager operation failures"""
    
    def __init__(self, message: str, code: ErrorCode = ErrorCode.SYSTEM_MANAGER_INITIALIZATION_FAILED, **kwargs):
        super().__init__(message, code, **kwargs)


class ServiceDiscoveryError(SystemManagerError):
    """Service discovery failed"""
    
    def __init__(self, service_name: str, reason: Optional[str] = None, **kwargs):
        message = f"Service discovery failed for '{service_name}'"
        if reason:
            message += f": {reason}"
        data = kwargs.pop("data", {})
        data["service_name"] = service_name
        if reason:
            data["reason"] = reason
        super().__init__(
            message,
            ErrorCode.SERVICE_DISCOVERY_FAILED,
            data=data,
            **kwargs
        )


class ResourceAllocationError(SystemManagerError):
    """Resource allocation failed"""
    
    def __init__(self, resource_type: str, reason: Optional[str] = None, **kwargs):
        message = f"Resource allocation failed for '{resource_type}'"
        if reason:
            message += f": {reason}"
        data = kwargs.pop("data", {})
        data["resource_type"] = resource_type
        if reason:
            data["reason"] = reason
        super().__init__(
            message,
            ErrorCode.RESOURCE_ALLOCATION_FAILED,
            data=data,
            **kwargs
        )


class DistributedRegistryError(SystemManagerError):
    """Distributed registry operation failed"""
    
    def __init__(self, operation: str, component_id: Optional[str] = None, **kwargs):
        message = f"Registry operation '{operation}' failed"
        if component_id:
            message += f" for component '{component_id}'"
        data = kwargs.pop("data", {})
        data["operation"] = operation
        if component_id:
            data["component_id"] = component_id
        super().__init__(
            message,
            ErrorCode.DISTRIBUTED_REGISTRY_ERROR,
            data=data,
            **kwargs
        )


class ConfigValidationError(SystemManagerError):
    """Configuration validation failed"""
    
    def __init__(self, config_key: str, validation_error: str, **kwargs):
        data = kwargs.pop("data", {})
        data["config_key"] = config_key
        data["validation_error"] = validation_error
        super().__init__(
            f"Configuration validation failed for '{config_key}': {validation_error}",
            ErrorCode.CONFIG_VALIDATION_FAILED,
            data=data,
            **kwargs
        )


class HealthCheckError(SystemManagerError):
    """Health check failed"""
    
    def __init__(self, component_id: str, check_name: Optional[str] = None, **kwargs):
        message = f"Health check failed for component '{component_id}'"
        if check_name:
            message += f" (check: {check_name})"
        data = kwargs.pop("data", {})
        data["component_id"] = component_id
        if check_name:
            data["check_name"] = check_name
        super().__init__(
            message,
            ErrorCode.HEALTH_CHECK_FAILED,
            data=data,
            **kwargs
        )


class ServiceRegistrationError(SystemManagerError):
    """Service registration failed"""
    
    def __init__(self, service_id: str, operation: str, **kwargs):
        data = kwargs.pop("data", {})
        data["service_id"] = service_id
        data["operation"] = operation
        super().__init__(
            f"Service registration {operation} failed for '{service_id}'",
            ErrorCode.SERVICE_REGISTRATION_FAILED,
            data=data,
            **kwargs
        )


class ClientPoolError(GleitzeitError):
    """Client pool operation errors"""
    
    def __init__(self, message: str, code: ErrorCode = ErrorCode.CLIENT_POOL_ERROR, **kwargs):
        super().__init__(message, code, **kwargs)


class ClientPoolExhaustedError(ClientPoolError):
    """No available clients in pool"""
    
    def __init__(self, pool_id: str, max_size: int, **kwargs):
        data = kwargs.pop("data", {})
        data["pool_id"] = pool_id
        data["max_size"] = max_size
        super().__init__(
            f"Client pool '{pool_id}' is exhausted (max size: {max_size})",
            ErrorCode.CLIENT_POOL_EXHAUSTED,
            data=data,
            **kwargs
        )


class ProviderHubError(GleitzeitError):
    """Provider hub operation errors"""
    
    def __init__(self, message: str, hub_id: Optional[str] = None, **kwargs):
        data = kwargs.pop("data", {})
        if hub_id:
            data["hub_id"] = hub_id
        super().__init__(
            message,
            ErrorCode.PROVIDER_HUB_ERROR,
            data=data,
            **kwargs
        )


class SharedResourceError(SystemManagerError):
    """Shared resource coordination error"""
    
    def __init__(self, resource_id: str, operation: str, **kwargs):
        data = kwargs.pop("data", {})
        data["resource_id"] = resource_id
        data["operation"] = operation
        super().__init__(
            f"Shared resource operation '{operation}' failed for '{resource_id}'",
            ErrorCode.SHARED_RESOURCE_ERROR,
            data=data,
            **kwargs
        )


class CoordinationError(SystemManagerError):
    """Distributed coordination error"""
    
    def __init__(self, operation: str, nodes: Optional[list] = None, **kwargs):
        message = f"Distributed coordination failed for operation '{operation}'"
        data = kwargs.pop("data", {})
        data["operation"] = operation
        if nodes:
            data["affected_nodes"] = nodes
            message += f" (nodes: {', '.join(nodes)})"
        super().__init__(
            message,
            ErrorCode.COORDINATION_ERROR,
            data=data,
            **kwargs
        )

# Workflow Loader Errors
class WorkflowLoaderError(GleitzeitError):
    """Base class for workflow loader errors"""
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.WORKFLOW_LOADER_ERROR,
        file_path: Optional[str] = None,
        **kwargs
    ):
        data = kwargs.pop("data", {})
        if file_path:
            data["file_path"] = file_path
        super().__init__(message, code, data=data, **kwargs)


class FileSystemError(WorkflowLoaderError):
    """File system operation error"""
    
    def __init__(self, operation: str, path: str, reason: str, **kwargs):
        data = kwargs.pop("data", {})
        data["operation"] = operation
        data["path"] = path
        super().__init__(
            f"File system {operation} failed for '{path}': {reason}",
            ErrorCode.FILE_SYSTEM_ERROR,
            file_path=path,
            data=data,
            **kwargs
        )


class SecurityError(WorkflowLoaderError):
    """Security violation in workflow loading"""
    
    def __init__(self, violation_type: str, path: str, details: str, **kwargs):
        data = kwargs.pop("data", {})
        data["violation_type"] = violation_type
        data["path"] = path
        data["details"] = details
        super().__init__(
            f"Security violation ({violation_type}) for '{path}': {details}",
            ErrorCode.SECURITY_ERROR,
            file_path=path,
            data=data,
            **kwargs
        )


class ResourceLimitError(WorkflowLoaderError):
    """Resource limit exceeded"""
    
    def __init__(self, resource_type: str, current_value: Any, limit: Any, **kwargs):
        data = kwargs.pop("data", {})
        data["resource_type"] = resource_type
        data["current_value"] = current_value
        data["limit"] = limit
        super().__init__(
            f"Resource limit exceeded for {resource_type}: {current_value} > {limit}",
            ErrorCode.RESOURCE_LIMIT_ERROR,
            data=data,
            **kwargs
        )
