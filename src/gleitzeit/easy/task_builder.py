"""
TaskBuilder - Fluent interface for building Gleitzeit tasks

Provides a chainable API for defining tasks with dependencies, parameters,
configuration, and event handlers.
"""

from typing import Dict, Any, List, Optional, Union
import re
from .errors import (
    TaskBuilderError,
    InvalidProtocolFormatError,
    InvalidDependencyError,
    InvalidEventTypeError,
    InvalidParameterError,
    InvalidConfigurationError,
    validate_protocol_format,
    validate_task_id
)

class EventHandler:
    """Handles inline event definitions that will be registered with the event bus."""
    
    def __init__(self, parent_task_builder: 'TaskBuilder', event_type: str, condition: Optional[str] = None):
        """
        Initialize event handler.

        Args:
            parent_task_builder: The TaskBuilder this handler belongs to
            event_type: Type of event ('error', 'success', 'failure', 'timeout', 'finally')
            condition: Optional condition for the event (e.g., error code)

        Raises:
            InvalidEventTypeError: If event type is not valid
        """
        valid_event_types = ['success', 'failure', 'error', 'timeout', 'finally']
        if event_type not in valid_event_types:
            raise InvalidEventTypeError(
                event_type,
                task_id=parent_task_builder.task_id,
                valid_types=valid_event_types
            )

        self.parent_task_builder = parent_task_builder
        self.parent_task_id = parent_task_builder.task_id
        self.event_type = event_type
        self.condition = condition
        self.actions: List[Dict[str, Any]] = []
        
    def run(self, task_id: str, protocol_method: str) -> 'EventHandler':
        """
        Add a task to execute when this event occurs.

        Args:
            task_id: ID for the new task
            protocol_method: Protocol and method in format "protocol/version:method"

        Returns:
            Self for chaining

        Raises:
            TaskBuilderError: If task_id is invalid
            InvalidProtocolFormatError: If protocol format is invalid
        """
        try:
            validate_task_id(task_id)
            protocol_version, method = validate_protocol_format(protocol_method, task_id)
        except Exception as e:
            # Add context about the event handler
            if hasattr(e, 'data'):
                e.data['event_type'] = self.event_type
                e.data['parent_task_id'] = self.parent_task_id
            raise

        action = {
            "task_id": task_id,
            "protocol_method": protocol_method,
            "params": {}
        }
        self.actions.append(action)
        return self
        
    def with_(self, **params) -> 'EventHandler':
        """
        Set parameters for the most recently added action.
        
        Args:
            **params: Parameters to pass to the task
            
        Returns:
            Self for chaining
        """
        if self.actions:
            self.actions[-1]["params"].update(params)
        return self
        
    def wait(self, seconds: Union[int, str]) -> 'EventHandler':
        """
        Add a wait before executing the next action.
        
        Args:
            seconds: Number of seconds to wait, or template string
            
        Returns:
            Self for chaining
        """
        action = {
            "task_id": f"{self.parent_task_id}_wait_{len(self.actions)}",
            "protocol_method": "timer/v1:wait",
            "params": {"duration": seconds}
        }
        self.actions.append(action)
        return self
        
    def retry_self(self) -> 'EventHandler':
        """
        Retry the parent task.
        
        Returns:
            Self for chaining
        """
        action = {
            "task_id": f"{self.parent_task_id}_retry_{len(self.actions)}",
            "protocol_method": "retry/v1:retry",
            "params": {"task_id": self.parent_task_id}
        }
        self.actions.append(action)
        return self
        
    def on_success(self) -> 'EventHandler':
        """Chain to define success handler on the parent task."""
        return self.parent_task_builder.on_success()
        
    def on_failure(self) -> 'EventHandler':
        """Chain to define failure handler on the parent task."""
        return self.parent_task_builder.on_failure()
        
    def on_error(self, error_code: Optional[str] = None) -> 'EventHandler':
        """Chain to define error handler on the parent task."""
        return self.parent_task_builder.on_error(error_code)
        
    def on_timeout(self) -> 'EventHandler':
        """Chain to define timeout handler on the parent task."""
        return self.parent_task_builder.on_timeout()
        
    def then(self) -> 'EventHandler':
        """Chain to define success handler on the parent task (promise-style)."""
        return self.parent_task_builder.then()
        
    def catch(self, error_code: Optional[str] = None) -> 'EventHandler':
        """Chain to define error handler on the parent task (promise-style)."""
        return self.parent_task_builder.catch(error_code)
        
    def finally_(self) -> 'EventHandler':
        """Chain to define finally handler on the parent task."""
        return self.parent_task_builder.finally_()
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "parent_task_id": self.parent_task_id,
            "event_type": self.event_type,
            "condition": self.condition,
            "actions": self.actions
        }


class TaskBuilder:
    """
    Fluent interface for building Gleitzeit tasks.
    
    Provides chainable methods to define task properties, dependencies,
    parameters, configuration, and event handlers.
    """
    
    def __init__(self, task_id: str, protocol_method: str):
        """
        Initialize TaskBuilder.

        Args:
            task_id: Unique identifier for the task
            protocol_method: Protocol and method in format "protocol/version:method"

        Raises:
            TaskBuilderError: If task_id is invalid
            InvalidProtocolFormatError: If protocol format is invalid
        """
        # Validate task ID
        validate_task_id(task_id)
        self.task_id = task_id
        self.protocol_method = protocol_method

        # Parse and validate protocol/method
        try:
            protocol_version, method = validate_protocol_format(protocol_method, task_id)
        except InvalidProtocolFormatError as e:
            # Enrich error with task context
            e.data['task_id'] = task_id
            raise

        # Build base task structure
        self.task_data = {
            "id": task_id,
            "protocol": protocol_version,
            "method": method,
            "params": {},
            "dependencies": [],
        }

        # Configuration
        self._retry_count = None
        self._timeout_seconds = None
        self._cache_ttl = None

        # Event handlers
        self.event_handlers: List[EventHandler] = []
        
    def needs(self, *dependencies: str) -> 'TaskBuilder':
        """
        Set task dependencies.
        
        Args:
            *dependencies: Task IDs this task depends on
            
        Returns:
            Self for chaining
        """
        self.task_data["dependencies"] = list(dependencies)
        return self
        
    def with_(self, **params) -> 'TaskBuilder':
        """
        Set task parameters.
        
        Args:
            **params: Parameters to pass to the task
            
        Returns:
            Self for chaining
        """
        self.task_data["params"].update(params)
        return self
        
    def retry(self, count: int) -> 'TaskBuilder':
        """
        Set retry count for the task.

        Args:
            count: Maximum number of retries

        Returns:
            Self for chaining

        Raises:
            InvalidConfigurationError: If count is invalid
        """
        if not isinstance(count, int):
            raise InvalidConfigurationError(
                self.task_id,
                "retry_count",
                count,
                f"Must be an integer, got {type(count).__name__}"
            )
        if count < 0:
            raise InvalidConfigurationError(
                self.task_id,
                "retry_count",
                count,
                "Must be non-negative"
            )
        if count > 100:
            raise InvalidConfigurationError(
                self.task_id,
                "retry_count",
                count,
                "Maximum retry count is 100"
            )
        self._retry_count = count
        return self

    def timeout(self, seconds: int) -> 'TaskBuilder':
        """
        Set timeout for the task.

        Args:
            seconds: Timeout in seconds

        Returns:
            Self for chaining

        Raises:
            InvalidConfigurationError: If seconds is invalid
        """
        if not isinstance(seconds, (int, float)):
            raise InvalidConfigurationError(
                self.task_id,
                "timeout_seconds",
                seconds,
                f"Must be a number, got {type(seconds).__name__}"
            )
        if seconds <= 0:
            raise InvalidConfigurationError(
                self.task_id,
                "timeout_seconds",
                seconds,
                "Must be positive"
            )
        if seconds > 3600:
            raise InvalidConfigurationError(
                self.task_id,
                "timeout_seconds",
                seconds,
                "Maximum timeout is 3600 seconds (1 hour)"
            )
        self._timeout_seconds = seconds
        return self

    def cache(self, ttl_seconds: int) -> 'TaskBuilder':
        """
        Enable result caching for the task.

        Args:
            ttl_seconds: Cache time-to-live in seconds

        Returns:
            Self for chaining

        Raises:
            InvalidConfigurationError: If ttl_seconds is invalid
        """
        if not isinstance(ttl_seconds, (int, float)):
            raise InvalidConfigurationError(
                self.task_id,
                "cache_ttl",
                ttl_seconds,
                f"Must be a number, got {type(ttl_seconds).__name__}"
            )
        if ttl_seconds <= 0:
            raise InvalidConfigurationError(
                self.task_id,
                "cache_ttl",
                ttl_seconds,
                "Must be positive"
            )
        if ttl_seconds > 86400:
            raise InvalidConfigurationError(
                self.task_id,
                "cache_ttl",
                ttl_seconds,
                "Maximum cache TTL is 86400 seconds (24 hours)"
            )
        self._cache_ttl = ttl_seconds
        return self
        
    def on_success(self) -> EventHandler:
        """
        Define actions to run when task succeeds.
        
        Returns:
            EventHandler for chaining success actions
        """
        handler = EventHandler(self, "success")
        self.event_handlers.append(handler)
        return handler
        
    def on_failure(self) -> EventHandler:
        """
        Define actions to run when task fails permanently (after all retries).
        
        Returns:
            EventHandler for chaining failure actions
        """
        handler = EventHandler(self, "failure")
        self.event_handlers.append(handler)
        return handler
        
    def on_error(self, error_code: Optional[str] = None) -> EventHandler:
        """
        Define actions to run when task encounters an error.
        
        Args:
            error_code: Optional specific error code to match
            
        Returns:
            EventHandler for chaining error actions
        """
        handler = EventHandler(self, "error", error_code)
        self.event_handlers.append(handler)
        return handler
        
    def on_timeout(self) -> EventHandler:
        """
        Define actions to run when task times out.
        
        Returns:
            EventHandler for chaining timeout actions
        """
        handler = EventHandler(self, "timeout")
        self.event_handlers.append(handler)
        return handler
        
    # Promise-style aliases
    def then(self) -> EventHandler:
        """Alias for on_success() - promise-style syntax."""
        return self.on_success()
        
    def catch(self, error_code: Optional[str] = None) -> EventHandler:
        """Alias for on_error() - promise-style syntax."""
        return self.on_error(error_code)
        
    def finally_(self) -> EventHandler:
        """
        Define actions that always run after task completion.
        Note: Uses finally_ to avoid Python keyword conflict.
        
        Returns:
            EventHandler for chaining final actions
        """
        handler = EventHandler(self, "finally")
        self.event_handlers.append(handler)
        return handler
        
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert TaskBuilder to dictionary format.

        Returns:
            Dictionary representation of the task
        """
        task_dict = self.task_data.copy()

        # Add configuration as top-level fields (not nested in config)
        if self._retry_count is not None:
            task_dict["retry_count"] = self._retry_count
        if self._timeout_seconds is not None:
            task_dict["timeout"] = self._timeout_seconds  # Use "timeout" not "timeout_seconds"
        if self._cache_ttl is not None:
            task_dict["cache_ttl"] = self._cache_ttl

        return task_dict
        
    def expand(self) -> List[Dict[str, Any]]:
        """
        Expand TaskBuilder into list of tasks and event registrations.
        
        In this initial version, we just return the main task.
        Future versions will expand inline conditions and other features.
        
        Returns:
            List containing the main task dictionary
        """
        return [self.to_dict()]
        
    def get_event_handlers(self) -> List[EventHandler]:
        """
        Get all event handlers for this task.
        
        Returns:
            List of EventHandler instances
        """
        return self.event_handlers.copy()
        
    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"TaskBuilder(id='{self.task_id}', protocol_method='{self.protocol_method}')"