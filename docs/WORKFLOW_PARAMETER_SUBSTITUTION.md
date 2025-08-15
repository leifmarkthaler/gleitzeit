# Workflow Parameter Substitution Guide

## Overview

Parameter substitution is a powerful feature in Gleitzeit V4 that allows tasks to reference and use results from previous tasks in a workflow. This enables complex, data-driven workflows where each task builds upon the results of earlier tasks.

## Table of Contents

1. [Basic Syntax](#basic-syntax)
2. [How It Works](#how-it-works)
3. [Substitution Patterns](#substitution-patterns)
4. [Working with Different Data Types](#working-with-different-data-types)
5. [Debugging Parameter Substitution](#debugging-parameter-substitution)
6. [Best Practices](#best-practices)
7. [Common Issues and Solutions](#common-issues-and-solutions)

## Basic Syntax

### Simple Reference

The basic syntax for parameter substitution is:

```yaml
${task_id.field_name}
```

- `task_id`: The ID of a previously executed task
- `field_name`: The field in that task's result to reference

### Example

```yaml
tasks:
  - id: "get_topic"
    method: "llm/chat"
    parameters:
      messages:
        - role: "user"
          content: "Generate a random topic for an article"
  
  - id: "write_article"
    method: "llm/chat"
    dependencies: ["get_topic"]
    parameters:
      messages:
        - role: "user"
          content: "Write an article about: ${get_topic.response}"
```

## How It Works

### 1. Task Execution and Result Storage

When a task completes, its result is stored as a `TaskResult` object:

```python
TaskResult:
  task_id: "get_topic"
  status: "completed"
  result: {
    "response": "The Future of Renewable Energy",
    "model": "llama3.2",
    "tokens_used": 15
  }
```

### 2. Dependency Resolution

Before executing a dependent task, the engine:
1. Identifies all parameter substitution patterns (`${...}`)
2. Resolves each reference to its actual value
3. Replaces the pattern with the resolved value

### 3. Field Navigation

The engine navigates to the requested field:
- Starts with the `TaskResult` object
- Automatically accesses the `result` field
- Then navigates to the requested field (e.g., `response`)

### Execution Flow

```
1. Task A executes → Returns {"response": "Hello"}
2. Task A result stored as TaskResult(result={"response": "Hello"})
3. Task B references ${A.response}
4. Engine retrieves TaskResult for A
5. Engine accesses TaskResult.result.response
6. Engine substitutes "Hello" into Task B's parameters
7. Task B executes with substituted value
```

## Substitution Patterns

### Simple Field Access

Access top-level fields in the result:

```yaml
# If task returns: {"response": "text", "score": 0.95}
${task_id.response}  # → "text"
${task_id.score}     # → 0.95
```

### Nested Field Access

Access nested fields using dot notation:

```yaml
# If task returns: {"data": {"user": {"name": "John"}}}
${task_id.data.user.name}  # → "John"
```

### Array Index Access

Access array elements by index:

```yaml
# If task returns: {"items": ["first", "second", "third"]}
${task_id.items[0]}  # → "first"
${task_id.items[2]}  # → "third"
```

### Complex Navigation

Combine different access patterns:

```yaml
# If task returns: {"users": [{"name": "Alice", "age": 30}]}
${task_id.users[0].name}  # → "Alice"
```

### Multiple Substitutions

Use multiple substitutions in a single parameter:

```yaml
parameters:
  prompt: "Compare ${task1.response} with ${task2.response}"
```

### Substitution in Different Parameter Types

#### In Strings

```yaml
parameters:
  message: "The result was: ${previous_task.response}"
```

#### In Arrays

```yaml
parameters:
  items:
    - "First: ${task1.response}"
    - "Second: ${task2.response}"
```

#### In Nested Objects

```yaml
parameters:
  config:
    title: "${generate_title.response}"
    content: "${generate_content.response}"
    metadata:
      author: "${get_author.response}"
```

## Working with Different Data Types

### String Results

Most common for LLM providers:

```yaml
# Provider returns: {"response": "Generated text"}
content: "${task.response}"
```

### Numeric Results

```yaml
# Provider returns: {"result": 42}
threshold: ${calculate_threshold.result}
```

### Boolean Results

```yaml
# Provider returns: {"result": true}
enabled: ${check_feature.result}
```

### Array Results

```yaml
# Provider returns: {"items": ["a", "b", "c"]}
first_item: "${get_list.items[0]}"
all_items: ${get_list.items}  # Entire array
```

### Object Results

```yaml
# Provider returns: {"config": {"host": "localhost", "port": 8080}}
connection:
  host: "${get_config.config.host}"
  port: ${get_config.config.port}
```

## Debugging Parameter Substitution

### Enable Debug Logging

Set logging level to DEBUG to see substitution details:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Common Debug Messages

```
DEBUG: Looking for task generate_topic in results
DEBUG: Substituting ${generate_topic.response} with "The Future of AI"
WARNING: Field response not found in task generate_topic result
```

### Checking Available Fields

If substitution fails, the engine logs available fields:

```
WARNING: Field response not found in task generate_topic result
WARNING:   Available fields in ref_value: ['content', 'model', 'tokens_used']
```

This indicates the provider returned `content` instead of `response`.

## Best Practices

### 1. Use Consistent Field Names

Ensure providers return standard field names:
- LLM providers: Use `"response"` for generated text
- Python providers: Use `"result"` for execution results

### 2. Add Dependencies Explicitly

Always declare task dependencies when using substitution:

```yaml
tasks:
  - id: "task_a"
    method: "some/method"
  
  - id: "task_b"
    dependencies: ["task_a"]  # Required!
    parameters:
      value: "${task_a.response}"
```

### 3. Handle Missing Fields Gracefully

Consider what happens if a field doesn't exist:

```yaml
# Use conditional logic in your prompts
prompt: |
  Process this data: ${data_task.response}
  If no data was provided, use default processing.
```

### 4. Validate Results Before Substitution

For critical workflows, add validation tasks:

```yaml
tasks:
  - id: "generate_data"
    method: "llm/generate"
    
  - id: "validate_data"
    method: "python/execute"
    dependencies: ["generate_data"]
    parameters:
      code: |
        data = "${generate_data.response}"
        assert len(data) > 0, "Generated data is empty"
        result = "valid"
```

### 5. Use Meaningful Task IDs

Choose descriptive task IDs for clarity:

```yaml
# Good
${generate_article_title.response}
${calculate_word_count.result}

# Bad
${task1.response}
${t2.result}
```

## Common Issues and Solutions

### Issue 1: "Field not found" Warning

**Problem**: 
```
WARNING: Field response not found in task generate_topic result
```

**Cause**: Provider returns different field name than expected.

**Solution**: 
1. Check what fields the provider actually returns
2. Update provider to return standard fields
3. Or update workflow to use correct field name

### Issue 2: Substitution Not Happening

**Problem**: The literal `${task.field}` appears in the output.

**Cause**: Missing dependency declaration.

**Solution**: Add the referenced task to dependencies:
```yaml
dependencies: ["referenced_task_id"]
```

### Issue 3: Wrong Value Substituted

**Problem**: Substituted value doesn't match expected result.

**Cause**: Navigation path incorrect or result structure different.

**Solution**: 
1. Log the task result structure
2. Verify the navigation path
3. Check for typos in field names

### Issue 4: Type Mismatch

**Problem**: Substituted value has wrong type (e.g., object instead of string).

**Cause**: Accessing wrong level of nested structure.

**Solution**: Adjust navigation path:
```yaml
# Wrong: Returns entire object
${task.data}

# Right: Returns specific field
${task.data.value}
```

### Issue 5: Circular Dependencies

**Problem**: Tasks reference each other in a cycle.

**Cause**: Incorrect dependency configuration.

**Solution**: Restructure workflow to eliminate cycles:
```yaml
# Wrong: Circular dependency
- id: "task_a"
  dependencies: ["task_b"]
  
- id: "task_b"
  dependencies: ["task_a"]

# Right: Linear dependency
- id: "task_a"
  
- id: "task_b"
  dependencies: ["task_a"]
```

## Advanced Examples

### Chain of Reasoning

```yaml
tasks:
  - id: "identify_problem"
    method: "llm/chat"
    parameters:
      messages:
        - role: "user"
          content: "What is the main challenge in renewable energy adoption?"
  
  - id: "analyze_causes"
    method: "llm/chat"
    dependencies: ["identify_problem"]
    parameters:
      messages:
        - role: "user"
          content: "What are the root causes of: ${identify_problem.response}"
  
  - id: "propose_solutions"
    method: "llm/chat"
    dependencies: ["identify_problem", "analyze_causes"]
    parameters:
      messages:
        - role: "user"
          content: |
            Problem: ${identify_problem.response}
            Causes: ${analyze_causes.response}
            
            Propose three innovative solutions.
```

### Data Processing Pipeline

```yaml
tasks:
  - id: "fetch_data"
    method: "python/execute"
    parameters:
      code: |
        import json
        result = {"data": [1, 2, 3, 4, 5], "metadata": {"source": "test"}}
  
  - id: "process_data"
    method: "python/execute"
    dependencies: ["fetch_data"]
    parameters:
      code: |
        data = ${fetch_data.data}
        result = sum(data) / len(data)
  
  - id: "generate_report"
    method: "llm/chat"
    dependencies: ["fetch_data", "process_data"]
    parameters:
      messages:
        - role: "user"
          content: |
            Generate a report:
            - Data source: ${fetch_data.metadata.source}
            - Average value: ${process_data.result}
            - Data points: ${fetch_data.data}
```

### Conditional Workflow

```yaml
tasks:
  - id: "check_condition"
    method: "python/execute"
    parameters:
      code: |
        import random
        result = random.choice(["option_a", "option_b"])
  
  - id: "process_result"
    method: "llm/chat"
    dependencies: ["check_condition"]
    parameters:
      messages:
        - role: "user"
          content: |
            The selected option was: ${check_condition.result}
            
            If option_a: Explain benefits of solar energy
            If option_b: Explain benefits of wind energy
```

## Conclusion

Parameter substitution is a core feature that enables powerful, dynamic workflows in Gleitzeit V4. By following the patterns and best practices in this guide, you can create complex workflows that intelligently chain tasks together.

Key takeaways:
1. Always declare dependencies when using substitution
2. Ensure providers return standard field names
3. Use clear, descriptive task IDs
4. Test workflows incrementally
5. Enable debug logging when troubleshooting

For more information, see:
- [PROVIDER_IMPLEMENTATION_GUIDE.md](./PROVIDER_IMPLEMENTATION_GUIDE.md)
- [GLEITZEIT_V4_ARCHITECTURE.md](./GLEITZEIT_V4_ARCHITECTURE.md)