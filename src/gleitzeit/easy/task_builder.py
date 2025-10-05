"""
TaskBuilder - Fluent interface for building Gleitzeit tasks.

Provides a chainable API for defining tasks with dependencies, parameters,
and configuration. Adapted for 0.0.7 workflow structure.
"""

from typing import Dict, Any, List, Optional, Union, Type, Tuple
import re
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

        # Validation rules (runtime validation framework)
        self._required_params: set = set()
        self._type_specs: Dict[str, Tuple[Type, ...]] = {}
        self._range_specs: Dict[str, Tuple[Any, Any]] = {}
        self._auto_validate: bool = False

        # Track if .input() was used (for code injection)
        self._uses_input: bool = False
        self._input_vars: List[str] = []

    def with_(self, **params) -> 'TaskBuilder':
        """
        Set task parameters.

        For Python tasks, common parameters are:
        - code: Python code to execute
        - file: Python file to execute
        - capture_output: Whether to capture output

        Auto-injection for .input():
        If you used .input() before calling .with_(), this method automatically injects
        code that extracts task results from the 'inputs' dict and creates variables.
        The injected code finds result dicts in 'inputs' and assigns them to variables
        named after the tasks.

        Example:
            gen = t("generate", ...).with_(code="result = {'number': 42}")
            proc = t("process", ...).input(gen).with_(code='''
                # 'generate' variable is automatically available here!
                print(generate['number'])  # Prints: 42
            ''')

        Args:
            **params: Parameters to pass to the task

        Returns:
            Self for chaining
        """
        # If .input() was used and code parameter is present, inject parsing helper
        if self._uses_input and 'code' in params and self.protocol.startswith('python/'):
            user_code = params['code']

            # Generate helper code to extract results from inputs
            # The dependency worker injects results into inputs dict with UUID keys
            # We need to find those results and assign them to the user's task name variables
            helper_lines = [
                "# Auto-injected by Easy Client .input() method",
                "# The dependency worker injects task results into 'inputs' dict",
                "# Extract results and assign to task name variables",
            ]

            # For each task name, find the corresponding result in inputs
            # Since inputs contains both UUID keys (with results) and potentially
            # other keys (from user params), we look for dict values that look like results
            for var_name in self._input_vars:
                helper_lines.extend([
                    f"# Find result for task '{var_name}'",
                    f"{var_name} = None",
                    f"if 'inputs' in dir() and isinstance(inputs, dict):",
                    f"    # Look for result dict in inputs (dependency worker injects with UUID key)",
                    f"    for key, value in inputs.items():",
                    f"        if isinstance(value, dict) and ('_stdout' in value or 'result' in str(type(value))):",
                    f"            {var_name} = value",
                    f"            break",
                    f"if {var_name} is None:",
                    f"    {var_name} = {{}}  # Default to empty dict if not found",
                    "",
                ])

            helper_lines.append("")  # Blank line before user code

            # Prepend helper to user code
            params['code'] = '\n'.join(helper_lines) + '\n' + user_code

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

    def input(self, *tasks: Union[str, 'TaskBuilder']) -> 'TaskBuilder':
        """
        Add input parameters that reference results from other tasks.

        This method enables result chaining by automatically:
        1. Adding the specified tasks as dependencies
        2. Creating variables in your code named after each task
        3. Populating those variables with the task results

        How it works:
        - Gleitzeit's dependency worker automatically injects task results into an 'inputs' dict
        - The .input() method injects code that extracts these results into named variables
        - Variables are named after the task (e.g., task "generate" becomes variable "generate")
        - Each variable contains the full result dict from that task

        Examples:
            # Simple chaining (recommended - type-safe)
            gen = t("generate", "python/v1:execute").with_(code='''
                result = {'number': 42, 'message': 'Hello'}
            ''')

            proc = t("process", "python/v1:execute").input(gen).with_(code='''
                # 'generate' variable is automatically available!
                doubled = generate['number'] * 2
                result = {'doubled': doubled, 'msg': generate['message']}
            ''')

            workflow = w(gen).sequential(proc).name("chain_example")

            # Multiple inputs
            t1 = t("task1", "python/v1:execute").with_(code="result = {'a': 1}")
            t2 = t("task2", "python/v1:execute").with_(code="result = {'b': 2}")
            agg = t("aggregate", "python/v1:execute").input(t1, t2).with_(code='''
                # Both task1 and task2 variables are available
                result = {'sum': task1['a'] + task2['b']}
            ''')

            # Reference by string name (not recommended - no type safety)
            t("process").input("generate").with_(code="...")

        Args:
            *tasks: TaskBuilder objects (recommended) or task name strings

        Returns:
            Self for chaining
        """
        # Get or create inputs parameter
        if 'inputs' not in self.parameters:
            self.parameters['inputs'] = {}

        for task in tasks:
            # Get task name from TaskBuilder or use string directly
            if isinstance(task, TaskBuilder):
                task_name = task.task_id
            else:
                task_name = task

            # Don't add ${task.result} expressions - the dependency worker
            # automatically injects results into inputs using task IDs

            # Add as dependency if not already present
            if task_name not in self.dependencies:
                self.dependencies.append(task_name)

            # Track task name for code injection
            if task_name not in self._input_vars:
                self._input_vars.append(task_name)

        self._uses_input = True
        return self

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

        If auto_validate is enabled, validation is performed before conversion.

        Returns:
            Task dictionary for workflow

        Raises:
            TaskBuilderError: If auto-validation is enabled and validation fails
        """
        # Auto-validate if enabled
        if self._auto_validate:
            self.validate()

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

    # Runtime Validation Framework

    def _is_dynamic_expression(self, value: Any) -> bool:
        """
        Check if a parameter value is a dynamic expression.

        Dynamic expressions start with ${...} and are resolved at runtime.
        These should be skipped during validation.

        Args:
            value: Parameter value to check

        Returns:
            True if value is a dynamic expression
        """
        if isinstance(value, str):
            return value.strip().startswith('${')
        return False

    def require(self, *param_names: str) -> 'TaskBuilder':
        """
        Mark parameters as required.

        Required parameters will be validated when .validate() is called.
        Dynamic expressions like "${task1.output}" are allowed.

        Example:
            task = t("analyze", "ollama/v1:generate")
                .require('prompt', 'model')
                .with_(prompt="Analyze this", model="llama2")
                .validate()

        Args:
            *param_names: Names of required parameters

        Returns:
            Self for chaining

        Raises:
            TaskBuilderError: If validation is called and required params are missing
        """
        self._required_params.update(param_names)
        return self

    def expect_types(self, **type_specs) -> 'TaskBuilder':
        """
        Specify expected types for parameters.

        Type checking is performed at validation time.
        Dynamic expressions are skipped during type checking.

        Example:
            task = t("process", "python/v1:execute")
                .expect_types(
                    temperature=(int, float),
                    max_tokens=int,
                    enabled=bool
                )
                .with_(temperature=0.7, max_tokens=1000, enabled=True)
                .validate()

        Args:
            **type_specs: Parameter name -> type(s) mapping
                         Can be single type or tuple of types

        Returns:
            Self for chaining

        Raises:
            TaskBuilderError: If validation is called and types don't match
        """
        for param_name, expected_type in type_specs.items():
            # Normalize to tuple of types
            if not isinstance(expected_type, tuple):
                expected_type = (expected_type,)
            self._type_specs[param_name] = expected_type
        return self

    def expect_range(self, param_name: str, min_val: Any, max_val: Any) -> 'TaskBuilder':
        """
        Specify expected range for a numeric parameter.

        Range checking is performed at validation time.
        Dynamic expressions are skipped during range checking.

        Example:
            task = t("analyze", "ollama/v1:generate")
                .expect_range('temperature', 0, 2)
                .expect_range('max_tokens', 1, 10000)
                .with_(temperature=0.7, max_tokens=1000)
                .validate()

        Args:
            param_name: Name of parameter
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)

        Returns:
            Self for chaining

        Raises:
            TaskBuilderError: If validation is called and value is out of range
        """
        self._range_specs[param_name] = (min_val, max_val)
        return self

    def validate(self) -> 'TaskBuilder':
        """
        Validate task parameters against specified rules.

        Checks:
        - Required parameters are present
        - Parameter types match expected types
        - Numeric parameters are within expected ranges

        Dynamic expressions (starting with ${) are skipped during validation
        as they will be resolved at runtime.

        Example:
            task = t("analyze", "ollama/v1:generate")
                .require('prompt')
                .expect_types(temperature=(int, float))
                .expect_range('temperature', 0, 2)
                .with_(prompt="Analyze this", temperature=0.7)
                .validate()  # Raises TaskBuilderError if invalid

        Returns:
            Self for chaining

        Raises:
            TaskBuilderError: If validation fails with details
        """
        errors = []

        # Check required parameters
        for param_name in self._required_params:
            if param_name not in self.parameters:
                errors.append(f"Missing required parameter: '{param_name}'")

        # Check types
        for param_name, expected_types in self._type_specs.items():
            if param_name in self.parameters:
                value = self.parameters[param_name]
                # Skip dynamic expressions
                if self._is_dynamic_expression(value):
                    continue
                if not isinstance(value, expected_types):
                    type_names = ' or '.join(t.__name__ for t in expected_types)
                    actual_type = type(value).__name__
                    errors.append(
                        f"Parameter '{param_name}' has incorrect type: "
                        f"expected {type_names}, got {actual_type}"
                    )

        # Check ranges
        for param_name, (min_val, max_val) in self._range_specs.items():
            if param_name in self.parameters:
                value = self.parameters[param_name]
                # Skip dynamic expressions
                if self._is_dynamic_expression(value):
                    continue
                try:
                    if not (min_val <= value <= max_val):
                        errors.append(
                            f"Parameter '{param_name}' out of range: "
                            f"expected {min_val}-{max_val}, got {value}"
                        )
                except TypeError:
                    errors.append(
                        f"Parameter '{param_name}' is not comparable for range checking"
                    )

        # Raise error if any validation failed
        if errors:
            error_msg = f"Task '{self.task_id}' validation failed:\n"
            error_msg += "\n".join(f"  - {err}" for err in errors)
            raise TaskBuilderError(error_msg)

        return self

    def auto_validate(self, enabled: bool = True) -> 'TaskBuilder':
        """
        Enable automatic validation when building workflow.

        When enabled, validate() is called automatically in to_dict().

        Example:
            task = t("analyze", "ollama/v1:generate")
                .require('prompt')
                .auto_validate()  # Will validate when added to workflow
                .with_(prompt="Analyze this")

        Args:
            enabled: Whether to enable auto-validation

        Returns:
            Self for chaining
        """
        self._auto_validate = enabled
        return self