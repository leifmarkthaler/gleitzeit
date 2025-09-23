# Validation Handler Documentation

## Overview

The ValidationHandler enables conditional task execution in Gleitzeit workflows through validation tasks. These tasks evaluate conditions and control whether downstream tasks should execute, skip, or fail.

## Core Concepts

### Validation as a Task

Validation is implemented as a first-class task type, not a field or property. This means:
- Validation logic is visible in the workflow
- Validation execution is tracked and observable
- Validation results can be cached and reused
- Validations can have their own dependencies

### Convention-Based Behavior

Tasks that depend on `validation/v1` protocol tasks automatically respect validation results:
- If validation returns `valid: false` → dependent task is skipped (default)
- If validation returns `valid: true` → dependent task proceeds normally
- Override behavior with `validation_behavior` field on dependent task

## Protocol Definition

**Protocol:** `validation/v1`

### Methods

#### `validation/evaluate`

Evaluates one or more conditions and returns a validation result.

**Parameters:**
- `conditions` (list): Conditions to evaluate
  - `expression` (string): Expression to evaluate
  - `name` (string): Descriptive name for the condition
- `mode` (string): How to combine conditions
  - `"all"`: All conditions must pass (AND)
  - `"any"`: At least one condition must pass (OR)
  - `"none"`: No conditions should pass (NOT ANY)
  - `"custom"`: Custom evaluation logic
- `context` (dict): Variables available to expressions
- `on_failure` (string): What happens when validation fails
  - `"skip"`: Skip dependent tasks (default)
  - `"fail"`: Fail dependent tasks
  - `"continue"`: Allow dependent tasks to proceed

**Returns:**
```json
{
  "valid": true/false,
  "mode": "all",
  "on_failure": "skip",
  "summary": {
    "total": 3,
    "passed": 2,
    "failed": 1
  },
  "details": [
    {
      "name": "threshold_check",
      "expression": "value > 100",
      "result": true,
      "evaluated": true
    }
  ],
  "evaluated_at": "2024-01-19T16:54:23.328498"
}
```

#### `validation/assert`

Stricter validation that fails the task if any assertion is false.

**Parameters:**
- `assertions` (list): Assertions that must all be true
  - `expression` (string): Expression that must evaluate to true
  - `name` (string): Descriptive name
- `context` (dict): Variables available to expressions

**Returns:**
- On success: Similar to evaluate with `valid: true`
- On failure: Task fails with error message

#### `validation/gate`

Controls multiple downstream tasks based on rules.

**Parameters:**
- `rules` (list): Gating rules to evaluate
  - `name` (string): Rule name
  - `condition` (string): Condition expression
  - `enable_tasks` (list): Task names to enable if condition is true
  - `disable_tasks` (list): Task names to disable if condition is true
- `context` (dict): Variables available to expressions

**Returns:**
```json
{
  "valid": true,
  "gate_results": [...],
  "control": {
    "enable_tasks": ["premium_process"],
    "skip_tasks": ["standard_process"]
  }
}
```

## Expression Language

The ValidationHandler uses SimpleEval for safe expression evaluation.

### Supported Operations

**Comparisons:**
- `==`, `!=`, `>`, `<`, `>=`, `<=`
- `is`, `is not`

**Logical:**
- `and`, `or`, `not`

**Membership:**
- `in`, `not in`

**Built-in Functions:**
- `len()`, `abs()`, `min()`, `max()`
- `round()`, `str()`, `int()`, `float()`, `bool()`

### Examples

```python
# Simple comparisons
"value > 100"
"status == 'active'"
"count >= min_threshold"

# Logical combinations
"value > 100 and status == 'active'"
"count < 10 or override == True"

# Membership tests
"role in ['admin', 'manager']"
"status not in ['failed', 'cancelled']"

# Null checks
"data is not None"
"error is None"

# Complex expressions
"(total > 1000 or priority == 'high') and status == 'pending'"
```

## Workflow Examples

### Basic Validation

```yaml
tasks:
  - name: fetch_data
    protocol: http/v1
    method: get
    params:
      url: "https://api.example.com/data"

  - name: validate_response
    protocol: validation/v1
    method: validation/evaluate
    dependencies: [fetch_data]
    params:
      conditions:
        - expression: "status_code == 200"
          name: "success_response"
        - expression: "len(items) > 0"
          name: "has_data"
      mode: "all"
      context:
        status_code: "${fetch_data.status_code}"
        items: "${fetch_data.result.items}"

  - name: process_data
    protocol: python/v1
    dependencies: [validate_response]
    # Automatically skipped if validation fails
```

### Multiple Validations

```yaml
tasks:
  - name: get_order
    protocol: python/v1
    method: python/execute
    params:
      code: |
        result = {
          'total': 1500,
          'items': 5,
          'customer_type': 'premium'
        }

  - name: validate_order_size
    protocol: validation/v1
    method: validation/evaluate
    dependencies: [get_order]
    params:
      conditions:
        - expression: "total > 1000"
          name: "large_order"
      context:
        total: "${get_order.total}"

  - name: validate_customer
    protocol: validation/v1
    method: validation/evaluate
    dependencies: [get_order]
    params:
      conditions:
        - expression: "customer_type == 'premium'"
          name: "premium_customer"
      context:
        customer_type: "${get_order.customer_type}"

  - name: apply_special_processing
    protocol: python/v1
    dependencies: [validate_order_size, validate_customer]
    # Only runs if BOTH validations pass
```

### Validation with Override

```yaml
tasks:
  - name: check_conditions
    protocol: validation/v1
    method: validation/evaluate
    params:
      conditions:
        - expression: "risk_score < 50"
      context:
        risk_score: 75

  - name: process_anyway
    protocol: python/v1
    dependencies: [check_conditions]
    validation_behavior: "continue"  # Run even if validation fails
    params:
      code: |
        print("Processing with elevated risk")
```

### Assertions for Critical Checks

```yaml
tasks:
  - name: assert_prerequisites
    protocol: validation/v1
    method: validation/assert
    params:
      assertions:
        - expression: "api_key is not None"
          name: "api_key_present"
        - expression: "len(api_key) == 32"
          name: "api_key_valid_length"
      context:
        api_key: "${config.api_key}"

  - name: call_external_api
    protocol: http/v1
    dependencies: [assert_prerequisites]
    # Task only runs if ALL assertions pass
    # Workflow fails if any assertion fails
```

### Gating for Branch Control

```yaml
tasks:
  - name: calculate_total
    protocol: python/v1
    method: python/execute
    params:
      code: |
        result = {'total': 2500}

  - name: routing_gate
    protocol: validation/v1
    method: validation/gate
    dependencies: [calculate_total]
    params:
      rules:
        - name: "high_value_route"
          condition: "total > 2000"
          enable_tasks: ["premium_shipping", "gift_wrap"]
          disable_tasks: ["standard_shipping"]

        - name: "standard_route"
          condition: "total <= 2000"
          enable_tasks: ["standard_shipping"]
          disable_tasks: ["premium_shipping", "gift_wrap"]
      context:
        total: "${calculate_total.total}"

  - name: premium_shipping
    protocol: python/v1
    dependencies: [routing_gate]
    # Only runs if total > 2000

  - name: standard_shipping
    protocol: python/v1
    dependencies: [routing_gate]
    # Only runs if total <= 2000

  - name: gift_wrap
    protocol: python/v1
    dependencies: [routing_gate]
    # Only runs if total > 2000
```

## Task Status Flow

When validation tasks control execution:

```
1. Validation task: PENDING → EXECUTING → COMPLETED
   - Returns: {valid: true/false, ...}

2. Dependent task checks validation:
   - If valid=true → PENDING → EXECUTING → COMPLETED
   - If valid=false & on_failure="skip" → SKIPPED
   - If valid=false & on_failure="fail" → FAILED
   - If valid=false & on_failure="continue" → PENDING → EXECUTING
```

## Integration with DependencyWorker

The DependencyWorker automatically checks validation results:

1. When resolving dependencies, identifies `validation/v1` protocol tasks
2. Checks the validation result (`valid` field)
3. Applies the appropriate behavior based on `on_failure` setting
4. Updates task status accordingly (SKIPPED, FAILED, or proceed)

## Best Practices

### 1. Use Descriptive Names

```yaml
conditions:
  - expression: "value > 1000"
    name: "order_exceeds_minimum"  # Good
  # vs
  - expression: "value > 1000"
    name: "check1"  # Bad
```

### 2. Group Related Validations

```yaml
# Single validation task for related checks
- name: validate_order
  params:
    conditions:
      - name: "has_items"
        expression: "item_count > 0"
      - name: "valid_total"
        expression: "total > 0"
      - name: "currency_supported"
        expression: "currency in ['USD', 'EUR']"
```

### 3. Use Appropriate Methods

- **evaluate**: For conditional flow control
- **assert**: For critical prerequisites that must pass
- **gate**: For routing between multiple paths

### 4. Provide Clear Context

```yaml
context:
  # Explicit context makes debugging easier
  order_total: "${fetch_order.result.total}"
  customer_type: "${fetch_customer.result.type}"
  # Instead of passing entire objects
  # order: "${fetch_order.result}"  # Less clear
```

### 5. Handle None Values

```yaml
conditions:
  # Safe None handling
  - expression: "value is not None and value > 100"
  # Or with defaults
  - expression: "(value or 0) > 100"
```

## Error Handling

### Variable Not Found

If a variable in an expression isn't in the context:
```yaml
conditions:
  - expression: "undefined_var > 100"
# Result: NameNotDefined error, condition evaluates to false
```

### Invalid Expression Syntax

```yaml
conditions:
  - expression: "value >>> 100"  # Invalid operator
# Result: Syntax error, condition evaluates to false
```

### Type Errors

```yaml
conditions:
  - expression: "text_value > 100"  # Comparing string to number
context:
  text_value: "hello"
# Result: TypeError, condition evaluates to false
```

## Performance Considerations

1. **Validation Caching**: Results are stored in Redis and not re-evaluated
2. **Parallel Validation**: Multiple validation tasks can run in parallel
3. **Early Exit**: Failed assertions stop immediately
4. **Minimal Overhead**: SimpleEval is lightweight and fast

## Data Persistence

### Expression Storage

All validation expressions are fully preserved in multiple locations:

1. **Workflow Definition**: Complete workflow with all expressions stored in Redis
2. **Task Streams**: Full task definitions in `task:ready` messages
3. **Validation Results**: Original expressions included in results

This ensures:
- **Auditability**: Can trace what conditions were evaluated
- **Debugging**: Can examine exact expressions that caused decisions
- **Replay**: Can re-run workflows with identical logic
- **Compliance**: Full audit trail for regulatory requirements

### Retrieving Persisted Expressions

```python
# From workflow definition
workflow_key = f"{shard}:workflow:data:{workflow_id}"
workflow_data = redis.hget(workflow_key, "workflow")
workflow = json.loads(workflow_data)

# From task results
task_key = f"{shard}:task:{task_id}"
result = json.loads(redis.hget(task_key, "result"))
for detail in result['details']:
    print(f"Expression: {detail['expression']}")
    print(f"Result: {detail['result']}")
```

## Debugging

### Enable Debug Logging

```python
import logging
logging.getLogger('gleitzeit.handlers.validation').setLevel(logging.DEBUG)
```

### Check Validation Results

Validation results are stored in Redis:
```
Key: {shard}:task:{task_id}
Field: result
```

### Common Issues

1. **Expression returns None**: Check for None values in context
2. **All tasks skipped**: Verify validation logic and context values
3. **Unexpected skips**: Check `on_failure` settings and `validation_behavior`

## Migration Guide

### From Conditional Fields

Before:
```yaml
- name: process_data
  condition: "${previous.result} > 100"
```

After:
```yaml
- name: validate_threshold
  protocol: validation/v1
  method: validation/evaluate
  dependencies: [previous]
  params:
    conditions:
      - expression: "result > 100"
    context:
      result: "${previous.result}"

- name: process_data
  dependencies: [validate_threshold]
```

### From Custom Logic

Before (in Python handler):
```python
if data['total'] > 1000 and data['status'] == 'active':
    # process
else:
    # skip
```

After:
```yaml
- name: validate_conditions
  protocol: validation/v1
  method: validation/evaluate
  params:
    conditions:
      - expression: "total > 1000"
      - expression: "status == 'active'"
    mode: "all"

- name: process_data
  dependencies: [validate_conditions]
```

## FAQ

**Q: Can validation tasks have dependencies?**
A: Yes, validation tasks are normal tasks and can depend on other tasks for their input data.

**Q: What happens if validation task itself fails?**
A: If a validation task fails (not returns valid=false, but actually fails), dependent tasks are blocked and the workflow may fail.

**Q: Can I have multiple validation dependencies?**
A: Yes, a task can depend on multiple validation tasks. All must pass for the task to run (unless using `validation_behavior: continue`).

**Q: How do I test validation logic?**
A: Use the test script in `test_validation_flow.py` or write unit tests for your validation expressions.

**Q: Can validation tasks be retried?**
A: Yes, validation tasks can be retried like any other task if they fail (not if they return valid=false).