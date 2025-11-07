# Easy Client Enhancements - Implementation Documentation

**Version**: 0.0.7
**Status**: ✅ Implemented
**Date**: 2025-09-30

## Overview

This document describes the enhancements made to the Gleitzeit Easy Client to provide runtime validation, DAG pattern helpers, and better error messages while preserving 100% backward compatibility.

## Table of Contents

1. [Runtime Validation Framework](#runtime-validation-framework)
2. [DAG Pattern Helpers](#dag-pattern-helpers)
3. [Enhanced Error Messages](#enhanced-error-messages)
4. [Central Error System Integration](#central-error-system-integration)
5. [Usage Examples](#usage-examples)
6. [Migration Guide](#migration-guide)

---

## Runtime Validation Framework

### Overview

The runtime validation framework allows you to specify parameter requirements and validation rules that are checked when building workflows, catching errors early while still supporting Gleitzeit's dynamic parameter resolution.

### Features

- **Required Parameters**: Mark parameters as required
- **Type Checking**: Specify expected parameter types
- **Range Validation**: Define valid ranges for numeric parameters
- **Dynamic Expression Support**: Automatically skips validation for runtime-resolved expressions like `${task1.output}`
- **Auto-validation**: Optional automatic validation when building workflows

### API Reference

#### `.require(*param_names: str) -> TaskBuilder`

Mark parameters as required.

```python
task = t("analyze", "ollama/v1:generate")
    .require('prompt', 'model')  # Mark prompt and model as required
    .with_(prompt="Analyze this", model="llama2")
    .validate()  # Will fail if prompt or model is missing
```

**Parameters:**
- `*param_names`: Names of required parameters

**Returns:** Self for chaining

**Raises:** `TaskBuilderError` if validation is called and required params are missing

---

#### `.expect_types(**type_specs) -> TaskBuilder`

Specify expected types for parameters.

```python
task = t("process", "python/v1:execute")
    .expect_types(
        temperature=(int, float),  # Allow int or float
        max_tokens=int,            # Only int
        enabled=bool               # Only bool
    )
    .with_(temperature=0.7, max_tokens=1000, enabled=True)
    .validate()  # Will fail if types don't match
```

**Parameters:**
- `**type_specs`: Parameter name -> type(s) mapping. Can be single type or tuple of types.

**Returns:** Self for chaining

**Raises:** `TaskBuilderError` if validation is called and types don't match

**Note:** Dynamic expressions like `"${task1.output}"` are skipped during type checking.

---

#### `.expect_range(param_name: str, min_val: Any, max_val: Any) -> TaskBuilder`

Specify expected range for a numeric parameter.

```python
task = t("analyze", "ollama/v1:generate")
    .expect_range('temperature', 0, 2)      # Temperature must be 0-2
    .expect_range('max_tokens', 1, 10000)   # Max tokens must be 1-10000
    .with_(temperature=0.7, max_tokens=1000)
    .validate()  # Will fail if values are out of range
```

**Parameters:**
- `param_name`: Name of parameter
- `min_val`: Minimum allowed value (inclusive)
- `max_val`: Maximum allowed value (inclusive)

**Returns:** Self for chaining

**Raises:** `TaskBuilderError` if validation is called and value is out of range

---

#### `.validate() -> TaskBuilder`

Validate task parameters against specified rules.

```python
task = t("analyze", "ollama/v1:generate")
    .require('prompt')
    .expect_types(temperature=(int, float))
    .expect_range('temperature', 0, 2)
    .with_(prompt="Analyze this", temperature=0.7)
    .validate()  # Validates all rules
```

**Checks:**
- Required parameters are present
- Parameter types match expected types
- Numeric parameters are within expected ranges

**Returns:** Self for chaining

**Raises:** `TaskBuilderError` with detailed error messages if validation fails

---

#### `.auto_validate(enabled: bool = True) -> TaskBuilder`

Enable automatic validation when building workflow.

```python
task = t("analyze", "ollama/v1:generate")
    .require('prompt')
    .auto_validate()  # Will validate when added to workflow
    .with_(prompt="Analyze this")

workflow = w(task)  # Validation happens here automatically
```

**Parameters:**
- `enabled`: Whether to enable auto-validation (default: True)

**Returns:** Self for chaining

---

### Complete Example

```python
from gleitzeit.easy import t, w

# Define task with validation rules
task = t("analyze", "ollama/v1:generate")
    .require('prompt', 'model')                    # Required params
    .expect_types(
        prompt=str,
        model=str,
        temperature=(int, float),
        max_tokens=int
    )
    .expect_range('temperature', 0, 2)             # Valid range
    .expect_range('max_tokens', 1, 10000)
    .with_(
        prompt="Analyze this code",
        model="llama2",
        temperature=0.7,
        max_tokens=1000
    )
    .validate()  # Explicit validation

# Or use auto-validation
task2 = t("process", "python/v1:execute")
    .require('code')
    .auto_validate()  # Validates on workflow build
    .with_(code="print('hello')")

workflow = w(task, task2).submit()
```

---

## DAG Pattern Helpers

### Overview

DAG pattern helpers provide convenient methods for creating common workflow patterns while respecting Gleitzeit's dependency-based execution model.

### Features

- **Pipeline**: Sequential task chains
- **Fan-out**: One producer, many parallel consumers
- **Fan-in**: Many producers, one consumer
- **Diamond**: Fan-out followed by fan-in
- **DAG Visualization**: ASCII tree visualization

### API Reference

#### `.pipeline(*tasks: TaskBuilder) -> WorkflowBuilder`

Create a sequential pipeline where each task depends on the previous.

```python
workflow = w().pipeline(
    t("fetch", "http/v1:request").with_(url="..."),
    t("process", "python/v1:execute").with_(code="..."),
    t("analyze", "ollama/v1:generate").with_(prompt="..."),
    t("save", "python/v1:execute").with_(code="...")
)
# Creates: fetch → process → analyze → save
```

**Parameters:**
- `*tasks`: Tasks to chain sequentially

**Returns:** Self for chaining

---

#### `.fan_out(source: Union[str, TaskBuilder], *consumers: TaskBuilder) -> WorkflowBuilder`

Create a fan-out pattern: one producer feeds multiple consumers.

```python
workflow = w(
    t("fetch", "http/v1:request").with_(url="...")
).fan_out("fetch",
    t("process1", "python/v1:execute").with_(code="..."),
    t("process2", "python/v1:execute").with_(code="..."),
    t("process3", "python/v1:execute").with_(code="...")
)
# Creates: fetch → [process1, process2, process3] (parallel)
```

**Parameters:**
- `source`: Source task ID or TaskBuilder
- `*consumers`: Consumer tasks that depend on source

**Returns:** Self for chaining

**Raises:** `WorkflowBuilderError` if source task not found

---

#### `.fan_in(*sources: Union[str, TaskBuilder], aggregator: TaskBuilder) -> WorkflowBuilder`

Create a fan-in pattern: multiple producers feed one consumer.

```python
workflow = w(
    t("fetch1", "http/v1:request"),
    t("fetch2", "http/v1:request"),
    t("fetch3", "http/v1:request")
).fan_in("fetch1", "fetch2", "fetch3",
    aggregator=t("merge", "python/v1:execute").with_(code="...")
)
# Creates: [fetch1, fetch2, fetch3] → merge
```

**Parameters:**
- `*sources`: Source task IDs or TaskBuilders
- `aggregator`: Consumer task that depends on all sources

**Returns:** Self for chaining

**Raises:** `WorkflowBuilderError` if source tasks not found

---

#### `.diamond(source: Union[str, TaskBuilder], *middle_tasks: TaskBuilder, aggregator: TaskBuilder) -> WorkflowBuilder`

Create a diamond pattern: fan-out then fan-in.

```python
workflow = w(
    t("fetch", "http/v1:request").with_(url="...")
).diamond("fetch",
    t("process1", "python/v1:execute"),
    t("process2", "python/v1:execute"),
    t("process3", "python/v1:execute"),
    aggregator=t("merge", "python/v1:execute")
)
# Creates:
#        process1
#       /         \
# fetch - process2 - merge
#       \         /
#        process3
```

**Parameters:**
- `source`: Source task ID or TaskBuilder
- `*middle_tasks`: Tasks that depend on source
- `aggregator`: Final task that depends on all middle tasks

**Returns:** Self for chaining

---

#### `.broadcast(source, *consumers) -> WorkflowBuilder`

Broadcast pattern: alias for fan_out with clearer semantics.

```python
workflow = w(
    t("load_config", "python/v1:execute")
).broadcast("load_config",
    t("service1", "python/v1:execute"),
    t("service2", "python/v1:execute"),
    t("service3", "python/v1:execute")
)
```

---

#### `.aggregate(*sources, aggregator) -> WorkflowBuilder`

Aggregation pattern: alias for fan_in with clearer semantics.

```python
workflow = w(
    t("query1", "http/v1:request"),
    t("query2", "http/v1:request"),
    t("query3", "http/v1:request")
).aggregate("query1", "query2", "query3",
    aggregator=t("combine", "python/v1:execute")
)
```

---

#### `.print_dag()`

Print a visual representation of the workflow DAG.

```python
workflow = w(
    t("fetch", "http/v1:request")
).fan_out("fetch",
    t("process1", "python/v1:execute"),
    t("process2", "python/v1:execute")
).fan_in("process1", "process2",
    aggregator=t("merge", "python/v1:execute")
)

workflow.print_dag()
```

**Output:**
```
Workflow DAG: Data Pipeline

fetch (no dependencies)
  └─> process1
        └─> merge
  └─> process2
        └─> merge
```

---

### Complete Example

```python
from gleitzeit.easy import t, w

# Complex data processing pipeline
workflow = w(
    # Initial data fetch
    t("fetch_data", "http/v1:request").with_(
        url="https://api.example.com/data"
    )
).fan_out("fetch_data",
    # Parallel processing
    t("validate", "python/v1:execute").with_(code="validate_data()"),
    t("transform", "python/v1:execute").with_(code="transform_data()"),
    t("enrich", "python/v1:execute").with_(code="enrich_data()")
).fan_in("validate", "transform", "enrich",
    # Aggregate results
    aggregator=t("combine", "python/v1:execute").with_(
        code="combine_results()"
    )
).pipeline(
    # Sequential analysis
    t("combine", "python/v1:execute"),  # Already added
    t("analyze", "ollama/v1:generate").with_(
        prompt="Analyze the combined data"
    ),
    t("report", "python/v1:execute").with_(
        code="generate_report()"
    )
)

# Visualize the workflow
workflow.print_dag()

# Submit
response = workflow.submit()
```

---

## Enhanced Error Messages

### Overview

Enhanced error messages use fuzzy matching to suggest corrections when you mistype protocols, methods, or parameters.

### Features

- **Fuzzy Matching**: Uses difflib to find similar strings
- **Helpful Suggestions**: Shows "Did you mean...?" with closest matches
- **Available Options**: Lists available protocols/methods when no close match found
- **Central Error Integration**: All errors use Gleitzeit's `ErrorCode` system

### Error Classes

#### `ProtocolNotFoundError`

Raised when a protocol is not found in the registry.

```python
# User types:
task = t("analyze", "olama/v1:generate")  # Typo: "olama" instead of "ollama"

# Error message:
"""
Protocol 'olama/v1' not found for task 'analyze'

Did you mean: 'ollama/v1'?
"""
```

**Error Code:** `ErrorCode.PROTOCOL_NOT_FOUND` (-30001)

---

#### `MethodNotFoundError`

Raised when a method is not found for a protocol.

```python
# User types:
task = t("analyze", "ollama/v1:generete")  # Typo: "generete" instead of "generate"

# Error message:
"""
Method 'ollama/generete' not found in protocol 'ollama/v1' for task 'analyze'

Did you mean: 'ollama/generate'?
"""
```

**Error Code:** `ErrorCode.METHOD_NOT_SUPPORTED` (-30008)

---

#### `ParameterSuggestionError`

Raised when a parameter issue is detected with suggestions.

```python
# User types:
task = t("analyze", "ollama/v1:generate").with_(
    promt="Analyze this"  # Typo: "promt" instead of "prompt"
)

# Error message:
"""
Parameter 'promt' is invalid for task 'analyze' (protocol: ollama/v1, method: ollama/generate)

Did you mean: 'prompt'?
"""
```

**Error Code:** `ErrorCode.TASK_PARAMETER_ERROR` (-29006)

---

### Helper Functions

#### `find_closest_matches(target: str, candidates: List[str], n: int = 3, cutoff: float = 0.6) -> List[str]`

Find closest matches to target string from list of candidates.

```python
from gleitzeit.easy.errors import find_closest_matches

candidates = ["python/v1", "ollama/v1", "http/v1"]
matches = find_closest_matches("pyton/v1", candidates)
# Returns: ["python/v1"]
```

**Parameters:**
- `target`: Target string to match
- `candidates`: List of candidate strings
- `n`: Maximum number of matches to return (default: 3)
- `cutoff`: Similarity threshold 0-1 (default: 0.6)

**Returns:** List of closest matching strings

---

#### `format_suggestion(message: str, suggestions: List[str]) -> str`

Format error message with suggestions.

```python
from gleitzeit.easy.errors import format_suggestion

message = "Protocol 'olama/v1' not found"
suggestions = ["ollama/v1"]
formatted = format_suggestion(message, suggestions)
# Returns: "Protocol 'olama/v1' not found\n\nDid you mean: 'ollama/v1'?"
```

---

### Protocol Registry Enhancements

The `ProtocolRegistry` now has a `validate_with_suggestions()` method:

```python
from gleitzeit.easy.protocol_registry import get_registry

registry = get_registry()

# Validate with helpful suggestions
is_valid, error = registry.validate_with_suggestions(
    protocol="olama/v1",  # Typo
    method="ollama/generate",
    task_id="my_task"
)

if not is_valid:
    raise error  # ProtocolNotFoundError with suggestions
```

---

## Central Error System Integration

### Overview

All Easy Client errors now properly inherit from Gleitzeit's central error system, ensuring consistency across the entire platform.

### Error Hierarchy

```
GleitzeitError (base)
├── TaskError
│   └── TaskBuilderError (Easy Client)
│       ├── InvalidProtocolFormatError
│       ├── InvalidParameterError
│       ├── InvalidConfigurationError
│       ├── InvalidEventTypeError
│       └── ParameterSuggestionError
├── WorkflowError
│   └── WorkflowBuilderError (Easy Client)
│       ├── InvalidDependencyError
│       ├── DuplicateTaskError
│       ├── CircularDependencyError
│       └── EmptyWorkflowError
└── ProtocolError
    ├── ProtocolNotFoundError (Easy Client)
    └── MethodNotFoundError (Easy Client)
```

### Error Codes

All errors use standardized `ErrorCode` constants:

| Error Class | Error Code | Value | Description |
|-------------|------------|-------|-------------|
| `ProtocolNotFoundError` | `PROTOCOL_NOT_FOUND` | -30001 | Protocol not in registry |
| `MethodNotFoundError` | `METHOD_NOT_SUPPORTED` | -30008 | Method not supported by protocol |
| `TaskBuilderError` | `TASK_VALIDATION_FAILED` | -29001 | Task validation failed |
| `WorkflowBuilderError` | `WORKFLOW_VALIDATION_FAILED` | -28001 | Workflow validation failed |
| `ParameterSuggestionError` | `TASK_PARAMETER_ERROR` | -29006 | Task parameter error |
| `CircularDependencyError` | `WORKFLOW_CIRCULAR_DEPENDENCY` | -28006 | Circular dependency detected |

### Benefits

1. **Consistent Error Handling**: All errors follow the same pattern
2. **Centralized Logging**: Errors integrate with Gleitzeit's logging system
3. **JSON-RPC Compliance**: Errors can be serialized to JSON-RPC format
4. **Structured Data**: All errors include structured data for debugging
5. **Retry Logic**: Error codes determine if errors are retryable

### Error Structure

All errors include:

```python
error = ProtocolNotFoundError(
    protocol="olama/v1",
    task_id="my_task",
    available_protocols=["python/v1", "ollama/v1", "http/v1"]
)

# Error properties
error.code          # ErrorCode.PROTOCOL_NOT_FOUND
error.message       # Human-readable message
error.data          # Structured error data
error.cause         # Original exception (if any)

# Serialization
error.to_dict()          # Dictionary representation
error.to_json_string()   # JSON string
error.to_context_dict()  # Full context with traceback
```

---

## Usage Examples

### Example 1: Validated LLM Task

```python
from gleitzeit.easy import t, w

# Define task with comprehensive validation
llm_task = t("analyze_code", "ollama/v1:generate")
    .require('prompt', 'model')                    # Required parameters
    .expect_types(
        prompt=str,
        model=str,
        temperature=(int, float),
        max_tokens=int
    )
    .expect_range('temperature', 0, 2)             # Valid range 0-2
    .expect_range('max_tokens', 1, 10000)          # Valid range 1-10000
    .with_(
        prompt="Analyze this Python code and suggest improvements",
        model="codellama",
        temperature=0.3,
        max_tokens=2000
    )
    .validate()  # Explicit validation

# Submit workflow
workflow = w(llm_task).submit()
```

### Example 2: Complex Data Pipeline

```python
from gleitzeit.easy import t, w

# Build complex ETL pipeline
workflow = w(
    # Initial data sources
    t("fetch_db", "python/v1:execute").with_(
        code="fetch_from_database()"
    ),
    t("fetch_api", "http/v1:request").with_(
        url="https://api.example.com/data"
    ),
    t("fetch_file", "python/v1:execute").with_(
        code="read_csv_file()"
    )
).aggregate("fetch_db", "fetch_api", "fetch_file",
    # Combine all sources
    aggregator=t("combine", "python/v1:execute")
        .require('code')
        .with_(code="combine_data_sources()")
).fan_out("combine",
    # Parallel transformations
    t("clean", "python/v1:execute").with_(code="clean_data()"),
    t("validate", "python/v1:execute").with_(code="validate_data()"),
    t("enrich", "python/v1:execute").with_(code="enrich_data()")
).diamond("clean",
    # Parallel analytics
    t("stats", "python/v1:execute").with_(code="calculate_stats()"),
    t("ml", "python/v1:execute").with_(code="run_ml_model()"),
    t("viz", "python/v1:execute").with_(code="create_visualizations()"),
    # Final aggregation
    aggregator=t("report", "python/v1:execute")
        .with_(code="generate_report()")
)

# Visualize the pipeline
workflow.print_dag()

# Submit and wait
result = workflow.submit_and_wait()
print(f"Workflow completed: {result['status']}")
```

### Example 3: Error Handling with Suggestions

```python
from gleitzeit.easy import t, w
from gleitzeit.easy.errors import ProtocolNotFoundError

try:
    # Intentional typo
    task = t("analyze", "olama/v1:generete")  # Two typos!
        .with_(promt="Analyze this")  # Typo in parameter

    workflow = w(task).submit()

except ProtocolNotFoundError as e:
    print(f"Error: {e}")
    print(f"Code: {e.code}")
    print(f"Suggestions: {e.data['suggestions']}")
    # Output:
    # Error: Protocol 'olama/v1' not found for task 'analyze'
    #
    # Did you mean: 'ollama/v1'?
    # Code: ErrorCode.PROTOCOL_NOT_FOUND
    # Suggestions: ['ollama/v1']
```

### Example 4: Dynamic Parameter Resolution

```python
from gleitzeit.easy import t, w

# Tasks with runtime-resolved parameters
workflow = w(
    # First task produces data
    t("fetch", "http/v1:request")
        .with_(url="https://api.example.com/data"),

    # Second task uses first task's output
    t("process", "python/v1:execute")
        .require('code', 'input')                  # Mark as required
        .expect_types(code=str)                    # Validate type
        .with_(
            code="process_data(input)",
            input="${fetch.result.data}"           # Runtime resolved - skipped during validation
        )
        .needs("fetch")
        .validate(),  # Validation passes because ${...} is skipped

    # Third task uses processed data
    t("analyze", "ollama/v1:generate")
        .require('prompt')
        .with_(
            prompt="Analyze this data: ${process.result}"  # Runtime resolved
        )
        .needs("process")
        .validate()
)

workflow.submit()
```

---

## Migration Guide

### Backward Compatibility

**All existing code continues to work unchanged.** The enhancements are 100% opt-in.

```python
# This code still works exactly as before
from gleitzeit.easy import t, w

workflow = w(
    t("task1", "python/v1:execute").with_(code="print('hello')"),
    t("task2", "ollama/v1:generate").with_(prompt="Say hello")
).submit()
```

### Gradual Adoption

You can adopt enhancements incrementally:

#### Stage 1: Use DAG Pattern Helpers

```python
# Before
workflow = w(
    t("task1", "python/v1:execute"),
    t("task2", "python/v1:execute").needs("task1"),
    t("task3", "python/v1:execute").needs("task2")
)

# After - clearer intent
workflow = w().pipeline(
    t("task1", "python/v1:execute"),
    t("task2", "python/v1:execute"),
    t("task3", "python/v1:execute")
)
```

#### Stage 2: Add Validation for Critical Tasks

```python
# Add validation to tasks with strict requirements
critical_task = t("analyze", "ollama/v1:generate")
    .require('prompt', 'model')  # NEW: Validation
    .expect_range('temperature', 0, 2)
    .with_(prompt="...", model="llama2", temperature=0.7)
    .validate()
```

#### Stage 3: Enable Auto-validation

```python
# Enable for all tasks in a workflow
workflow = w(
    t("task1", "python/v1:execute")
        .require('code')
        .auto_validate()
        .with_(code="..."),

    t("task2", "ollama/v1:generate")
        .require('prompt')
        .auto_validate()
        .with_(prompt="...")
)
# Validation happens automatically on submit
```

### Best Practices

1. **Use `.require()` for critical parameters**
   ```python
   .require('prompt', 'model')  # Always validate critical params
   ```

2. **Use `.expect_types()` for type safety**
   ```python
   .expect_types(temperature=(int, float), max_tokens=int)
   ```

3. **Use `.expect_range()` for bounded values**
   ```python
   .expect_range('temperature', 0, 2)
   ```

4. **Use DAG helpers for clarity**
   ```python
   .fan_out(source, *consumers)  # Clearer than manual .needs()
   ```

5. **Use `.print_dag()` for debugging**
   ```python
   workflow.print_dag()  # Visualize before submitting
   ```

6. **Handle errors gracefully**
   ```python
   try:
       workflow.submit()
   except ProtocolNotFoundError as e:
       print(f"Did you mean: {e.data['suggestions']}")
   ```

---

## Implementation Details

### Files Modified

1. **`src/gleitzeit/easy/task_builder.py`**
   - Added validation framework methods
   - Added `_is_dynamic_expression()` helper
   - Updated `to_dict()` to support auto-validation

2. **`src/gleitzeit/easy/workflow_builder.py`**
   - Added DAG pattern helpers
   - Added `.print_dag()` visualization

3. **`src/gleitzeit/easy/errors.py`**
   - Integrated with central error system
   - Added fuzzy matching helpers
   - Added enhanced error classes

4. **`src/gleitzeit/easy/protocol_registry.py`**
   - Added `.validate_with_suggestions()`
   - Added `.get_available_protocols()`
   - Added `.get_available_methods()`

### Dependencies

- **difflib**: Python standard library (fuzzy matching)
- **typing**: Python standard library (type hints)
- **Central error system**: `src/gleitzeit/core/errors.py`

### Performance Impact

- **Validation**: Negligible (only on workflow build, not execution)
- **Error messages**: Minimal (only on error paths)
- **DAG helpers**: None (just syntactic sugar)

---

## Future Enhancements

Potential future additions (not yet implemented):

1. **Handler Schema Integration**
   - Auto-populate validation rules from handler schemas
   - IDE autocomplete from handler documentation

2. **CLI Documentation Command**
   - `gleitzeit docs <protocol>` to show handler documentation
   - Interactive protocol/method browser

3. **Workflow Templates**
   - Pre-built templates for common patterns
   - Template sharing and discovery

4. **Enhanced Visualization**
   - Graphical DAG rendering
   - Export to DOT/Graphviz format

---

## Summary

The Easy Client enhancements provide:

✅ **Runtime validation** - Catch errors early while preserving flexibility
✅ **DAG pattern helpers** - Express intent clearly with common patterns
✅ **Better error messages** - Get helpful suggestions when things go wrong
✅ **Central error integration** - Consistent error handling across Gleitzeit
✅ **100% backward compatible** - All existing code works unchanged
✅ **Opt-in adoption** - Use enhancements when beneficial

These enhancements make the Easy Client more robust, maintainable, and user-friendly while maintaining the flexibility that makes Gleitzeit powerful.
