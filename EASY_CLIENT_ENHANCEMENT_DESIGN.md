# Easy Client Enhancement Design Document

**Version**: 1.0
**Date**: 2025-09-30
**Status**: Design Review
**Author**: Architecture Review

---

## Executive Summary

This document proposes practical enhancements to Gleitzeit's Easy Client API that respect the system's core architectural principles while addressing real user pain points. Unlike previous proposals that attempted to introduce static typing (incompatible with dynamic parameter resolution), this design focuses on runtime validation, self-documentation, and workflow pattern helpers.

### Goals

1. **Runtime Validation**: Catch parameter errors before submission
2. **Self-Documentation**: Make handler capabilities discoverable
3. **Workflow Patterns**: Reduce boilerplate for common DAG patterns
4. **Better DX**: Improve error messages and discoverability

### Non-Goals

- ❌ Static type checking (breaks dynamic resolution)
- ❌ Handler-specific factory methods (reduces flexibility)
- ❌ Map-reduce templates (wrong execution model)
- ❌ Breaking changes to existing API

---

## Architecture Principles (Must Preserve)

### 1. Dynamic Parameter Resolution

Gleitzeit's runtime parameter resolution allows task parameters to reference other task outputs:

```python
task2 = t("process", "python/v1:execute").with_(
    input="${task1.result.data}",  # ← Resolved at runtime
    config="${workflow.config.threshold}"
)
```

**Design Constraint**: Any validation must support string expressions that start with `${}`.

### 2. Handler Flexibility

Handlers are registered dynamically and can accept arbitrary parameters:

```python
class BaseHandler(ABC):
    @abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        # task.params is Dict[str, Any] - intentionally flexible
        pass
```

**Design Constraint**: No fixed schemas. Handlers self-describe their parameters.

### 3. Protocol Agnostic

Easy Client works with any protocol, including user-defined handlers:

```python
# Should work with ALL of these
t("task", "python/v1:execute")
t("task", "ollama/v1:generate")
t("task", "custom_company/v2:special_method")
```

**Design Constraint**: No hardcoding of specific protocols.

### 4. Stateless

All state lives in Redis. Easy Client is just a builder that produces workflow dictionaries.

**Design Constraint**: No local state management.

---

## Enhancement 1: Runtime Validation Framework

### Problem Statement

Users have no way to validate task parameters before submission, leading to runtime errors when workflows execute.

**Current Experience**:
```python
task = t("analyze", "ollama/v1:generate").with_(
    promt="Analyze this"  # ← Typo! Only discovered at runtime
)
workflow.submit()  # ← Fails minutes later when task executes
```

### Design: Validation Chain

Add optional validation methods to `TaskBuilder` that check parameters before workflow submission.

#### API Design

```python
class TaskBuilder:
    def require(self, *param_names: str) -> 'TaskBuilder':
        """
        Mark parameters as required.

        Args:
            *param_names: Parameter names that must be provided

        Returns:
            Self for chaining
        """
        if not hasattr(self, '_required_params'):
            self._required_params = set()
        self._required_params.update(param_names)
        return self

    def expect_types(self, **type_specs) -> 'TaskBuilder':
        """
        Specify expected types for parameters (for validation).

        Args:
            **type_specs: param_name -> type or tuple of types

        Example:
            .expect_types(temperature=(int, float), prompt=str)

        Returns:
            Self for chaining
        """
        if not hasattr(self, '_type_specs'):
            self._type_specs = {}
        self._type_specs.update(type_specs)
        return self

    def expect_range(self, param_name: str, min_val=None, max_val=None) -> 'TaskBuilder':
        """
        Specify valid range for numeric parameter.

        Args:
            param_name: Parameter name
            min_val: Minimum value (inclusive)
            max_val: Maximum value (inclusive)

        Returns:
            Self for chaining
        """
        if not hasattr(self, '_range_specs'):
            self._range_specs = {}
        self._range_specs[param_name] = (min_val, max_val)
        return self

    def validate(self) -> 'TaskBuilder':
        """
        Validate parameters against specifications.

        Raises:
            InvalidParameterError: If validation fails

        Returns:
            Self for chaining
        """
        # Check required parameters
        if hasattr(self, '_required_params'):
            missing = self._required_params - set(self.parameters.keys())
            if missing:
                raise InvalidParameterError(
                    "validation",
                    missing,
                    self.task_id,
                    f"Missing required parameters: {', '.join(missing)}"
                )

        # Check types (skip dynamic resolution expressions)
        if hasattr(self, '_type_specs'):
            for param, expected_type in self._type_specs.items():
                if param in self.parameters:
                    value = self.parameters[param]
                    # Skip validation for dynamic expressions
                    if isinstance(value, str) and value.startswith('${'):
                        continue
                    if not isinstance(value, expected_type):
                        raise InvalidParameterError(
                            param,
                            value,
                            self.task_id,
                            f"Expected {expected_type}, got {type(value)}"
                        )

        # Check ranges (skip dynamic expressions)
        if hasattr(self, '_range_specs'):
            for param, (min_val, max_val) in self._range_specs.items():
                if param in self.parameters:
                    value = self.parameters[param]
                    # Skip validation for dynamic expressions
                    if isinstance(value, str) and value.startswith('${'):
                        continue
                    if min_val is not None and value < min_val:
                        raise InvalidParameterError(
                            param, value, self.task_id,
                            f"Value {value} below minimum {min_val}"
                        )
                    if max_val is not None and value > max_val:
                        raise InvalidParameterError(
                            param, value, self.task_id,
                            f"Value {value} above maximum {max_val}"
                        )

        return self
```

#### Usage Examples

```python
# Example 1: Simple required parameters
task = t("analyze", "ollama/v1:generate")
    .require('prompt')
    .with_(prompt="Analyze this text")
    .validate()  # ← Passes

# Example 2: Type and range validation
task = t("analyze", "ollama/v1:generate")
    .require('prompt')
    .expect_types(temperature=(int, float), prompt=str)
    .expect_range('temperature', 0, 2)
    .with_(prompt="Analyze", temperature=0.7)
    .validate()  # ← Passes

# Example 3: Dynamic resolution (validation skipped)
task = t("process", "python/v1:execute")
    .require('input')
    .with_(input="${task1.result}")  # ← Validation skipped for ${...}
    .validate()  # ← Passes (dynamic expressions allowed)

# Example 4: Validation failure
task = t("analyze", "ollama/v1:generate")
    .require('prompt')
    .with_(model="llama2")  # ← Missing 'prompt'
    .validate()  # ← Raises InvalidParameterError
```

#### Workflow-Level Validation

```python
class WorkflowBuilder:
    def validate_all(self) -> 'WorkflowBuilder':
        """
        Validate all tasks in the workflow.

        Returns:
            Self for chaining

        Raises:
            WorkflowBuilderError: If any task validation fails
        """
        errors = []

        for task in self.tasks:
            try:
                task.validate()
            except InvalidParameterError as e:
                errors.append(f"Task '{task.task_id}': {e}")

        if errors:
            raise WorkflowBuilderError(
                f"Workflow validation failed:\n" + "\n".join(errors)
            )

        return self

# Usage
workflow = w(
    t("fetch", "http/v1:request").require('url').with_(url="..."),
    t("process", "python/v1:execute").require('code').with_(code="...")
).validate_all()  # ← Validates all tasks
```

### Implementation Details

**Files to Modify**:
- `src/gleitzeit/easy/task_builder.py`: Add validation methods
- `src/gleitzeit/easy/workflow_builder.py`: Add `validate_all()`
- `src/gleitzeit/easy/errors.py`: Enhance error messages

**Backward Compatibility**: ✅ 100% compatible - validation is opt-in

**Performance Impact**: Negligible (~0.001ms per task)

---

## Enhancement 2: Handler Self-Documentation

### Problem Statement

Users don't know what parameters a handler accepts without reading documentation or source code.

**Current Experience**:
```python
# What parameters does ollama/v1:generate accept?
# User has to guess or read docs
task = t("analyze", "ollama/v1:generate").with_(
    prompt="...",  # Is this required?
    model="...",   # What models are available?
    temperature=0.7  # What's the valid range?
)
```

### Design: Handler Parameter Schema

Handlers self-describe their parameters via a new `get_param_schema()` method.

#### API Design

```python
# Add to BaseHandler
class BaseHandler(ABC):
    def get_param_schema(self) -> Dict[str, Any]:
        """
        Return parameter schema for this handler.

        Returns:
            {
                'protocol': 'python/v1',
                'methods': {
                    'execute': {
                        'required': ['code'],
                        'optional': {
                            'env': {
                                'type': 'dict',
                                'default': {},
                                'description': 'Environment variables'
                            },
                            'timeout': {
                                'type': 'int',
                                'default': 300,
                                'description': 'Execution timeout in seconds'
                            }
                        },
                        'examples': [
                            {'code': 'print("hello")'},
                            {'code': 'import sys; print(sys.version)', 'env': {'DEBUG': '1'}}
                        ]
                    }
                }
            }
        """
        return {
            'protocol': self.get_capabilities().get('protocol', 'unknown'),
            'methods': {}
        }
```

#### Implementation in Handlers

```python
# src/gleitzeit/handlers/ollama.py
class OllamaHandler(BaseHandler):
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            'protocol': 'ollama/v1',
            'methods': {
                'generate': {
                    'required': ['prompt'],
                    'optional': {
                        'model': {
                            'type': 'str',
                            'default': 'llama2',
                            'description': 'Model name to use for generation',
                            'examples': ['llama2', 'mistral', 'codellama']
                        },
                        'temperature': {
                            'type': 'float',
                            'default': 0.7,
                            'description': 'Sampling temperature',
                            'range': [0, 2]
                        },
                        'max_tokens': {
                            'type': 'int',
                            'default': 1000,
                            'description': 'Maximum tokens to generate',
                            'range': [1, 4096]
                        },
                        'system': {
                            'type': 'str',
                            'default': None,
                            'description': 'System prompt for the model'
                        }
                    },
                    'examples': [
                        {
                            'prompt': 'Explain quantum computing',
                            'model': 'llama2',
                            'temperature': 0.7
                        },
                        {
                            'prompt': 'Write a function to sort a list',
                            'model': 'codellama',
                            'temperature': 0.3
                        }
                    ]
                },
                'embed': {
                    'required': ['text'],
                    'optional': {
                        'model': {
                            'type': 'str',
                            'default': 'llama2',
                            'description': 'Model to use for embeddings'
                        }
                    }
                }
            }
        }

# src/gleitzeit/handlers/python.py
class PythonHandler(BaseHandler):
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            'protocol': 'python/v1',
            'methods': {
                'execute': {
                    'required': [],  # Either 'code' or 'file' required (checked at runtime)
                    'optional': {
                        'code': {
                            'type': 'str',
                            'default': None,
                            'description': 'Python code to execute'
                        },
                        'file': {
                            'type': 'str',
                            'default': None,
                            'description': 'Path to Python file to execute'
                        },
                        'env': {
                            'type': 'dict',
                            'default': {},
                            'description': 'Environment variables'
                        },
                        'timeout': {
                            'type': 'int',
                            'default': 300,
                            'description': 'Execution timeout in seconds'
                        },
                        'capture_output': {
                            'type': 'bool',
                            'default': True,
                            'description': 'Whether to capture stdout/stderr'
                        }
                    },
                    'examples': [
                        {'code': 'print("hello world")'},
                        {'file': '/path/to/script.py', 'env': {'DEBUG': '1'}},
                        {'code': 'import sys; sys.exit(0)', 'capture_output': False}
                    ]
                }
            }
        }
```

#### CLI Integration

Add new CLI command to display handler documentation:

```python
# src/gleitzeit/cli/main.py
@cli.command('docs')
@click.argument('protocol_method', required=False)
@click.option('--format', type=click.Choice(['text', 'json', 'yaml']), default='text')
def show_docs(protocol_method: Optional[str], format: str):
    """
    Show documentation for handlers.

    Examples:
        gleitzeit docs                    # List all protocols
        gleitzeit docs ollama/v1          # Show all methods for protocol
        gleitzeit docs ollama/v1:generate # Show specific method
    """
    from ..core.handler_registry import get_handler_for_protocol

    if not protocol_method:
        # List all available protocols
        click.echo("Available protocols:")
        # ... list protocols from registry
        return

    # Parse protocol and method
    if ':' in protocol_method:
        protocol, method = protocol_method.split(':', 1)
    else:
        protocol = protocol_method
        method = None

    # Get handler
    handler = get_handler_for_protocol(protocol)
    if not handler:
        click.echo(f"❌ Unknown protocol: {protocol}")
        return

    # Get schema
    schema = handler.get_param_schema()

    if format == 'json':
        click.echo(json.dumps(schema, indent=2))
    elif format == 'yaml':
        click.echo(yaml.dump(schema))
    else:
        # Pretty print for terminal
        _print_handler_docs(schema, method)

def _print_handler_docs(schema: Dict[str, Any], method: Optional[str] = None):
    """Pretty print handler documentation."""
    click.echo(f"\n📚 Handler Documentation: {schema['protocol']}")
    click.echo("=" * 70)

    methods = schema.get('methods', {})

    if method:
        # Show specific method
        if method not in methods:
            click.echo(f"❌ Method '{method}' not found")
            return
        _print_method_docs(method, methods[method])
    else:
        # Show all methods
        for method_name, method_schema in methods.items():
            _print_method_docs(method_name, method_schema)
            click.echo()

def _print_method_docs(method_name: str, method_schema: Dict[str, Any]):
    """Print documentation for a single method."""
    click.echo(f"\n🔹 Method: {method_name}")

    # Required parameters
    required = method_schema.get('required', [])
    if required:
        click.echo(f"\n  Required parameters:")
        for param in required:
            click.echo(f"    • {param}")

    # Optional parameters
    optional = method_schema.get('optional', {})
    if optional:
        click.echo(f"\n  Optional parameters:")
        for param, spec in optional.items():
            type_str = spec.get('type', 'any')
            default = spec.get('default')
            desc = spec.get('description', 'No description')
            range_str = ""
            if 'range' in spec:
                range_str = f" (range: {spec['range'][0]}-{spec['range'][1]})"

            click.echo(f"    • {param}: {type_str}{range_str}")
            click.echo(f"      Default: {default}")
            click.echo(f"      {desc}")

    # Examples
    examples = method_schema.get('examples', [])
    if examples:
        click.echo(f"\n  Examples:")
        for i, example in enumerate(examples, 1):
            click.echo(f"    Example {i}:")
            click.echo(f"      {json.dumps(example, indent=6)}")
```

#### Usage Examples

```bash
# List all available protocols
$ gleitzeit docs
Available protocols:
  • python/v1: Python code execution
  • ollama/v1: LLM inference via Ollama
  • http/v1: HTTP requests
  • file/v1: File operations
  • custom/v1: Custom company handler

# Show documentation for a protocol
$ gleitzeit docs ollama/v1

📚 Handler Documentation: ollama/v1
======================================================================

🔹 Method: generate

  Required parameters:
    • prompt

  Optional parameters:
    • model: str
      Default: llama2
      Model name to use for generation

    • temperature: float (range: 0-2)
      Default: 0.7
      Sampling temperature

    • max_tokens: int (range: 1-4096)
      Default: 1000
      Maximum tokens to generate

  Examples:
    Example 1:
      {
        "prompt": "Explain quantum computing",
        "model": "llama2",
        "temperature": 0.7
      }
    Example 2:
      {
        "prompt": "Write a function to sort a list",
        "model": "codellama",
        "temperature": 0.3
      }

# Show specific method documentation
$ gleitzeit docs python/v1:execute

📚 Handler Documentation: python/v1
======================================================================

🔹 Method: execute

  Optional parameters:
    • code: str
      Default: None
      Python code to execute

    • file: str
      Default: None
      Path to Python file to execute

    • env: dict
      Default: {}
      Environment variables

    • timeout: int
      Default: 300
      Execution timeout in seconds

  Examples:
    Example 1:
      {"code": "print(\"hello world\")"}
    Example 2:
      {"file": "/path/to/script.py", "env": {"DEBUG": "1"}}
```

### Auto-Validation from Schema

TaskBuilder can optionally load schema and auto-validate:

```python
class TaskBuilder:
    def auto_validate(self) -> 'TaskBuilder':
        """
        Load handler schema and configure validation automatically.

        Returns:
            Self for chaining
        """
        # Get handler for this protocol
        from ..core.handler_registry import get_handler_for_protocol
        handler = get_handler_for_protocol(self.protocol)

        if handler:
            schema = handler.get_param_schema()
            method_name = self.full_method.split('/')[-1]  # Extract method name

            if method_name in schema.get('methods', {}):
                method_schema = schema['methods'][method_name]

                # Configure required params
                if method_schema.get('required'):
                    self.require(*method_schema['required'])

                # Configure type checking
                type_specs = {}
                range_specs = {}
                for param, spec in method_schema.get('optional', {}).items():
                    if 'type' in spec:
                        type_map = {
                            'str': str,
                            'int': int,
                            'float': (int, float),
                            'bool': bool,
                            'dict': dict,
                            'list': list
                        }
                        if spec['type'] in type_map:
                            type_specs[param] = type_map[spec['type']]

                    if 'range' in spec:
                        min_val, max_val = spec['range']
                        range_specs[param] = (min_val, max_val)

                if type_specs:
                    self.expect_types(**type_specs)

                for param, (min_val, max_val) in range_specs.items():
                    self.expect_range(param, min_val, max_val)

        return self.validate()

# Usage
task = t("analyze", "ollama/v1:generate")
    .with_(prompt="...", temperature=0.7)
    .auto_validate()  # ← Automatically validates against handler schema!
```

### Implementation Details

**Files to Modify**:
- `src/gleitzeit/handlers/base.py`: Add `get_param_schema()`
- `src/gleitzeit/handlers/python.py`: Implement schema
- `src/gleitzeit/handlers/ollama.py`: Implement schema
- `src/gleitzeit/handlers/http.py`: Implement schema
- `src/gleitzeit/cli/main.py`: Add `docs` command
- `src/gleitzeit/easy/task_builder.py`: Add `auto_validate()`

**Backward Compatibility**: ✅ 100% compatible - new feature, no changes to existing API

---

## Enhancement 3: DAG Pattern Helpers

### Problem Statement

Common workflow patterns require verbose boilerplate code.

**Current Experience**:
```python
# Fan-out pattern (one task feeds many)
task1 = t("fetch", "http/v1:request").with_(url="...")
task2 = t("process1", "python/v1:execute").with_(code="...").needs("fetch")
task3 = t("process2", "python/v1:execute").with_(code="...").needs("fetch")
task4 = t("process3", "python/v1:execute").with_(code="...").needs("fetch")

# Fan-in pattern (many tasks feed one)
task5 = t("merge", "python/v1:execute").with_(code="...").needs("process1", "process2", "process3")

workflow = w(task1, task2, task3, task4, task5)  # Verbose!
```

### Design: Pattern Helper Methods

Add methods to `WorkflowBuilder` that express common DAG patterns clearly.

#### API Design

```python
class WorkflowBuilder:
    def pipeline(self, *tasks: TaskBuilder) -> 'WorkflowBuilder':
        """
        Create sequential pipeline: task1 → task2 → task3

        Each task depends on the previous one.

        Args:
            *tasks: Tasks to chain sequentially

        Returns:
            Self for chaining

        Example:
            workflow.pipeline(
                t("fetch", "http/v1:request").with_(...),
                t("parse", "python/v1:execute").with_(...),
                t("save", "python/v1:execute").with_(...)
            )
            # fetch → parse → save
        """
        prev = None
        for task in tasks:
            if prev:
                task.needs(prev.task_id)
            self.add_task(task)
            prev = task
        return self

    def fan_out(
        self,
        source: Union[str, TaskBuilder],
        *consumers: TaskBuilder
    ) -> 'WorkflowBuilder':
        """
        Create fan-out pattern: one producer, many parallel consumers.

                      ┌→ consumer1
        source ──────→├→ consumer2
                      └→ consumer3

        Args:
            source: Source task (name or TaskBuilder)
            *consumers: Tasks that depend on source

        Returns:
            Self for chaining

        Example:
            workflow.fan_out(
                t("fetch", "http/v1:request").with_(...),
                t("process1", "python/v1:execute").with_(...),
                t("process2", "python/v1:execute").with_(...),
                t("process3", "python/v1:execute").with_(...)
            )
        """
        # Add source task if it's a TaskBuilder
        if isinstance(source, TaskBuilder):
            self.add_task(source)
            source_id = source.task_id
        else:
            source_id = source

        # Add consumers with dependency on source
        for consumer in consumers:
            consumer.needs(source_id)
            self.add_task(consumer)

        return self

    def fan_in(
        self,
        *sources: Union[str, TaskBuilder],
        aggregator: TaskBuilder
    ) -> 'WorkflowBuilder':
        """
        Create fan-in pattern: many producers, one consumer.

        producer1 ─┐
        producer2 ─┼→ aggregator
        producer3 ─┘

        Args:
            *sources: Source tasks (names or TaskBuilders)
            aggregator: Task that depends on all sources

        Returns:
            Self for chaining

        Example:
            workflow.fan_in(
                t("task1", ...).with_(...),
                t("task2", ...).with_(...),
                t("task3", ...).with_(...),
                aggregator=t("merge", ...).with_(...)
            )
        """
        source_ids = []

        # Add source tasks if they're TaskBuilders
        for source in sources:
            if isinstance(source, TaskBuilder):
                self.add_task(source)
                source_ids.append(source.task_id)
            else:
                source_ids.append(source)

        # Add aggregator with dependencies on all sources
        aggregator.needs(*source_ids)
        self.add_task(aggregator)

        return self

    def broadcast(
        self,
        source: Union[str, TaskBuilder],
        *consumers: TaskBuilder
    ) -> 'WorkflowBuilder':
        """
        Alias for fan_out (more intuitive name for some use cases).

        Args:
            source: Source task
            *consumers: Consumer tasks

        Returns:
            Self for chaining
        """
        return self.fan_out(source, *consumers)

    def aggregate(
        self,
        *sources: Union[str, TaskBuilder],
        aggregator: TaskBuilder
    ) -> 'WorkflowBuilder':
        """
        Alias for fan_in (more intuitive name for some use cases).

        Args:
            *sources: Source tasks
            aggregator: Aggregator task

        Returns:
            Self for chaining
        """
        return self.fan_in(*sources, aggregator=aggregator)

    def diamond(
        self,
        source: TaskBuilder,
        *parallel_tasks: TaskBuilder,
        aggregator: TaskBuilder
    ) -> 'WorkflowBuilder':
        """
        Create diamond pattern: fan-out then fan-in.

                      ┌→ task1 ─┐
        source ──────→├→ task2 ─┼→ aggregator
                      └→ task3 ─┘

        Args:
            source: Initial task
            *parallel_tasks: Tasks that run in parallel
            aggregator: Final task that aggregates results

        Returns:
            Self for chaining

        Example:
            workflow.diamond(
                t("fetch", "http/v1:request").with_(...),
                t("process1", "python/v1:execute").with_(...),
                t("process2", "python/v1:execute").with_(...),
                t("process3", "python/v1:execute").with_(...),
                aggregator=t("merge", "python/v1:execute").with_(...)
            )
        """
        self.add_task(source)
        self.fan_out(source.task_id, *parallel_tasks)
        parallel_ids = [task.task_id for task in parallel_tasks]
        self.fan_in(*parallel_ids, aggregator=aggregator)
        return self
```

#### Usage Examples

```python
# Example 1: Simple pipeline
workflow = WorkflowBuilder().pipeline(
    t("fetch", "http/v1:request").with_(url="https://api.example.com"),
    t("parse", "python/v1:execute").with_(code="parse_json(input)"),
    t("transform", "python/v1:execute").with_(code="transform_data(input)"),
    t("save", "python/v1:execute").with_(code="save_to_db(input)")
)
# Dependency chain: fetch → parse → transform → save

# Example 2: Fan-out pattern
workflow = WorkflowBuilder().fan_out(
    t("fetch", "http/v1:request").with_(url="..."),
    t("analyze_sentiment", "ollama/v1:generate").with_(prompt="..."),
    t("extract_entities", "ollama/v1:generate").with_(prompt="..."),
    t("summarize", "ollama/v1:generate").with_(prompt="...")
)
# fetch feeds into 3 parallel analysis tasks

# Example 3: Fan-in pattern
workflow = WorkflowBuilder(
    t("fetch1", "http/v1:request").with_(url="..."),
    t("fetch2", "http/v1:request").with_(url="..."),
    t("fetch3", "http/v1:request").with_(url="...")
).fan_in(
    "fetch1", "fetch2", "fetch3",
    aggregator=t("combine", "python/v1:execute").with_(code="...")
)
# 3 parallel fetches feed into combine task

# Example 4: Diamond pattern
workflow = WorkflowBuilder().diamond(
    t("fetch", "http/v1:request").with_(url="..."),
    t("process1", "python/v1:execute").with_(code="..."),
    t("process2", "python/v1:execute").with_(code="..."),
    t("process3", "python/v1:execute").with_(code="..."),
    aggregator=t("merge", "python/v1:execute").with_(code="...")
)
# fetch → [process1, process2, process3] → merge

# Example 5: Complex workflow combining patterns
workflow = WorkflowBuilder().pipeline(
    t("init", "python/v1:execute").with_(code="initialize()"),
    t("fetch", "http/v1:request").with_(url="...")
).fan_out(
    "fetch",
    t("validate", "python/v1:execute").with_(code="..."),
    t("transform", "python/v1:execute").with_(code="..."),
    t("enrich", "ollama/v1:generate").with_(prompt="...")
).fan_in(
    "validate", "transform", "enrich",
    aggregator=t("merge", "python/v1:execute").with_(code="...")
).pipeline(
    t("final_check", "python/v1:execute").with_(code="..."),
    t("save", "python/v1:execute").with_(code="...")
)
# init → fetch → [validate, transform, enrich] → merge → final_check → save
```

### Visualization Helper

Add method to visualize workflow structure:

```python
class WorkflowBuilder:
    def print_dag(self, format: str = 'ascii') -> None:
        """
        Print workflow DAG structure.

        Args:
            format: 'ascii' or 'mermaid'
        """
        if format == 'ascii':
            self._print_ascii_dag()
        elif format == 'mermaid':
            self._print_mermaid_dag()

    def _print_ascii_dag(self) -> None:
        """Print ASCII art representation of DAG."""
        print(f"\nWorkflow: {self.workflow_name or 'Unnamed'}")
        print("=" * 60)

        # Build dependency graph
        graph = {}
        for task in self.tasks:
            graph[task.task_id] = task.dependencies.copy()

        # Print topologically sorted
        printed = set()

        def print_task(task_id: str, indent: int = 0):
            if task_id in printed:
                return

            # Print dependencies first
            deps = graph.get(task_id, [])
            for dep in deps:
                print_task(dep, indent)

            # Print this task
            task = self.get_task(task_id)
            prefix = "  " * indent
            print(f"{prefix}🔹 {task_id} ({task.protocol}:{task.full_method.split('/')[-1]})")
            if deps:
                print(f"{prefix}   ↳ depends on: {', '.join(deps)}")

            printed.add(task_id)

        for task in self.tasks:
            print_task(task.task_id)

    def _print_mermaid_dag(self) -> None:
        """Print Mermaid diagram syntax for DAG."""
        print("```mermaid")
        print("graph TD")

        for task in self.tasks:
            task_label = f"{task.task_id}<br/>{task.protocol}"
            print(f"  {task.task_id}[\"{task_label}\"]")

            for dep in task.dependencies:
                print(f"  {dep} --> {task.task_id}")

        print("```")

# Usage
workflow = WorkflowBuilder().diamond(
    t("fetch", "http/v1:request").with_(url="..."),
    t("process1", "python/v1:execute").with_(code="..."),
    t("process2", "python/v1:execute").with_(code="..."),
    aggregator=t("merge", "python/v1:execute").with_(code="...")
)

workflow.print_dag()
# Output:
# Workflow: Unnamed
# ============================================================
# 🔹 fetch (http/v1:request)
# 🔹 process1 (python/v1:execute)
#    ↳ depends on: fetch
# 🔹 process2 (python/v1:execute)
#    ↳ depends on: fetch
# 🔹 merge (python/v1:execute)
#    ↳ depends on: process1, process2
```

### Implementation Details

**Files to Modify**:
- `src/gleitzeit/easy/workflow_builder.py`: Add pattern methods

**Backward Compatibility**: ✅ 100% compatible - new methods, no changes to existing API

**Performance Impact**: Negligible - just convenience methods

---

## Enhancement 4: Better Error Messages

### Problem Statement

Cryptic errors when protocols don't exist or parameters are invalid.

**Current Experience**:
```python
task = t("analyze", "olama/v1:generate")  # Typo: "olama" not "ollama"
# Error: Unknown protocol: olama/v1
# User doesn't know what the correct protocol is
```

### Design: Intelligent Error Suggestions

#### Protocol Suggestions

```python
# Add to protocol_registry.py
from difflib import get_close_matches

class ProtocolRegistry:
    def suggest_protocol(self, invalid: str) -> List[str]:
        """
        Suggest similar protocols for typos.

        Args:
            invalid: Invalid protocol string

        Returns:
            List of similar protocol names
        """
        all_protocols = list(self._registry.keys())
        return get_close_matches(invalid, all_protocols, n=3, cutoff=0.6)

    def list_protocols(self) -> List[str]:
        """Return list of all registered protocols."""
        return list(self._registry.keys())

# Update error handling in task_builder.py
def __init__(self, task_id: str, protocol_method: str):
    try:
        protocol, method = registry.parse_protocol_method(protocol_method)
    except InvalidProtocolFormatError as e:
        # Try to suggest corrections
        suggestions = registry.suggest_protocol(protocol_method)

        if suggestions:
            raise InvalidProtocolFormatError(
                f"Unknown protocol '{protocol_method}'.\n"
                f"Did you mean one of these?\n" +
                "\n".join(f"  • {s}" for s in suggestions)
            )
        else:
            available = registry.list_protocols()
            raise InvalidProtocolFormatError(
                f"Unknown protocol '{protocol_method}'.\n"
                f"Available protocols:\n" +
                "\n".join(f"  • {p}" for p in available)
            )
```

#### Parameter Suggestions

```python
# Enhanced error messages for parameter validation
class TaskBuilder:
    def validate(self) -> 'TaskBuilder':
        # ... existing validation ...

        # Check for common typos in parameter names
        if hasattr(self, '_required_params'):
            # Get handler schema to suggest correct param names
            from ..core.handler_registry import get_handler_for_protocol
            handler = get_handler_for_protocol(self.protocol)

            if handler:
                schema = handler.get_param_schema()
                method_name = self.full_method.split('/')[-1]
                method_schema = schema.get('methods', {}).get(method_name, {})

                valid_params = set(method_schema.get('required', []))
                valid_params.update(method_schema.get('optional', {}).keys())

                # Check for typos in provided params
                for provided_param in self.parameters.keys():
                    if provided_param not in valid_params:
                        suggestions = get_close_matches(
                            provided_param,
                            list(valid_params),
                            n=1,
                            cutoff=0.6
                        )
                        if suggestions:
                            raise InvalidParameterError(
                                provided_param,
                                self.parameters[provided_param],
                                self.task_id,
                                f"Unknown parameter '{provided_param}'. "
                                f"Did you mean '{suggestions[0]}'?"
                            )

        return self
```

#### Example Error Messages

```python
# Before (cryptic)
task = t("analyze", "olama/v1:generate")
# Error: Unknown protocol: olama/v1

# After (helpful)
task = t("analyze", "olama/v1:generate")
# Error: Unknown protocol 'olama/v1'.
# Did you mean one of these?
#   • ollama/v1
#   • llama/v1

# Before (cryptic)
task = t("analyze", "ollama/v1:generate").with_(promt="...")
# Error: Missing required parameter: prompt

# After (helpful)
task = t("analyze", "ollama/v1:generate").with_(promt="...").validate()
# Error: Unknown parameter 'promt'. Did you mean 'prompt'?
```

### Implementation Details

**Files to Modify**:
- `src/gleitzeit/easy/protocol_registry.py`: Add suggestion methods
- `src/gleitzeit/easy/task_builder.py`: Enhanced error messages
- `src/gleitzeit/easy/errors.py`: Better error formatting

**Backward Compatibility**: ✅ 100% compatible - better errors, same API

---

## Implementation Plan

### Phase 1: Runtime Validation (Week 1)
- [ ] Add validation methods to `TaskBuilder`
  - [ ] `.require()` for required parameters
  - [ ] `.expect_types()` for type checking
  - [ ] `.expect_range()` for range validation
  - [ ] `.validate()` for execution
- [ ] Add `.validate_all()` to `WorkflowBuilder`
- [ ] Update error messages
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Update documentation

### Phase 2: Handler Documentation (Week 2)
- [ ] Add `get_param_schema()` to `BaseHandler`
- [ ] Implement schemas in handlers:
  - [ ] `PythonHandler`
  - [ ] `OllamaHandler`
  - [ ] `HTTPHandler`
  - [ ] `FileHandler`
- [ ] Add `gleitzeit docs` CLI command
- [ ] Add `.auto_validate()` to `TaskBuilder`
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Update documentation

### Phase 3: DAG Patterns (Week 3)
- [ ] Add pattern methods to `WorkflowBuilder`:
  - [ ] `.pipeline()`
  - [ ] `.fan_out()`
  - [ ] `.fan_in()`
  - [ ] `.diamond()`
- [ ] Add `.print_dag()` visualization
- [ ] Write unit tests
- [ ] Create example workflows
- [ ] Update documentation

### Phase 4: Error Improvements (Week 3)
- [ ] Add `.suggest_protocol()` to `ProtocolRegistry`
- [ ] Enhanced error messages in `TaskBuilder`
- [ ] Parameter typo detection
- [ ] Write unit tests
- [ ] Update documentation

### Phase 5: Polish & Release (Week 4)
- [ ] Performance testing
- [ ] Integration testing with full workflows
- [ ] Migration guide
- [ ] Example notebooks
- [ ] Video tutorials
- [ ] Release notes
- [ ] Announcement

---

## Testing Strategy

### Unit Tests

```python
# test_task_builder_validation.py
def test_require_missing_param():
    task = t("test", "python/v1:execute").require('code')
    with pytest.raises(InvalidParameterError):
        task.validate()

def test_require_with_param():
    task = t("test", "python/v1:execute").require('code').with_(code="...")
    task.validate()  # Should pass

def test_expect_types():
    task = t("test", "ollama/v1:generate").expect_types(temperature=(int, float))
    task.with_(temperature="not a number")
    with pytest.raises(InvalidParameterError):
        task.validate()

def test_dynamic_resolution_skipped():
    task = t("test", "python/v1:execute").require('input')
    task.with_(input="${task1.output}")  # Dynamic expression
    task.validate()  # Should pass (validation skipped for ${...})

# test_workflow_builder_patterns.py
def test_pipeline():
    workflow = WorkflowBuilder().pipeline(
        t("task1", "python/v1:execute").with_(code="..."),
        t("task2", "python/v1:execute").with_(code="..."),
        t("task3", "python/v1:execute").with_(code="...")
    )
    assert len(workflow.tasks) == 3
    assert "task1" in workflow.get_task("task2").dependencies
    assert "task2" in workflow.get_task("task3").dependencies

def test_fan_out():
    workflow = WorkflowBuilder().fan_out(
        t("source", "python/v1:execute").with_(code="..."),
        t("consumer1", "python/v1:execute").with_(code="..."),
        t("consumer2", "python/v1:execute").with_(code="...")
    )
    assert "source" in workflow.get_task("consumer1").dependencies
    assert "source" in workflow.get_task("consumer2").dependencies

# test_handler_schema.py
def test_ollama_schema():
    handler = OllamaHandler()
    schema = handler.get_param_schema()
    assert 'generate' in schema['methods']
    assert 'prompt' in schema['methods']['generate']['required']
    assert 'model' in schema['methods']['generate']['optional']
```

### Integration Tests

```python
# test_easy_client_integration.py
def test_validated_workflow_submission():
    workflow = WorkflowBuilder(
        t("fetch", "http/v1:request")
            .require('url')
            .with_(url="https://api.example.com")
            .validate(),
        t("process", "python/v1:execute")
            .require('code')
            .with_(code="process(input)")
            .validate()
    ).validate_all()

    # Should submit successfully
    response = workflow.submit()
    assert response['workflow_id']

def test_dag_patterns():
    workflow = WorkflowBuilder().diamond(
        t("fetch", "http/v1:request").with_(url="..."),
        t("process1", "python/v1:execute").with_(code="..."),
        t("process2", "python/v1:execute").with_(code="..."),
        aggregator=t("merge", "python/v1:execute").with_(code="...")
    )

    response = workflow.submit()
    assert response['workflow_id']
```

---

## Performance Benchmarks

### Expected Performance

| Operation | Current | With Enhancements | Overhead |
|-----------|---------|-------------------|----------|
| Task creation | 0.001ms | 0.001ms | +0% |
| Task validation | N/A | 0.002ms | +0.002ms |
| Workflow submission | 10ms | 10.002ms | +0.02% |
| Auto-validation | N/A | 0.5ms | +0.5ms |

**Conclusion**: Negligible performance impact (<1%)

---

## Backward Compatibility

### Compatibility Matrix

| Feature | Existing Code | Impact |
|---------|---------------|--------|
| Task validation | Still works | ✅ No impact |
| Handler schemas | Still works | ✅ No impact |
| DAG patterns | Still works | ✅ No impact |
| Error messages | Better errors | ✅ Improvement |

### Migration Guide

**No migration required!** All enhancements are opt-in:

```python
# Old code continues to work exactly as before
task = t("analyze", "ollama/v1:generate").with_(prompt="...")
workflow = w(task).submit()

# New code can optionally use enhancements
task = t("analyze", "ollama/v1:generate")
    .require('prompt')  # ← NEW (optional)
    .with_(prompt="...")
    .validate()  # ← NEW (optional)

workflow = WorkflowBuilder().pipeline(  # ← NEW (optional)
    task1, task2, task3
).validate_all().submit()  # ← NEW (optional)
```

---

## Documentation Updates

### User Guide Sections to Add

1. **Runtime Validation**
   - How to use `.require()`
   - How to use `.expect_types()`
   - How to use `.expect_range()`
   - When validation is skipped (dynamic expressions)

2. **Handler Documentation**
   - How to view handler docs with `gleitzeit docs`
   - How to use `.auto_validate()`
   - How handlers implement schemas

3. **Workflow Patterns**
   - `.pipeline()` for sequential tasks
   - `.fan_out()` for parallel processing
   - `.fan_in()` for aggregation
   - `.diamond()` for fan-out-in
   - Complex pattern combinations

4. **Error Messages**
   - Understanding error suggestions
   - Common typos and fixes

### API Reference Updates

- `TaskBuilder` new methods
- `WorkflowBuilder` new methods
- `BaseHandler.get_param_schema()`
- CLI `docs` command

---

## Success Metrics

### Adoption Metrics
- % of workflows using `.validate()`
- % of workflows using DAG patterns
- `gleitzeit docs` command usage

### Quality Metrics
- Reduction in runtime parameter errors
- Reduction in support tickets
- Developer satisfaction survey

### Performance Metrics
- Workflow submission latency (should remain <1% impact)
- Validation overhead (should be <1ms per task)

---

## Risks & Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking changes | High | Low | 100% backward compatible |
| Performance degradation | Medium | Low | Benchmarking, opt-in validation |
| Complexity increase | Medium | Medium | Good documentation, examples |
| Handler schema maintenance | Low | Medium | Auto-generation from code |

---

## Future Enhancements (Post-Release)

### Phase 2 (Future)

1. **Schema Auto-Generation**
   - Generate schemas from handler code
   - Type hints → parameter schemas

2. **Visual Workflow Builder**
   - Web UI for building workflows
   - Drag-and-drop task composition

3. **Workflow Templates Library**
   - Pre-built patterns for common use cases
   - Community-contributed templates

4. **Advanced Validation**
   - Custom validation rules
   - Cross-task validation
   - Resource constraints

---

## Conclusion

This design provides practical, architecture-compliant enhancements to Easy Client that:

✅ **Preserve dynamic resolution** - Validation skips `${...}` expressions
✅ **Maintain flexibility** - No hardcoded protocols or schemas
✅ **Respect stateless architecture** - All state in Redis
✅ **Are backward compatible** - 100% opt-in enhancements
✅ **Address real pain points** - Better errors, validation, patterns

### Recommended Approach

**Start with Phases 1-2** (Validation + Documentation):
- Biggest immediate impact
- Lowest risk
- Foundation for future enhancements

**Then add Phase 3** (DAG Patterns) based on user feedback.

This approach delivers **real value** without architectural violations or unnecessary complexity.
