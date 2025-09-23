"""
Base handler interface for Gleitzeit task execution.

Handlers are lightweight, stateless executors that replace the complex provider system.
They work directly with Task objects and return TaskResult objects.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging
import uuid
import platform
import os
from datetime import datetime

from ..core.models import Task, TaskResult, TaskStatus
from ..core.errors import GleitzeitError, ErrorCode

logger = logging.getLogger(__name__)


class BaseHandler(ABC):
    """
    Base handler interface - works with Task objects.

    Handlers are stateless executors that:
    - Validate task parameters
    - Execute tasks
    - Return TaskResult with appropriate status

    They do NOT:
    - Handle dependencies (DependencyWorker does this)
    - Manage state (all state is in Redis)
    - Know about workflows or other tasks
    """

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize handler with optional configuration.

        Args:
            config: Handler-specific configuration
        """
        self.config = config or {}

        # Generate unique handler ID
        self.handler_id = str(uuid.uuid4())
        self.created_at = datetime.utcnow()

        # Capture handler metadata
        self.metadata = self._capture_metadata()

        # Initialize metrics
        self._init_metrics()

        logger.info(f"Handler {self.__class__.__name__} initialized with ID: {self.handler_id}")

    def _capture_metadata(self) -> Dict[str, Any]:
        """
        Capture handler metadata including system information.

        Returns:
            Dictionary containing handler and system metadata
        """
        try:
            import psutil
            cpu_count = psutil.cpu_count()
            memory_info = psutil.virtual_memory()
            memory_total_gb = memory_info.total / (1024**3)
            memory_available_gb = memory_info.available / (1024**3)
        except ImportError:
            # psutil not available, use basic info
            cpu_count = os.cpu_count()
            memory_total_gb = None
            memory_available_gb = None

        metadata = {
            # Handler info
            'handler_class': self.__class__.__name__,
            'handler_protocol': self.get_capabilities().get('protocol', 'unknown'),
            'handler_version': getattr(self, '__version__', '1.0.0'),

            # Process info
            'process_id': os.getpid(),
            'python_version': platform.python_version(),

            # System info
            'hostname': platform.node(),
            'os_name': platform.system(),
            'os_version': platform.release(),
            'cpu_count': cpu_count,
            'memory_total_gb': memory_total_gb,
            'memory_available_gb': memory_available_gb,

            # Configuration hash (for tracking config changes)
            'config_hash': str(hash(frozenset(self.config.items()))) if self.config else None,
        }

        return metadata

    def _init_metrics(self):
        """Initialize metrics tracking"""
        try:
            from .metrics import HandlerMetrics
            self.metrics = HandlerMetrics(self.__class__.__name__)
        except ImportError:
            # Metrics are optional
            self.metrics = None

    @classmethod
    @abstractmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """
        Return handler capabilities for discovery and validation.

        Returns:
            Dict with:
                - protocol: str - Protocol identifier (e.g., 'python/v1')
                - task_types: List[str] - Task types for backward compatibility
                - methods: Dict[str, Dict] - Supported methods with params

        Example:
            {
                'protocol': 'python/v1',
                'task_types': ['python', 'script'],
                'methods': {
                    'python/execute': {
                        'description': 'Execute Python code',
                        'required': ['code'],
                        'optional': ['inputs', 'timeout']
                    }
                }
            }
        """
        pass

    @abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        """
        Execute task and return result.

        Args:
            task: Task object with protocol, method, params

        Returns:
            TaskResult with status and result/error

        Raises:
            GleitzeitError: For execution errors with appropriate ErrorCode
        """
        pass

    async def validate(self, task: Task) -> None:
        """
        Validate task can be executed.

        Default implementation checks if method is supported.
        Override for custom validation logic.

        Args:
            task: Task to validate

        Raises:
            GleitzeitError: If task is invalid
        """
        caps = self.get_capabilities()

        # Check protocol matches (if specified)
        if task.protocol and task.protocol != caps['protocol']:
            raise GleitzeitError(
                f"Protocol mismatch: task requires {task.protocol}, "
                f"handler provides {caps['protocol']}",
                code=ErrorCode.PROTOCOL_VERSION_MISMATCH,
                data={'task_id': task.id, 'expected': task.protocol, 'actual': caps['protocol']}
            )

        # Check method is supported
        if task.method not in caps.get('methods', {}):
            available_methods = list(caps.get('methods', {}).keys())
            raise GleitzeitError(
                f"Method '{task.method}' not supported by {caps['protocol']}",
                code=ErrorCode.METHOD_NOT_SUPPORTED,
                data={
                    'task_id': task.id,
                    'method': task.method,
                    'protocol': caps['protocol'],
                    'available_methods': available_methods
                }
            )

        # Check required parameters
        method_spec = caps['methods'][task.method]
        for required_param in method_spec.get('required', []):
            if required_param not in task.params:
                raise GleitzeitError(
                    f"Missing required parameter '{required_param}' for {task.method}",
                    code=ErrorCode.INVALID_PARAMS,
                    data={
                        'task_id': task.id,
                        'method': task.method,
                        'missing_param': required_param,
                        'provided_params': list(task.params.keys())
                    }
                )

    async def cleanup(self):
        """
        Cleanup handler resources.

        Called when handler is being destroyed.
        Override for custom cleanup logic.
        """
        if self.metrics:
            await self.metrics.flush()

    def create_result(
        self,
        task: Task,
        status: TaskStatus,
        result: Any = None,
        error: str = None,
        **kwargs
    ) -> TaskResult:
        """
        Create a TaskResult with handler tracking information.

        Args:
            task: The task being executed
            status: Task execution status
            result: Task result data (if successful)
            error: Error message (if failed)
            **kwargs: Additional fields for TaskResult

        Returns:
            TaskResult with handler tracking information
        """
        # Get provider URL (backend service like Ollama)
        provider_url = None
        if hasattr(self, 'base_url'):
            provider_url = self.base_url
        elif hasattr(self, 'connection_string'):
            # Hide sensitive info but keep host
            provider_url = self.connection_string.split('@')[-1] if '@' in self.connection_string else 'local'

        # Get worker instance URL (where this handler/worker is running)
        worker_instance_url = None
        if self.config.get('instance_url'):
            worker_instance_url = self.config.get('instance_url')
        elif self.config.get('hostname'):
            # Build from hostname and port if available
            hostname = self.config.get('hostname')
            port = self.config.get('port', '')
            worker_instance_url = f"{hostname}:{port}" if port else hostname

        return TaskResult(
            task_id=task.id,
            workflow_id=task.workflow_id,
            status=status,
            result=result,
            error=error,
            handler_id=self.handler_id,
            worker_id=self.config.get('worker_id'),  # Will be set by worker
            provider_url=provider_url,
            worker_instance_url=worker_instance_url,
            **kwargs
        )

    def get_handler_info(self) -> Dict[str, Any]:
        """
        Get handler identification and metadata.

        Returns:
            Dictionary with handler ID, metadata, and configuration
        """
        return {
            'handler_id': self.handler_id,
            'handler_class': self.__class__.__name__,
            'protocol': self.get_capabilities().get('protocol', 'unknown'),
            'created_at': self.created_at.isoformat(),
            'metadata': self.metadata,
            'config': {k: v for k, v in self.config.items() if not k.endswith('_secret')}  # Exclude secrets
        }

    def __repr__(self) -> str:
        """String representation"""
        caps = self.get_capabilities()
        return f"{self.__class__.__name__}(protocol={caps.get('protocol', 'unknown')}, id={self.handler_id[:8]})"