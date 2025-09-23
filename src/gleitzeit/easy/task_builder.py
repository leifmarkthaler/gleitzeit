"""
TaskBuilder - Fluent interface for building Gleitzeit tasks.

Provides a chainable API for defining tasks with dependencies, parameters,
and configuration. Adapted for 0.0.7 workflow structure.
"""

from typing import Dict, Any, List, Optional, Union
from .errors import (
    TaskBuilderError,
    InvalidProtocolFormatError,
    InvalidParameterError,
    validate_task_id,
    validate_protocol_format
)
from .protocol_registry import get_registry


class TaskBuilder:
    """
    Fluent builder for creating tasks with chainable configuration.

    Adapted for 0.0.7's workflow structure where tasks have:
    - name (instead of task_id)
    - protocol
    - method
    - params (instead of parameters)
    - dependencies
    """

    def __init__(self, task_id: str, protocol_method: str = "python/v1:execute"):
        """
        Initialize a new task builder.

        Args:
            task_id: Unique task identifier (becomes the task name)
            protocol_method: Protocol and method in format "protocol/version:method"
        """
        validate_task_id(task_id)

        # Use protocol registry to parse and validate
        registry = get_registry()
        protocol, method = registry.parse_protocol_method(protocol_method)

        if not protocol or not method:
            # Fallback to old validation for backward compatibility
            protocol_version, method_name = validate_protocol_format(protocol_method, task_id)

            # Fix up for known protocols
            if protocol_version == "python":
                protocol = "python/v1"
                method = f"python/{method_name}"
            elif protocol_version == "ollama":
                protocol = "ollama/v1"
                method = f"ollama/{method_name}"
            else:
                protocol = protocol_version
                method = method_name if "/" in method_name else f"{protocol_version.split('/')[0]}/{method_name}"

        self.task_id = task_id  # Internal ID
        self.name = task_id  # Task name in workflow
        self.protocol = protocol  # Full protocol with version
        self.full_method = method  # Full method name

        # Extract version from protocol
        if '/' in protocol:
            self.version = protocol.split('/', 1)[1]
        else:
            self.version = "v1"

        self.parameters: Dict[str, Any] = {}
        self.dependencies: List[str] = []
        self.config: Dict[str, Any] = {}

        # Retry and timeout configuration
        self._retry_count: Optional[int] = None
        self._timeout: Optional[int] = None

    def with_(self, **params) -> 'TaskBuilder':
        """
        Set task parameters.

        For Python tasks, common parameters are:
        - code: Python code to execute
        - file: Python file to execute
        - capture_output: Whether to capture output

        Args:
            **params: Parameters to pass to the task

        Returns:
            Self for chaining
        """
        self.parameters.update(params)
        return self

    def needs(self, *dependencies: str) -> 'TaskBuilder':
        """
        Add task dependencies.

        Args:
            *dependencies: Task IDs this task depends on

        Returns:
            Self for chaining
        """
        for dep in dependencies:
            if dep and dep not in self.dependencies:
                self.dependencies.append(dep)
        return self

    def depends_on(self, *dependencies: str) -> 'TaskBuilder':
        """
        Alias for needs().

        Args:
            *dependencies: Task IDs this task depends on

        Returns:
            Self for chaining
        """
        return self.needs(*dependencies)

    def retry(self, count: int) -> 'TaskBuilder':
        """
        Set retry count for the task.

        Args:
            count: Number of retries (0 to disable)

        Returns:
            Self for chaining
        """
        if count < 0:
            raise InvalidParameterError("retry", count, self.task_id, "Retry count must be >= 0")
        self._retry_count = count
        self.config['retry_count'] = count
        return self

    def timeout(self, seconds: int) -> 'TaskBuilder':
        """
        Set task timeout in seconds.

        Args:
            seconds: Timeout in seconds

        Returns:
            Self for chaining
        """
        if seconds <= 0:
            raise InvalidParameterError("timeout", seconds, self.task_id, "Timeout must be > 0")
        self._timeout = seconds
        self.config['timeout'] = seconds
        return self

    def cache(self, ttl: int) -> 'TaskBuilder':
        """
        Cache task results for specified seconds.

        Args:
            ttl: Time to live in seconds

        Returns:
            Self for chaining
        """
        if ttl <= 0:
            raise InvalidParameterError("cache", ttl, self.task_id, "Cache TTL must be > 0")
        self.config['cache_ttl'] = ttl
        return self

    def priority(self, level: int) -> 'TaskBuilder':
        """
        Set task priority (higher = more important).

        Args:
            level: Priority level (1-100)

        Returns:
            Self for chaining
        """
        if not 1 <= level <= 100:
            raise InvalidParameterError("priority", level, self.task_id, "Priority must be 1-100")
        self.config['priority'] = level
        return self

    def env(self, **env_vars) -> 'TaskBuilder':
        """
        Set environment variables for task execution.

        Args:
            **env_vars: Environment variables

        Returns:
            Self for chaining
        """
        if 'env' not in self.config:
            self.config['env'] = {}
        self.config['env'].update(env_vars)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to 0.0.7 task dictionary format.

        Returns:
            Task dictionary for workflow
        """
        task = {
            "name": self.name,
            "protocol": self.protocol,
            "method": self.full_method,
            "params": self.parameters.copy()
        }

        # Add dependencies if any
        if self.dependencies:
            task["dependencies"] = self.dependencies.copy()

        # Add retry/timeout to params for 0.0.7
        if self._retry_count is not None:
            task["params"]["retry_count"] = self._retry_count

        if self._timeout is not None:
            task["params"]["timeout"] = self._timeout

        # Add any additional config to params
        for key, value in self.config.items():
            if key not in ['retry_count', 'timeout']:
                task["params"][key] = value

        return task

    def __repr__(self) -> str:
        """String representation of the task."""
        deps = f", depends_on={self.dependencies}" if self.dependencies else ""
        return f"TaskBuilder('{self.task_id}', '{self.protocol}/{self.version}:{self.method}'{deps})"

    # Convenience methods for common patterns

    def with_code(self, code: str) -> 'TaskBuilder':
        """
        Set Python code for execution (convenience for Python tasks).

        Args:
            code: Python code to execute

        Returns:
            Self for chaining
        """
        return self.with_(code=code)

    def with_file(self, file_path: str) -> 'TaskBuilder':
        """
        Set Python file for execution (convenience for Python tasks).

        Args:
            file_path: Path to Python file

        Returns:
            Self for chaining
        """
        return self.with_(file=file_path)

    def capture_output(self, capture: bool = True) -> 'TaskBuilder':
        """
        Whether to capture task output.

        Args:
            capture: Whether to capture output

        Returns:
            Self for chaining
        """
        return self.with_(capture_output=capture)

    def parallel_with(self, *task_ids: str) -> 'TaskBuilder':
        """
        Run in parallel with specified tasks (no dependencies between them).

        This is a semantic helper - it doesn't add dependencies but helps
        document that these tasks should run in parallel.

        Args:
            *task_ids: Tasks to run in parallel with

        Returns:
            Self for chaining
        """
        # Just for documentation, doesn't affect the task structure
        if 'parallel_with' not in self.config:
            self.config['parallel_with'] = []
        self.config['parallel_with'].extend(task_ids)
        return self