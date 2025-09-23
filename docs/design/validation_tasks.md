# Validation Tasks Design for Conditional Execution

## Overview

Instead of adding condition fields to tasks, this design treats conditions as first-class validation tasks that control the execution flow. This approach maintains Gleitzeit's "everything is a task" philosophy while enabling powerful conditional workflows.

## Core Concept: Validation as a Task

### The Validation Task Model

```yaml
workflow:
  name: Conditional Workflow with Validation
  tasks:
    # Validation task - determines if subsequent tasks should run
    - id: validate_conditions
      name: Check Processing Requirements
      protocol: validation/v1
      method: validation/evaluate
      params:
        conditions:
          - expression: "${data.size} > 1000"
            name: "data_size_check"
          - expression: "${user.subscription} == 'premium'"
            name: "subscription_check"
        mode: "all"  # all, any, custom
        
    # Regular task that depends on validation
    - id: process_data
      dependencies: [validate_conditions]
      protocol: python/v1
      method: python/execute
      params:
        code: "# Process large dataset"
```

## Validation Task Protocol

### Validation Handler

```yaml
protocol: validation/v1
methods:
  validation/evaluate:
    description: Evaluate conditions and control flow
    params:
      conditions: List of conditions to evaluate
      mode: How to combine conditions (all/any/custom)
      on_failure: What to do when validation fails
    returns:
      valid: boolean
      results: Individual condition results
      
  validation/assert:
    description: Assert conditions (fail workflow if false)
    params:
      assertions: List of assertions
      
  validation/gate:
    description: Gate keeper for workflow branches
    params:
      rules: Gating rules
      branches: Named branches to enable/disable
```

## Where Validation Code Actually Runs

### Execution Location

The validation code runs in a **ValidationHandler** that executes within the **TaskExecutionWorker**, just like any other handler (Ollama, Python, etc.):

```
1. DependencyWorker resolves dependencies and marks validation task as READY
2. TaskExecutionWorker picks up the validation task from Redis stream
3. ValidationHandler (inside TaskExecutionWorker) executes the validation logic
4. Validation result goes back to Redis
5. DependencyWorker checks validation results before marking dependent tasks as READY
```

### Architecture Design

#### 1. Validation Handler Implementation

The ValidationHandler runs **inside the TaskExecutionWorker** process:

```python
# This runs in TaskExecutionWorker, just like OllamaHandler or PythonHandler
@HandlerRegistry.register
class ValidationHandler(BaseHandler):
    """
    Handler for validation tasks that control workflow execution.
    Executes within TaskExecutionWorker like any other handler.
    """

    async def execute(self, task: Task) -> TaskResult:
        """This method runs in the TaskExecutionWorker process"""

        if task.method == 'validation/evaluate':
            # The actual validation logic runs HERE, in the worker process
            return await self._evaluate_conditions(task)
        elif task.method == 'validation/assert':
            return await self._assert_conditions(task)
        elif task.method == 'validation/gate':
            return await self._gate_workflow(task)

    async def _evaluate_conditions(self, task: Task) -> TaskResult:
        """
        This runs in the TaskExecutionWorker process.
        Evaluates conditions using Python code, not external services.
        """
        conditions = task.params.get('conditions', [])
        mode = task.params.get('mode', 'all')  # all, any, custom

        results = []
        for condition in conditions:
            # Parse and evaluate expression safely (no exec/eval)
            # This happens in the worker's Python process
            result = await self._safe_evaluate(
                condition['expression'],
                task.params.get('context', {})
            )
            results.append(result)

        # Determine overall validation result
        if mode == 'all':
            valid = all(results)
        elif mode == 'any':
            valid = any(results)
        else:
            # Custom logic
            valid = self._custom_evaluation(results, task.params)

        return TaskResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            result={
                'valid': valid,
                'results': results,
                'evaluated_at': datetime.utcnow()
            }
        )

    async def _safe_evaluate(self, expression: str, context: Dict) -> bool:
        """
        Safely evaluates expressions without exec/eval.
        Runs in the worker process, not external.
        """
        # Use AST parsing or a safe expression evaluator
        # This is pure Python code running in the worker
        import ast
        import operator

        # Safe operators mapping
        ops = {
            ast.Eq: operator.eq,
            ast.NotEq: operator.ne,
            ast.Lt: operator.lt,
            ast.LtE: operator.le,
            ast.Gt: operator.gt,
            ast.GtE: operator.ge,
            ast.And: operator.and_,
            ast.Or: operator.or_,
        }

        # Parse and evaluate safely
        # ... AST evaluation logic ...
        return result
```

#### 2. Execution Flow Diagram

```
┌─────────────────┐
│   Redis Stream  │
│  task:ready     │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│     TaskExecutionWorker         │
│  ┌───────────────────────────┐  │
│  │  Handler Selection Logic  │  │
│  └─────────┬─────────────────┘  │
│            │                     │
│            ▼                     │
│  ┌───────────────────────────┐  │
│  │   ValidationHandler       │  │ ◄── Validation code runs HERE
│  │   ├── _evaluate()         │  │     in the worker process
│  │   ├── _assert()           │  │     using Python, not external
│  │   └── _gate()             │  │     services
│  └─────────┬─────────────────┘  │
└────────────┬────────────────────┘
             │
             ▼
      ┌──────────────┐
      │ Redis Result │
      │   Storage    │
      └──────────────┘
```

### 2. Flow Control Mechanisms

#### Option A: Validation Result Controls Dependencies

Tasks check their validation dependencies:

```python
# In DependencyWorker
if dependency_task.protocol == 'validation/v1':
    if not dependency_result.get('valid', False):
        # Mark dependent task as SKIPPED or BLOCKED
        return mark_task_skipped(task, reason="Validation failed")
```

#### Option B: Validation Task Emits Control Signals

Validation tasks actively control downstream tasks:

```python
# Validation task result includes control directives
return TaskResult(
    result={
        'valid': False,
        'control': {
            'skip_tasks': ['process_data', 'generate_report'],
            'fail_tasks': [],
            'enable_tasks': ['send_error_notification']
        }
    }
)
```

#### Option C: Validation as Workflow Modifier (RECOMMENDED)

Validation tasks modify workflow state in Redis:

```python
# Validation handler updates task states directly
if not all_conditions_met:
    for task_id in dependent_tasks:
        await redis.hset(
            f"task:control:{task_id}",
            mapping={
                b"should_skip": b"true",
                b"skip_reason": b"Validation failed",
                b"validated_by": validation_task_id
            }
        )
```

## Validation Patterns

### Pattern 1: Simple Gate

```yaml
tasks:
  - id: check_prerequisites
    protocol: validation/v1
    method: validation/evaluate
    params:
      conditions:
        - expression: "${config.enabled}"
        - expression: "${user.authorized}"
      mode: all
      
  - id: main_process
    dependencies: [check_prerequisites]
    # Only runs if validation passes
```

### Pattern 2: Multi-Branch Validation

```yaml
tasks:
  - id: route_validator
    protocol: validation/v1
    method: validation/gate
    params:
      rules:
        - name: "large_data_path"
          condition: "${data.size} > 10000"
          enable_tasks: [batch_processor]
          disable_tasks: [inline_processor]
          
        - name: "small_data_path"  
          condition: "${data.size} <= 10000"
          enable_tasks: [inline_processor]
          disable_tasks: [batch_processor]
          
  - id: batch_processor
    dependencies: [route_validator]
    # Runs only for large data
    
  - id: inline_processor
    dependencies: [route_validator]
    # Runs only for small data
```

### Pattern 3: Progressive Validation

```yaml
tasks:
  # First level validation
  - id: basic_validation
    protocol: validation/v1
    method: validation/assert
    params:
      assertions:
        - "${input.data} is not None"
        - "${input.format} in ['json', 'xml']"
        
  # Process if basic validation passes
  - id: parse_data
    dependencies: [basic_validation]
    
  # Second level validation
  - id: business_validation
    dependencies: [parse_data]
    protocol: validation/v1
    method: validation/evaluate
    params:
      conditions:
        - expression: "${parse_data.result.total} < ${limits.max_amount}"
        - expression: "${parse_data.result.currency} in ${allowed_currencies}"
        
  # Continue if business rules pass
  - id: process_transaction
    dependencies: [business_validation]
```

### Pattern 4: Circuit Breaker

```yaml
tasks:
  - id: circuit_breaker
    protocol: validation/v1
    method: validation/evaluate
    params:
      conditions:
        - expression: "${metrics.error_rate} < 0.1"
        - expression: "${metrics.response_time} < 5000"
      mode: all
      cache_result: true
      cache_ttl: 60  # Cache validation for 60 seconds
      
  - id: external_api_call
    dependencies: [circuit_breaker]
    # Only calls API if circuit is closed
```

## Scalability Considerations

### 1. Validation Result Caching

```python
# Cache validation results to avoid re-evaluation
cache_key = f"validation:cache:{task_id}:{input_hash}"
if cached_result := await redis.get(cache_key):
    return cached_result
```

### 2. Parallel Validation

```yaml
tasks:
  # Multiple validation tasks can run in parallel
  - id: validate_auth
    protocol: validation/v1
    
  - id: validate_quota
    protocol: validation/v1
    
  - id: validate_rate_limit
    protocol: validation/v1
    
  # Main task depends on all validations
  - id: process_request
    dependencies: [validate_auth, validate_quota, validate_rate_limit]
```

### 3. Distributed Validation

Validation tasks can be distributed across workers:

```yaml
# Worker specialization
worker_1:
  enabled_protocols: [validation/v1]  # Validation specialist
  
worker_2:
  enabled_protocols: [python/v1, http/v1]  # Execution specialist
```

## Implementation in Current Architecture

### 1. New ValidationHandler

The ValidationHandler is just another handler that gets registered and runs in TaskExecutionWorker:

```python
# This lives in src/gleitzeit/handlers/validation.py
@HandlerRegistry.register
class ValidationHandler(BaseHandler):
    """
    Runs inside TaskExecutionWorker process.
    No external service needed - pure Python validation logic.
    """

    @classmethod
    def get_capabilities(cls):
        return {
            'protocol': 'validation/v1',
            'task_types': ['validation', 'condition', 'gate'],
            'methods': {
                'validation/evaluate': {...},
                'validation/assert': {...},
                'validation/gate': {...}
            }
        }

    # The actual validation code runs here in the worker
    async def execute(self, task: Task) -> TaskResult:
        # This executes in the TaskExecutionWorker process
        # No external callout - evaluates expressions locally
        ...
```

### Worker Configuration

```yaml
# TaskExecutionWorker automatically loads ValidationHandler
worker:
  type: TaskExecutionWorker
  enabled_protocols:
    - validation/v1  # Handles validation tasks
    - python/v1      # Handles Python tasks
    - ollama/v1      # Handles Ollama tasks
```

### 2. DependencyWorker Enhancement

```python
class DependencyWorker:
    async def process_task_dependencies(self, task):
        # Check validation dependencies
        for dep_id in task.dependencies:
            dep_result = await self.get_task_result(dep_id)
            
            if dep_result.protocol == 'validation/v1':
                if not dep_result.result.get('valid', False):
                    # Check skip behavior
                    skip_behavior = dep_result.result.get('on_failure', 'skip')
                    
                    if skip_behavior == 'skip':
                        await self.mark_task_skipped(task)
                        return
                    elif skip_behavior == 'fail':
                        await self.mark_task_failed(task, "Validation failed")
                        return
                    elif skip_behavior == 'continue':
                        # Continue but mark validation state
                        task.metadata['validation_failed'] = True
```

### 3. New Task Status

```python
class TaskStatus(Enum):
    # Existing statuses...
    SKIPPED = "skipped"      # Skipped due to validation
    BLOCKED = "blocked"      # Blocked by validation gate
    GATED = "gated"         # Waiting for gate to open
```

## Advantages of Validation Tasks

1. **First-Class Citizens**: Validations are trackable, retryable tasks
2. **Composable**: Can chain and combine validations
3. **Reusable**: Validation logic in shareable handlers
4. **Observable**: Full visibility into validation execution
5. **Scalable**: Validations can be distributed and cached
6. **Testable**: Validation logic can be unit tested
7. **Versioned**: Validation handlers can evolve with versions

## Complex Workflow Example

```yaml
workflow:
  name: Order Processing with Validations
  tasks:
    # Input validation
    - id: validate_order
      protocol: validation/v1
      method: validation/assert
      params:
        assertions:
          - "${order.items} is not empty"
          - "${order.customer_id} is not None"
          
    # Check inventory
    - id: check_inventory
      dependencies: [validate_order]
      protocol: inventory/v1
      method: check_availability
      
    # Validate inventory results
    - id: validate_inventory
      dependencies: [check_inventory]
      protocol: validation/v1
      method: validation/evaluate
      params:
        conditions:
          - expression: "${check_inventory.result.all_available}"
        on_failure: "skip"
        
    # Credit check for large orders
    - id: validate_credit
      dependencies: [validate_order]
      protocol: validation/v1
      method: validation/evaluate
      params:
        conditions:
          - expression: "${order.total} < 10000 or ${customer.credit_approved}"
        on_failure: "fail"
        
    # Process payment (needs both validations)
    - id: process_payment
      dependencies: [validate_inventory, validate_credit]
      protocol: payment/v1
      method: charge
      
    # Fulfillment (only if payment succeeds)
    - id: fulfill_order
      dependencies: [process_payment]
      protocol: fulfillment/v1
      method: ship
```

## Scalability Analysis

### Performance Characteristics

1. **Overhead**: ~1-5ms per validation task
2. **Caching**: Reduces repeated validations to <1ms
3. **Parallelism**: Multiple validations run concurrently
4. **Distribution**: Validations spread across workers

### Scaling Patterns

#### Horizontal Scaling
- Add more validation workers for complex workflows
- Shard validations by workflow or domain

#### Vertical Scaling  
- Cache validation results aggressively
- Batch validation operations
- Use compiled validation rules

#### Load Balancing
- Dedicated validation worker pools
- Priority queues for critical validations
- Circuit breakers for external validations

### Performance Optimizations

1. **Early Exit**: Stop validation chain on first failure
2. **Lazy Evaluation**: Only validate when needed
3. **Result Sharing**: Share validation results across tasks
4. **Precomputation**: Pre-validate during quiet periods

## Comparison with Field-Based Conditions

| Aspect | Validation Tasks | Condition Fields |
|--------|-----------------|------------------|
| **Visibility** | Full task tracking | Hidden in task definition |
| **Reusability** | Highly reusable | Copy-paste prone |
| **Testability** | Independent testing | Integrated testing only |
| **Debugging** | Clear execution trace | Harder to debug |
| **Performance** | Slight overhead (~5ms) | Minimal overhead |
| **Complexity** | More tasks in workflow | Simpler workflow |
| **Flexibility** | Very flexible | Limited to expressions |
| **Scalability** | Independently scalable | Scales with tasks |

## Conclusion

Validation tasks provide a clean, scalable solution for conditional execution that:

1. **Maintains Architecture**: Fits perfectly with task-based model
2. **Enables Complex Logic**: Sophisticated validation patterns
3. **Provides Visibility**: Full tracking and debugging
4. **Scales Naturally**: Distributed validation execution
5. **Stays Flexible**: Easy to extend and modify

This approach treats conditions as first-class workflow citizens, making them observable, scalable, and maintainable while preserving Gleitzeit's elegant task-based architecture.