"""
Comprehensive Error Registry for Gleitzeit Cluster

This module provides a centralized error registry with structured error definitions,
user-friendly messages, resolution hints, and complete error metadata for the entire project.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional, List, Callable, Any
from datetime import datetime
import traceback

# Import existing error handling components
from .error_handling import ErrorCategory, ErrorSeverity


class ErrorDomain(Enum):
    """High-level error domains for organizing errors by system component"""
    INFRASTRUCTURE = "infrastructure"  # Redis, Socket.IO, services
    EXECUTION = "execution"           # Tasks, Ollama, Python functions  
    WORKFLOW = "workflow"             # Workflow logic, dependencies
    AUTHENTICATION = "auth"           # Users, API keys, permissions
    STORAGE = "storage"              # Files, data persistence
    NETWORK = "network"              # HTTP, connectivity
    VALIDATION = "validation"        # Input validation, schemas
    SYSTEM = "system"               # OS-level, resource issues
    CLI = "cli"                     # Command-line interface errors
    MONITORING = "monitoring"       # Observability and metrics


class ErrorCode(Enum):
    """Comprehensive error codes for the entire Gleitzeit project"""
    
    # Infrastructure Errors (1000-1999)
    REDIS_CONNECTION_FAILED = "GZ1001"
    REDIS_TIMEOUT = "GZ1002"
    REDIS_AUTHENTICATION_FAILED = "GZ1003"
    REDIS_MEMORY_FULL = "GZ1004"
    REDIS_COMMAND_FAILED = "GZ1005"
    REDIS_CLUSTER_DOWN = "GZ1006"
    
    SOCKETIO_CONNECTION_FAILED = "GZ1010"
    SOCKETIO_SERVER_START_FAILED = "GZ1011"
    SOCKETIO_CLIENT_TIMEOUT = "GZ1012"
    SOCKETIO_HANDSHAKE_FAILED = "GZ1013"
    SOCKETIO_TRANSPORT_ERROR = "GZ1014"
    
    SERVICE_START_FAILED = "GZ1020"
    SERVICE_HEALTH_CHECK_FAILED = "GZ1021"
    SERVICE_DEPENDENCY_MISSING = "GZ1022"
    SERVICE_PORT_IN_USE = "GZ1023"
    SERVICE_SHUTDOWN_TIMEOUT = "GZ1024"
    
    # External Service Errors (unified architecture)
    EXTERNAL_SERVICE_UNAVAILABLE = "GZ1025"
    EXTERNAL_SERVICE_TIMEOUT = "GZ1026"
    EXTERNAL_SERVICE_AUTHENTICATION_FAILED = "GZ1027"
    EXTERNAL_SERVICE_RATE_LIMITED = "GZ1028"
    PYTHON_EXECUTOR_SERVICE_FAILED = "GZ1029"
    INTERNAL_LLM_SERVICE_FAILED = "GZ1030"
    
    CLUSTER_START_FAILED = "GZ1035"
    CLUSTER_NOT_INITIALIZED = "GZ1036"
    CLUSTER_ALREADY_RUNNING = "GZ1037"
    CIRCUIT_BREAKER_OPEN = "GZ1038"
    
    # Execution Errors (2000-2999)
    TASK_EXECUTION_FAILED = "GZ2001"
    TASK_TIMEOUT = "GZ2002"
    TASK_VALIDATION_FAILED = "GZ2003"
    TASK_RETRY_EXHAUSTED = "GZ2004"
    TASK_NOT_FOUND = "GZ2005"
    TASK_CANCELLED = "GZ2006"
    
    OLLAMA_CONNECTION_FAILED = "GZ2010"
    OLLAMA_MODEL_NOT_FOUND = "GZ2011"
    OLLAMA_MODEL_LOAD_FAILED = "GZ2012"
    OLLAMA_GENERATION_FAILED = "GZ2013"
    OLLAMA_RATE_LIMITED = "GZ2014"
    OLLAMA_SERVER_OVERLOADED = "GZ2015"
    OLLAMA_MODEL_CORRUPTED = "GZ2016"
    
    PYTHON_FUNCTION_NOT_FOUND = "GZ2020"
    PYTHON_FUNCTION_ERROR = "GZ2021"
    PYTHON_IMPORT_ERROR = "GZ2022"
    PYTHON_SECURITY_VIOLATION = "GZ2023"
    PYTHON_SYNTAX_ERROR = "GZ2024"
    PYTHON_RUNTIME_ERROR = "GZ2025"
    
    VISION_MODEL_UNAVAILABLE = "GZ2030"
    IMAGE_FILE_NOT_FOUND = "GZ2031"
    IMAGE_FORMAT_UNSUPPORTED = "GZ2032"
    IMAGE_TOO_LARGE = "GZ2033"
    IMAGE_CORRUPTED = "GZ2034"
    
    HTTP_REQUEST_FAILED = "GZ2040"
    HTTP_TIMEOUT = "GZ2041"
    HTTP_RATE_LIMITED = "GZ2042"
    HTTP_AUTHENTICATION_FAILED = "GZ2043"
    HTTP_SERVER_ERROR = "GZ2044"
    
    # Workflow Errors (3000-3999)
    WORKFLOW_VALIDATION_FAILED = "GZ3001"
    WORKFLOW_NOT_FOUND = "GZ3002"
    CIRCULAR_DEPENDENCY = "GZ3003"
    WORKFLOW_TIMEOUT = "GZ3004"
    WORKFLOW_CANCELLED = "GZ3005"
    WORKFLOW_ALREADY_RUNNING = "GZ3006"
    WORKFLOW_PARSE_ERROR = "GZ3007"
    
    DEPENDENCY_NOT_SATISFIED = "GZ3010"
    TASK_GRAPH_INVALID = "GZ3011"
    RESOURCE_CONSTRAINT_VIOLATED = "GZ3012"
    PARAMETER_SUBSTITUTION_FAILED = "GZ3013"
    
    BATCH_PROCESSING_FAILED = "GZ3020"
    BATCH_SIZE_EXCEEDED = "GZ3021"
    FOLDER_NOT_FOUND = "GZ3022"
    FILE_DISCOVERY_FAILED = "GZ3023"
    
    # Authentication Errors (4000-4999)
    AUTH_TOKEN_INVALID = "GZ4001"
    AUTH_TOKEN_EXPIRED = "GZ4002"
    AUTH_INSUFFICIENT_PERMISSIONS = "GZ4003"
    AUTH_USER_NOT_FOUND = "GZ4004"
    AUTH_LOGIN_FAILED = "GZ4005"
    AUTH_LOGOUT_FAILED = "GZ4006"
    AUTH_SESSION_EXPIRED = "GZ4007"
    
    API_KEY_INVALID = "GZ4010"
    API_KEY_EXPIRED = "GZ4011"
    API_KEY_REVOKED = "GZ4012"
    API_KEY_NOT_FOUND = "GZ4013"
    API_KEY_CREATION_FAILED = "GZ4014"
    
    RBAC_ROLE_NOT_FOUND = "GZ4020"
    RBAC_PERMISSION_DENIED = "GZ4021"
    RBAC_ROLE_ASSIGNMENT_FAILED = "GZ4022"
    USER_CREATION_FAILED = "GZ4023"
    USER_ALREADY_EXISTS = "GZ4024"
    
    # Storage Errors (5000-5999)
    FILE_NOT_FOUND = "GZ5001"
    FILE_ACCESS_DENIED = "GZ5002"
    FILE_CORRUPTED = "GZ5003"
    DISK_SPACE_FULL = "GZ5004"
    FILE_LOCKED = "GZ5005"
    DIRECTORY_NOT_FOUND = "GZ5006"
    PERMISSION_DENIED = "GZ5007"
    
    DATA_CORRUPTION = "GZ5010"
    BACKUP_FAILED = "GZ5011"
    RESTORE_FAILED = "GZ5012"
    SERIALIZATION_FAILED = "GZ5013"
    DESERIALIZATION_FAILED = "GZ5014"
    
    CACHE_MISS = "GZ5020"
    CACHE_EXPIRED = "GZ5021"
    CACHE_FULL = "GZ5022"
    CACHE_CORRUPTION = "GZ5023"
    
    # Network Errors (6000-6999)
    NETWORK_UNREACHABLE = "GZ6001"
    DNS_RESOLUTION_FAILED = "GZ6002"
    CONNECTION_REFUSED = "GZ6003"
    CONNECTION_TIMEOUT = "GZ6004"
    CONNECTION_RESET = "GZ6005"
    SSL_HANDSHAKE_FAILED = "GZ6006"
    
    PROXY_ERROR = "GZ6010"
    FIREWALL_BLOCKED = "GZ6011"
    BANDWIDTH_EXCEEDED = "GZ6012"
    
    # Validation Errors (7000-7999)
    INPUT_VALIDATION_FAILED = "GZ7001"
    SCHEMA_VALIDATION_FAILED = "GZ7002"
    TYPE_VALIDATION_FAILED = "GZ7003"
    RANGE_VALIDATION_FAILED = "GZ7004"
    FORMAT_VALIDATION_FAILED = "GZ7005"
    REQUIRED_FIELD_MISSING = "GZ7006"
    
    YAML_PARSE_ERROR = "GZ7010"
    JSON_PARSE_ERROR = "GZ7011"
    CONFIG_VALIDATION_FAILED = "GZ7012"
    
    # System Errors (8000-8999)
    MEMORY_EXHAUSTED = "GZ8001"
    CPU_THRESHOLD_EXCEEDED = "GZ8002"
    PROCESS_LIMIT_REACHED = "GZ8003"
    SYSTEM_RESOURCE_UNAVAILABLE = "GZ8004"
    DISK_FULL = "GZ8005"
    TEMP_DIRECTORY_UNAVAILABLE = "GZ8006"
    
    OS_COMMAND_FAILED = "GZ8010"
    ENVIRONMENT_VARIABLE_MISSING = "GZ8011"
    DEPENDENCY_NOT_INSTALLED = "GZ8012"
    VERSION_COMPATIBILITY_ERROR = "GZ8013"
    
    # CLI Errors (9000-9999)
    CLI_COMMAND_NOT_FOUND = "GZ9001"
    CLI_INVALID_ARGUMENTS = "GZ9002"
    CLI_CONFIG_NOT_FOUND = "GZ9003"
    CLI_PERMISSION_DENIED = "GZ9004"
    CLI_EXECUTION_FAILED = "GZ9005"
    
    CLI_AUTH_REQUIRED = "GZ9010"
    CLI_INTERACTIVE_MODE_FAILED = "GZ9011"
    CLI_OUTPUT_FORMAT_INVALID = "GZ9012"
    
    # Monitoring Errors (9500-9999)
    METRICS_COLLECTION_FAILED = "GZ9501"
    LOG_WRITE_FAILED = "GZ9502"
    HEALTH_CHECK_FAILED = "GZ9503"
    TELEMETRY_DISABLED = "GZ9504"
    DASHBOARD_UNAVAILABLE = "GZ9505"
    MONITORING_CLIENT_CONNECT_FAILED = "GZ9506"
    MONITORING_SUBSCRIPTION_FAILED = "GZ9507"
    METRICS_BROADCAST_FAILED = "GZ9508"
    MONITORING_DATA_CORRUPT = "GZ9509"
    SOCKETIO_MONITORING_DISABLED = "GZ9510"
    METRICS_HISTORY_OVERFLOW = "GZ9511"
    NODE_HEARTBEAT_TIMEOUT = "GZ9512"
    MONITORING_AUTHENTICATION_FAILED = "GZ9513"
    REAL_TIME_STREAM_ERROR = "GZ9514"
    METRICS_AGGREGATION_FAILED = "GZ9515"


@dataclass
class ErrorDefinition:
    """Complete error definition with all metadata"""
    code: ErrorCode
    domain: ErrorDomain
    message: str
    category: ErrorCategory
    severity: ErrorSeverity
    retry_after: Optional[int] = None
    user_message: Optional[str] = None
    resolution_hint: Optional[str] = None
    documentation_url: Optional[str] = None
    related_errors: Optional[List[ErrorCode]] = None
    custom_handler: Optional[Callable] = None
    tags: Optional[List[str]] = None  # For search and filtering


# Comprehensive error catalog
ERROR_CATALOG: Dict[ErrorCode, ErrorDefinition] = {
    
    # Infrastructure Errors
    ErrorCode.REDIS_CONNECTION_FAILED: ErrorDefinition(
        code=ErrorCode.REDIS_CONNECTION_FAILED,
        domain=ErrorDomain.INFRASTRUCTURE,
        message="Failed to establish connection to Redis server",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.MEDIUM,
        retry_after=5,
        user_message="Connection to Redis failed, falling back to local storage",
        resolution_hint="Check Redis server status: redis-cli ping or docker ps | grep redis",
        documentation_url="https://docs.gleitzeit.dev/troubleshooting/redis",
        related_errors=[ErrorCode.SERVICE_START_FAILED, ErrorCode.REDIS_TIMEOUT],
        tags=["redis", "connection", "infrastructure"]
    ),
    
    ErrorCode.REDIS_TIMEOUT: ErrorDefinition(
        code=ErrorCode.REDIS_TIMEOUT,
        domain=ErrorDomain.INFRASTRUCTURE,
        message="Redis operation timed out",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.MEDIUM,
        retry_after=3,
        user_message="Redis is responding slowly, retrying operation",
        resolution_hint="Check Redis performance: redis-cli --latency -h <host>",
        related_errors=[ErrorCode.REDIS_CONNECTION_FAILED],
        tags=["redis", "timeout", "performance"]
    ),
    
    ErrorCode.SOCKETIO_CONNECTION_FAILED: ErrorDefinition(
        code=ErrorCode.SOCKETIO_CONNECTION_FAILED,
        domain=ErrorDomain.INFRASTRUCTURE,
        message="Failed to establish Socket.IO connection",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.MEDIUM,
        retry_after=10,
        user_message="Real-time features unavailable, using fallback mode",
        resolution_hint="Check if Socket.IO server is running on the configured port",
        related_errors=[ErrorCode.SOCKETIO_SERVER_START_FAILED],
        tags=["socketio", "connection", "realtime"]
    ),
    
    ErrorCode.SOCKETIO_SERVER_START_FAILED: ErrorDefinition(
        code=ErrorCode.SOCKETIO_SERVER_START_FAILED,
        domain=ErrorDomain.INFRASTRUCTURE,
        message="Failed to start Socket.IO server",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.HIGH,
        user_message="Real-time server failed to start",
        resolution_hint="Check if port is available and server dependencies are installed",
        related_errors=[ErrorCode.SOCKETIO_CONNECTION_FAILED],
        tags=["socketio", "server", "startup"]
    ),
    
    ErrorCode.SERVICE_START_FAILED: ErrorDefinition(
        code=ErrorCode.SERVICE_START_FAILED,
        domain=ErrorDomain.INFRASTRUCTURE,
        message="Failed to start required service",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.HIGH,
        user_message="A required service failed to start",
        resolution_hint="Check service logs and ensure dependencies are installed",
        tags=["service", "startup", "dependencies"]
    ),
    
    # External Service Errors (unified architecture)
    ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE: ErrorDefinition(
        code=ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE,
        domain=ErrorDomain.INFRASTRUCTURE,
        message="External service is unavailable",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.MEDIUM,
        retry_after=10,
        user_message="External service is temporarily unavailable",
        resolution_hint="Check service status and retry in a few moments",
        tags=["external", "service", "availability"]
    ),
    
    ErrorCode.EXTERNAL_SERVICE_TIMEOUT: ErrorDefinition(
        code=ErrorCode.EXTERNAL_SERVICE_TIMEOUT,
        domain=ErrorDomain.INFRASTRUCTURE,
        message="External service request timed out",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.MEDIUM,
        retry_after=5,
        user_message="External service is taking too long to respond",
        resolution_hint="Check service performance or increase timeout settings",
        tags=["external", "service", "timeout"]
    ),
    
    ErrorCode.PYTHON_EXECUTOR_SERVICE_FAILED: ErrorDefinition(
        code=ErrorCode.PYTHON_EXECUTOR_SERVICE_FAILED,
        domain=ErrorDomain.EXECUTION,
        message="Python executor service failed",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.HIGH,
        user_message="Python task execution service is not working",
        resolution_hint="Start Python executor service: python services/python_executor_service.py",
        tags=["python", "executor", "service"]
    ),
    
    ErrorCode.INTERNAL_LLM_SERVICE_FAILED: ErrorDefinition(
        code=ErrorCode.INTERNAL_LLM_SERVICE_FAILED,
        domain=ErrorDomain.EXECUTION,
        message="Internal LLM service failed",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.HIGH,
        user_message="Internal LLM service is not working",
        resolution_hint="Start internal LLM service: python services/internal_llm_service.py",
        tags=["llm", "internal", "service"]
    ),
    
    ErrorCode.CLUSTER_START_FAILED: ErrorDefinition(
        code=ErrorCode.CLUSTER_START_FAILED,
        domain=ErrorDomain.INFRASTRUCTURE,
        message="Cluster initialization failed",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.CRITICAL,
        user_message="Gleitzeit cluster failed to start",
        resolution_hint="Check logs for specific service failures and ensure all dependencies are running",
        tags=["cluster", "startup", "critical"]
    ),
    
    # Execution Errors
    ErrorCode.OLLAMA_MODEL_NOT_FOUND: ErrorDefinition(
        code=ErrorCode.OLLAMA_MODEL_NOT_FOUND,
        domain=ErrorDomain.EXECUTION,
        message="Requested Ollama model is not available",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.HIGH,
        user_message="The AI model you requested is not installed",
        resolution_hint="Install the model: ollama pull <model_name>",
        documentation_url="https://docs.gleitzeit.dev/models/installation",
        related_errors=[ErrorCode.OLLAMA_CONNECTION_FAILED],
        tags=["ollama", "model", "missing"]
    ),
    
    ErrorCode.OLLAMA_CONNECTION_FAILED: ErrorDefinition(
        code=ErrorCode.OLLAMA_CONNECTION_FAILED,
        domain=ErrorDomain.EXECUTION,
        message="Cannot connect to Ollama server",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.HIGH,
        retry_after=5,
        user_message="AI service is unavailable",
        resolution_hint="Start Ollama: ollama serve or check if running on correct port",
        related_errors=[ErrorCode.OLLAMA_MODEL_NOT_FOUND],
        tags=["ollama", "connection", "service"]
    ),
    
    ErrorCode.TASK_EXECUTION_FAILED: ErrorDefinition(
        code=ErrorCode.TASK_EXECUTION_FAILED,
        domain=ErrorDomain.EXECUTION,
        message="Task execution encountered an error",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.MEDIUM,
        retry_after=2,
        user_message="A task in your workflow failed to execute",
        resolution_hint="Check task parameters and dependencies",
        tags=["task", "execution", "workflow"]
    ),
    
    ErrorCode.PYTHON_FUNCTION_NOT_FOUND: ErrorDefinition(
        code=ErrorCode.PYTHON_FUNCTION_NOT_FOUND,
        domain=ErrorDomain.EXECUTION,
        message="Python function not found in registry",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.MEDIUM,
        user_message="The function you requested is not available",
        resolution_hint="Check available functions: gleitzeit functions list",
        tags=["python", "function", "registry"]
    ),
    
    ErrorCode.IMAGE_FILE_NOT_FOUND: ErrorDefinition(
        code=ErrorCode.IMAGE_FILE_NOT_FOUND,
        domain=ErrorDomain.EXECUTION,
        message="Image file not found for vision task",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.MEDIUM,
        user_message="The image file you specified cannot be found",
        resolution_hint="Check file path and ensure image exists",
        tags=["vision", "image", "file"]
    ),
    
    # Workflow Errors
    ErrorCode.CIRCULAR_DEPENDENCY: ErrorDefinition(
        code=ErrorCode.CIRCULAR_DEPENDENCY,
        domain=ErrorDomain.WORKFLOW,
        message="Workflow contains circular task dependencies",
        category=ErrorCategory.VALIDATION,
        severity=ErrorSeverity.HIGH,
        user_message="Your workflow has tasks that depend on each other in a loop",
        resolution_hint="Review task dependencies and remove circular references",
        documentation_url="https://docs.gleitzeit.dev/workflows/dependencies",
        tags=["workflow", "dependencies", "validation"]
    ),
    
    ErrorCode.WORKFLOW_NOT_FOUND: ErrorDefinition(
        code=ErrorCode.WORKFLOW_NOT_FOUND,
        domain=ErrorDomain.WORKFLOW,
        message="Workflow not found",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.MEDIUM,
        user_message="The workflow you requested does not exist",
        resolution_hint="Check workflow ID or create the workflow first",
        tags=["workflow", "missing"]
    ),
    
    ErrorCode.BATCH_PROCESSING_FAILED: ErrorDefinition(
        code=ErrorCode.BATCH_PROCESSING_FAILED,
        domain=ErrorDomain.WORKFLOW,
        message="Batch processing operation failed",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.MEDIUM,
        retry_after=5,
        user_message="Batch operation encountered errors",
        resolution_hint="Check individual item errors and reduce batch size if needed",
        tags=["batch", "processing", "workflow"]
    ),
    
    # Authentication Errors
    ErrorCode.AUTH_TOKEN_EXPIRED: ErrorDefinition(
        code=ErrorCode.AUTH_TOKEN_EXPIRED,
        domain=ErrorDomain.AUTHENTICATION,
        message="Authentication token has expired",
        category=ErrorCategory.AUTHENTICATION,
        severity=ErrorSeverity.MEDIUM,
        user_message="Your session has expired, please log in again",
        resolution_hint="Authenticate: gleitzeit auth login",
        documentation_url="https://docs.gleitzeit.dev/auth/tokens",
        tags=["auth", "token", "expired"]
    ),
    
    ErrorCode.API_KEY_INVALID: ErrorDefinition(
        code=ErrorCode.API_KEY_INVALID,
        domain=ErrorDomain.AUTHENTICATION,
        message="API key is invalid or malformed",
        category=ErrorCategory.AUTHENTICATION,
        severity=ErrorSeverity.MEDIUM,
        user_message="Your API key is invalid",
        resolution_hint="Check API key format or create new key: gleitzeit auth key create",
        tags=["auth", "api-key", "invalid"]
    ),
    
    ErrorCode.RBAC_PERMISSION_DENIED: ErrorDefinition(
        code=ErrorCode.RBAC_PERMISSION_DENIED,
        domain=ErrorDomain.AUTHENTICATION,
        message="Insufficient permissions for requested operation",
        category=ErrorCategory.AUTHENTICATION,
        severity=ErrorSeverity.MEDIUM,
        user_message="You don't have permission to perform this action",
        resolution_hint="Contact administrator to grant required permissions",
        tags=["auth", "rbac", "permissions"]
    ),
    
    # Storage Errors
    ErrorCode.FILE_NOT_FOUND: ErrorDefinition(
        code=ErrorCode.FILE_NOT_FOUND,
        domain=ErrorDomain.STORAGE,
        message="Requested file does not exist",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.MEDIUM,
        user_message="The file you specified cannot be found",
        resolution_hint="Check file path and ensure file exists",
        tags=["file", "storage", "missing"]
    ),
    
    ErrorCode.DISK_SPACE_FULL: ErrorDefinition(
        code=ErrorCode.DISK_SPACE_FULL,
        domain=ErrorDomain.STORAGE,
        message="Insufficient disk space for operation",
        category=ErrorCategory.RESOURCE,
        severity=ErrorSeverity.HIGH,
        user_message="Not enough disk space to complete operation",
        resolution_hint="Free up disk space or configure different storage location",
        tags=["disk", "space", "storage"]
    ),
    
    # Network Errors
    ErrorCode.NETWORK_UNREACHABLE: ErrorDefinition(
        code=ErrorCode.NETWORK_UNREACHABLE,
        domain=ErrorDomain.NETWORK,
        message="Network destination is unreachable",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.MEDIUM,
        retry_after=10,
        user_message="Network connection failed",
        resolution_hint="Check network connectivity and firewall settings",
        tags=["network", "connectivity"]
    ),
    
    # Validation Errors
    ErrorCode.INPUT_VALIDATION_FAILED: ErrorDefinition(
        code=ErrorCode.INPUT_VALIDATION_FAILED,
        domain=ErrorDomain.VALIDATION,
        message="Input validation failed",
        category=ErrorCategory.VALIDATION,
        severity=ErrorSeverity.LOW,
        user_message="The input you provided is invalid",
        resolution_hint="Check input format and requirements",
        tags=["validation", "input"]
    ),
    
    # System Errors
    ErrorCode.MEMORY_EXHAUSTED: ErrorDefinition(
        code=ErrorCode.MEMORY_EXHAUSTED,
        domain=ErrorDomain.SYSTEM,
        message="System has run out of available memory",
        category=ErrorCategory.RESOURCE,
        severity=ErrorSeverity.CRITICAL,
        user_message="System is out of memory",
        resolution_hint="Reduce workload size or increase available memory",
        tags=["memory", "system", "resources"]
    ),
    
    # CLI Errors
    ErrorCode.CLI_COMMAND_NOT_FOUND: ErrorDefinition(
        code=ErrorCode.CLI_COMMAND_NOT_FOUND,
        domain=ErrorDomain.CLI,
        message="CLI command not recognized",
        category=ErrorCategory.VALIDATION,
        severity=ErrorSeverity.LOW,
        user_message="Command not found",
        resolution_hint="Run 'gleitzeit --help' to see available commands",
        tags=["cli", "command"]
    ),
    
    ErrorCode.CLI_AUTH_REQUIRED: ErrorDefinition(
        code=ErrorCode.CLI_AUTH_REQUIRED,
        domain=ErrorDomain.CLI,
        message="Authentication required for this command",
        category=ErrorCategory.AUTHENTICATION,
        severity=ErrorSeverity.MEDIUM,
        user_message="Please log in to use this command",
        resolution_hint="Run: gleitzeit auth login",
        tags=["cli", "auth", "required"]
    ),
    
    # Monitoring Errors
    ErrorCode.METRICS_COLLECTION_FAILED: ErrorDefinition(
        code=ErrorCode.METRICS_COLLECTION_FAILED,
        domain=ErrorDomain.MONITORING,
        message="Failed to collect system metrics",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.LOW,
        retry_after=10,
        user_message="Metrics collection temporarily unavailable",
        resolution_hint="Check system resource availability and permissions",
        tags=["metrics", "collection", "system"]
    ),
    
    ErrorCode.LOG_WRITE_FAILED: ErrorDefinition(
        code=ErrorCode.LOG_WRITE_FAILED,
        domain=ErrorDomain.MONITORING,
        message="Failed to write monitoring logs",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.LOW,
        user_message="Log writing temporarily unavailable",
        resolution_hint="Check disk space and file permissions",
        tags=["logging", "disk", "permissions"]
    ),
    
    ErrorCode.HEALTH_CHECK_FAILED: ErrorDefinition(
        code=ErrorCode.HEALTH_CHECK_FAILED,
        domain=ErrorDomain.MONITORING,
        message="System health check failed",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.MEDIUM,
        user_message="System health check failed",
        resolution_hint="Check component status and logs",
        tags=["health", "monitoring", "check"]
    ),
    
    ErrorCode.TELEMETRY_DISABLED: ErrorDefinition(
        code=ErrorCode.TELEMETRY_DISABLED,
        domain=ErrorDomain.MONITORING,
        message="Telemetry collection is disabled",
        category=ErrorCategory.VALIDATION,
        severity=ErrorSeverity.LOW,
        user_message="Monitoring data may be limited",
        resolution_hint="Enable telemetry in configuration if detailed monitoring is needed",
        tags=["telemetry", "config", "monitoring"]
    ),
    
    ErrorCode.DASHBOARD_UNAVAILABLE: ErrorDefinition(
        code=ErrorCode.DASHBOARD_UNAVAILABLE,
        domain=ErrorDomain.MONITORING,
        message="Monitoring dashboard is not available",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.LOW,
        user_message="Web dashboard temporarily unavailable",
        resolution_hint="Check if Socket.IO server is running on http://localhost:8000",
        tags=["dashboard", "ui", "socketio"]
    ),
    
    ErrorCode.MONITORING_CLIENT_CONNECT_FAILED: ErrorDefinition(
        code=ErrorCode.MONITORING_CLIENT_CONNECT_FAILED,
        domain=ErrorDomain.MONITORING,
        message="Failed to connect monitoring client to server",
        category=ErrorCategory.NETWORK,
        severity=ErrorSeverity.MEDIUM,
        retry_after=5,
        user_message="Cannot connect to monitoring server",
        resolution_hint="Verify Socket.IO server is running: netstat -an | grep 8000",
        documentation_url="https://docs.gleitzeit.dev/monitoring/connection-issues",
        tags=["client", "connection", "socketio"]
    ),
    
    ErrorCode.MONITORING_SUBSCRIPTION_FAILED: ErrorDefinition(
        code=ErrorCode.MONITORING_SUBSCRIPTION_FAILED,
        domain=ErrorDomain.MONITORING,
        message="Failed to subscribe to monitoring events",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.LOW,
        retry_after=3,
        user_message="Real-time monitoring subscription failed",
        resolution_hint="Try reconnecting or restart monitoring client",
        tags=["subscription", "events", "realtime"]
    ),
    
    ErrorCode.METRICS_BROADCAST_FAILED: ErrorDefinition(
        code=ErrorCode.METRICS_BROADCAST_FAILED,
        domain=ErrorDomain.MONITORING,
        message="Failed to broadcast metrics to monitoring clients",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.LOW,
        user_message="Metrics updates may be delayed",
        resolution_hint="Check network connectivity and server resources",
        tags=["broadcast", "metrics", "network"]
    ),
    
    ErrorCode.MONITORING_DATA_CORRUPT: ErrorDefinition(
        code=ErrorCode.MONITORING_DATA_CORRUPT,
        domain=ErrorDomain.MONITORING,
        message="Monitoring data is corrupted or invalid",
        category=ErrorCategory.PERMANENT,
        severity=ErrorSeverity.MEDIUM,
        user_message="Some monitoring data may be inaccurate",
        resolution_hint="Restart monitoring services to reset data collection",
        tags=["corruption", "data", "invalid"]
    ),
    
    ErrorCode.SOCKETIO_MONITORING_DISABLED: ErrorDefinition(
        code=ErrorCode.SOCKETIO_MONITORING_DISABLED,
        domain=ErrorDomain.MONITORING,
        message="Socket.IO real-time monitoring is disabled",
        category=ErrorCategory.VALIDATION,
        severity=ErrorSeverity.LOW,
        user_message="Real-time monitoring not available",
        resolution_hint="Enable Socket.IO monitoring in cluster configuration: enable_socketio=True",
        tags=["socketio", "disabled", "config"]
    ),
    
    ErrorCode.METRICS_HISTORY_OVERFLOW: ErrorDefinition(
        code=ErrorCode.METRICS_HISTORY_OVERFLOW,
        domain=ErrorDomain.MONITORING,
        message="Metrics history buffer overflow",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.LOW,
        user_message="Historical metrics data truncated",
        resolution_hint="Consider reducing metrics collection interval or increasing buffer size",
        tags=["history", "buffer", "memory"]
    ),
    
    ErrorCode.NODE_HEARTBEAT_TIMEOUT: ErrorDefinition(
        code=ErrorCode.NODE_HEARTBEAT_TIMEOUT,
        domain=ErrorDomain.MONITORING,
        message="Executor node heartbeat timeout",
        category=ErrorCategory.NETWORK,
        severity=ErrorSeverity.HIGH,
        user_message="Executor node appears offline",
        resolution_hint="Check node connectivity and restart executor if needed",
        related_errors=[ErrorCode.SOCKETIO_CLIENT_TIMEOUT],
        tags=["heartbeat", "timeout", "node"]
    ),
    
    ErrorCode.MONITORING_AUTHENTICATION_FAILED: ErrorDefinition(
        code=ErrorCode.MONITORING_AUTHENTICATION_FAILED,
        domain=ErrorDomain.MONITORING,
        message="Monitoring client authentication failed",
        category=ErrorCategory.AUTHENTICATION,
        severity=ErrorSeverity.MEDIUM,
        user_message="Access to monitoring denied",
        resolution_hint="Check authentication credentials and permissions",
        related_errors=[ErrorCode.AUTH_TOKEN_EXPIRED, ErrorCode.AUTH_TOKEN_INVALID],
        tags=["auth", "monitoring", "access"]
    ),
    
    ErrorCode.REAL_TIME_STREAM_ERROR: ErrorDefinition(
        code=ErrorCode.REAL_TIME_STREAM_ERROR,
        domain=ErrorDomain.MONITORING,
        message="Real-time data stream error",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.MEDIUM,
        retry_after=2,
        user_message="Real-time monitoring stream interrupted",
        resolution_hint="Check network connection and try reconnecting",
        tags=["stream", "realtime", "network"]
    ),
    
    ErrorCode.METRICS_AGGREGATION_FAILED: ErrorDefinition(
        code=ErrorCode.METRICS_AGGREGATION_FAILED,
        domain=ErrorDomain.MONITORING,
        message="Failed to aggregate metrics data",
        category=ErrorCategory.TRANSIENT,
        severity=ErrorSeverity.LOW,
        user_message="Some aggregate metrics may be unavailable",
        resolution_hint="Check data sources and computational resources",
        tags=["aggregation", "computation", "data"]
    ),
}


class GleitzeitError(Exception):
    """Base exception for Gleitzeit with structured error information"""
    
    def __init__(self, 
                 error_code: ErrorCode, 
                 context: Optional[Dict[str, Any]] = None, 
                 cause: Optional[Exception] = None,
                 custom_message: Optional[str] = None):
        """
        Initialize Gleitzeit error
        
        Args:
            error_code: The specific error code from ErrorCode enum
            context: Additional context information (task_id, file_path, etc.)
            cause: The underlying exception that caused this error
            custom_message: Optional custom message to override default
        """
        self.error_code = error_code
        self.definition = ERROR_CATALOG.get(error_code)
        if not self.definition:
            raise ValueError(f"Error code {error_code} not found in catalog")
            
        self.context = context or {}
        self.cause = cause
        self.custom_message = custom_message
        self.timestamp = datetime.utcnow()
        
        # Set the exception message
        message = custom_message or self.definition.message
        super().__init__(message)
    
    @property
    def user_friendly_message(self) -> str:
        """Get user-friendly error message"""
        return self.definition.user_message or self.definition.message
    
    @property
    def resolution_hint(self) -> Optional[str]:
        """Get resolution hint for this error"""
        return self.definition.resolution_hint
    
    @property
    def documentation_url(self) -> Optional[str]:
        """Get documentation URL for this error"""
        return self.definition.documentation_url
    
    @property
    def should_retry(self) -> bool:
        """Check if this error should be retried"""
        return self.definition.category == ErrorCategory.TRANSIENT
    
    @property
    def retry_after_seconds(self) -> Optional[int]:
        """Get recommended retry delay in seconds"""
        return self.definition.retry_after
    
    def to_error_info(self):
        """Convert to ErrorInfo for compatibility with existing error handling"""
        from .error_handling import ErrorInfo
        
        return ErrorInfo(
            error_type=self.error_code.value,
            message=self.custom_message or self.definition.message,
            category=self.definition.category,
            severity=self.definition.severity,
            timestamp=self.timestamp,
            context=self.context,
            retry_after=self.definition.retry_after,
            stacktrace=traceback.format_exc() if self.cause else None
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for serialization"""
        return {
            "error_code": self.error_code.value,
            "domain": self.definition.domain.value,
            "message": self.custom_message or self.definition.message,
            "user_message": self.user_friendly_message,
            "category": self.definition.category.value,
            "severity": self.definition.severity.value,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "resolution_hint": self.resolution_hint,
            "documentation_url": self.documentation_url,
            "retry_after": self.retry_after_seconds,
            "cause": str(self.cause) if self.cause else None
        }
    
    def __str__(self) -> str:
        """String representation of the error"""
        base_msg = f"[{self.error_code.value}] {self.definition.message}"
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            base_msg += f" (context: {context_str})"
        return base_msg


# Helper functions for error management
def get_error_definition(error_code: ErrorCode) -> Optional[ErrorDefinition]:
    """Get error definition by code"""
    return ERROR_CATALOG.get(error_code)


def get_errors_by_domain(domain: ErrorDomain) -> List[ErrorDefinition]:
    """Get all errors for a specific domain"""
    return [defn for defn in ERROR_CATALOG.values() if defn.domain == domain]


def get_errors_by_severity(severity: ErrorSeverity) -> List[ErrorDefinition]:
    """Get all errors of a specific severity"""
    return [defn for defn in ERROR_CATALOG.values() if defn.severity == severity]


def get_errors_by_category(category: ErrorCategory) -> List[ErrorDefinition]:
    """Get all errors of a specific category"""
    return [defn for defn in ERROR_CATALOG.values() if defn.category == category]


def search_errors(query: str) -> List[ErrorDefinition]:
    """Search errors by message, code, resolution hint, or tags"""
    query_lower = query.lower()
    results = []
    
    for defn in ERROR_CATALOG.values():
        # Search in message
        if query_lower in defn.message.lower():
            results.append(defn)
            continue
            
        # Search in error code
        if query_lower in defn.code.value.lower():
            results.append(defn)
            continue
            
        # Search in resolution hint
        if defn.resolution_hint and query_lower in defn.resolution_hint.lower():
            results.append(defn)
            continue
            
        # Search in tags
        if defn.tags and any(query_lower in tag.lower() for tag in defn.tags):
            results.append(defn)
            continue
            
        # Search in user message
        if defn.user_message and query_lower in defn.user_message.lower():
            results.append(defn)
            continue
    
    return results


def get_related_errors(error_code: ErrorCode) -> List[ErrorDefinition]:
    """Get errors related to the given error code"""
    definition = ERROR_CATALOG.get(error_code)
    if not definition or not definition.related_errors:
        return []
    
    return [ERROR_CATALOG[code] for code in definition.related_errors if code in ERROR_CATALOG]


def validate_error_catalog() -> List[str]:
    """Validate the error catalog for consistency and completeness"""
    issues = []
    
    # Check for duplicate codes
    codes_seen = set()
    for error_code, definition in ERROR_CATALOG.items():
        if definition.code.value in codes_seen:
            issues.append(f"Duplicate error code: {definition.code.value}")
        codes_seen.add(definition.code.value)
        
        # Validate related errors exist
        if definition.related_errors:
            for related_code in definition.related_errors:
                if related_code not in ERROR_CATALOG:
                    issues.append(f"Related error {related_code.value} not found in catalog for {error_code.value}")
    
    return issues


# Create commonly used error exceptions as shortcuts
class RedisConnectionError(GleitzeitError):
    def __init__(self, context: Optional[Dict] = None, cause: Optional[Exception] = None):
        super().__init__(ErrorCode.REDIS_CONNECTION_FAILED, context, cause)


class OllamaModelNotFoundError(GleitzeitError):
    def __init__(self, model_name: str, context: Optional[Dict] = None, cause: Optional[Exception] = None):
        ctx = context or {}
        ctx.update({"model_name": model_name})
        super().__init__(ErrorCode.OLLAMA_MODEL_NOT_FOUND, ctx, cause)


class WorkflowNotFoundError(GleitzeitError):
    def __init__(self, workflow_id: str, context: Optional[Dict] = None, cause: Optional[Exception] = None):
        ctx = context or {}
        ctx.update({"workflow_id": workflow_id})
        super().__init__(ErrorCode.WORKFLOW_NOT_FOUND, ctx, cause)


class AuthTokenExpiredError(GleitzeitError):
    def __init__(self, context: Optional[Dict] = None, cause: Optional[Exception] = None):
        super().__init__(ErrorCode.AUTH_TOKEN_EXPIRED, context, cause)


class FileNotFoundError(GleitzeitError):
    def __init__(self, file_path: str, context: Optional[Dict] = None, cause: Optional[Exception] = None):
        ctx = context or {}
        ctx.update({"file_path": file_path})
        super().__init__(ErrorCode.FILE_NOT_FOUND, ctx, cause)


# Export all error statistics
def get_error_statistics() -> Dict[str, Any]:
    """Get comprehensive statistics about the error catalog"""
    total_errors = len(ERROR_CATALOG)
    
    # Count by domain
    domain_counts = {}
    for domain in ErrorDomain:
        domain_counts[domain.value] = len(get_errors_by_domain(domain))
    
    # Count by severity
    severity_counts = {}
    for severity in ErrorSeverity:
        severity_counts[severity.value] = len(get_errors_by_severity(severity))
    
    # Count by category
    category_counts = {}
    for category in ErrorCategory:
        category_counts[category.value] = len(get_errors_by_category(category))
    
    # Count retryable errors
    retryable_errors = len([d for d in ERROR_CATALOG.values() if d.retry_after is not None])
    
    return {
        "total_errors": total_errors,
        "domains": domain_counts,
        "severities": severity_counts,
        "categories": category_counts,
        "retryable_errors": retryable_errors,
        "errors_with_documentation": len([d for d in ERROR_CATALOG.values() if d.documentation_url]),
        "errors_with_resolution_hints": len([d for d in ERROR_CATALOG.values() if d.resolution_hint]),
        "catalog_validation_issues": validate_error_catalog()
    }