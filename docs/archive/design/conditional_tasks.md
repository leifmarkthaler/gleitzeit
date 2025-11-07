# Conditional Tasks Design for Gleitzeit

## Overview

This document outlines a design for implementing conditional task execution in Gleitzeit's current architecture. Conditional tasks enable workflows to make decisions based on runtime data, creating dynamic execution paths.

## Core Concepts

### 1. Condition Types

#### Simple Boolean Conditions
```yaml
tasks:
  - id: check_status
    protocol: python/v1
    method: python/eval
    params:
      expression: "status == 'active'"
      
  - id: send_alert
    condition: "${check_status.result}"
    protocol: email/v1
    method: send
```

#### Comparison Conditions
```yaml
tasks:
  - id: process_if_large
    condition:
      expression: "${data_size.result} > 1000"
    protocol: batch/v1
```

#### Complex Conditions
```yaml
tasks:
  - id: complex_decision
    condition:
      all_of:
        - expression: "${user.role} == 'admin'"
        - expression: "${request.priority} > 5"
        - any_of:
          - expression: "${time.hour} < 6"
          - expression: "${time.hour} > 18"
```

## Architecture Approaches

### Approach 1: Condition Field in Task Model (RECOMMENDED)

Add a `condition` field to the Task model that gets evaluated before execution.

```python
@dataclass
class Task:
    # Existing fields...
    condition: Optional[Union[str, Dict[str, Any]]] = None
    skip_on_false: bool = True  # Skip vs fail behavior
```

**Advantages:**
- Simple and declarative
- Works with existing dependency resolution
- No new workers needed
- Backward compatible

**Implementation:**
- DependencyWorker evaluates conditions after resolving dependencies
- If condition is false and `skip_on_false=True`, mark task as SKIPPED
- If condition is false and `skip_on_false=False`, mark task as FAILED

### Approach 2: Conditional Handler

Create a dedicated conditional handler that wraps other tasks.

```yaml
tasks:
  - id: conditional_wrapper
    protocol: conditional/v1
    method: evaluate
    params:
      condition: "${previous.result} > 100"
      if_true:
        protocol: email/v1
        method: send
        params: {...}
      if_false:
        protocol: log/v1
        method: write
        params: {...}
```

**Advantages:**
- Supports if/then/else patterns
- Can return different results based on condition
- Encapsulated logic

**Disadvantages:**
- More complex task definitions
- Nested task execution complexity
- Harder to visualize workflow

### Approach 3: Workflow Branching

Extend workflow model to support explicit branches.

```yaml
workflow:
  branches:
    - name: large_data_branch
      condition: "${data_size} > 1000"
      tasks: [process_batch, notify_admin]
      
    - name: small_data_branch
      condition: "${data_size} <= 1000"
      tasks: [process_inline]
```

**Advantages:**
- Clear workflow visualization
- Supports complex branching logic
- Can run branches in parallel

**Disadvantages:**
- Requires significant workflow model changes
- Complex dependency tracking across branches
- More difficult to implement

## Recommended Implementation Design

### Phase 1: Simple Conditions

#### Task Model Enhancement
```python
class Task:
    condition: Optional[str] = None  # Expression to evaluate
    condition_type: str = "expression"  # expression, comparison, logical
    skip_behavior: str = "skip"  # skip, fail, default
```

#### Condition Evaluation in DependencyWorker

```
1. Resolve dependencies (existing)
2. If task has condition:
   a. Parse condition expression
   b. Replace parameter references with resolved values
   c. Evaluate condition
   d. If false:
      - skip_behavior="skip" → Mark as SKIPPED
      - skip_behavior="fail" → Mark as FAILED
      - skip_behavior="default" → Use default value
3. If true or no condition:
   - Proceed with normal execution
```

#### New TaskStatus: SKIPPED
```python
class TaskStatus(Enum):
    # Existing statuses...
    SKIPPED = "skipped"  # Task skipped due to condition
```

### Phase 2: Advanced Conditions

#### Condition Types

```yaml
# Simple expression
condition: "${result} > 100"

# Comparison object
condition:
  type: comparison
  left: "${user.age}"
  operator: ">="
  right: 18

# Logical combinations
condition:
  type: logical
  operator: AND
  conditions:
    - "${user.active}"
    - "${user.verified}"
    
# Switch/case pattern
condition:
  type: switch
  value: "${status}"
  cases:
    pending: skip
    approved: execute
    rejected: fail
  default: skip
```

### Phase 3: Conditional Groups

#### Task Groups with Shared Conditions

```yaml
task_groups:
  - id: premium_features
    condition: "${user.subscription} == 'premium'"
    tasks:
      - id: advanced_analysis
      - id: priority_processing
      - id: detailed_report
```

## Execution Flow

### Current Flow
```
1. WorkflowLoaderWorker → Validates and loads workflow
2. DependencyWorker → Resolves dependencies
3. TaskExecutionWorker → Executes task
```

### Enhanced Flow with Conditions
```
1. WorkflowLoaderWorker → Validates workflow (including conditions)
2. DependencyWorker:
   a. Resolves dependencies
   b. Evaluates conditions
   c. Marks tasks as READY or SKIPPED
3. TaskExecutionWorker → Executes only READY tasks
```

## Condition Evaluation Engine

### Safe Expression Evaluation

```python
class ConditionEvaluator:
    """Safe condition evaluation"""
    
    ALLOWED_OPERATORS = {
        '==', '!=', '>', '<', '>=', '<=',
        'and', 'or', 'not', 'in', 'is'
    }
    
    def evaluate(self, expression: str, context: Dict) -> bool:
        # Parse expression into AST
        # Validate only safe operations
        # Replace parameter references
        # Evaluate safely (no exec/eval)
```

### Supported Operations

- **Comparisons**: `==`, `!=`, `>`, `<`, `>=`, `<=`
- **Logical**: `and`, `or`, `not`
- **Membership**: `in`, `not in`
- **Type checking**: `is None`, `is not None`
- **String operations**: `startswith`, `endswith`, `contains`
- **Numeric operations**: Basic arithmetic for comparisons

## Workflow Examples

### Example 1: Data Processing Pipeline

```yaml
workflow:
  name: Conditional Data Pipeline
  tasks:
    - id: check_data_size
      protocol: python/v1
      method: python/eval
      params:
        expression: "len(data) > 1000"
        
    - id: batch_process
      condition: "${check_data_size.result}"
      protocol: batch/v1
      method: process
      
    - id: inline_process
      condition: "not ${check_data_size.result}"
      protocol: python/v1
      method: python/execute
```

### Example 2: Approval Workflow

```yaml
workflow:
  name: Approval Flow
  tasks:
    - id: check_amount
      protocol: python/v1
      method: python/eval
      params:
        expression: "amount > 10000"
        
    - id: manager_approval
      condition: "${check_amount.result}"
      protocol: signal/v1
      method: wait
      params:
        signal_name: "manager_approved"
        
    - id: auto_approve
      condition: "not ${check_amount.result}"
      protocol: python/v1
      method: python/execute
      params:
        code: "result = {'approved': True, 'auto': True}"
        
    - id: process_order
      dependencies: [manager_approval, auto_approve]
      condition:
        any_of:
          - "${manager_approval.status} == 'completed'"
          - "${auto_approve.status} == 'completed'"
```

### Example 3: Error Handling

```yaml
tasks:
  - id: risky_operation
    protocol: http/v1
    method: post
    
  - id: send_alert
    condition: "${risky_operation.status} == 'failed'"
    protocol: email/v1
    method: send
    params:
      to: admin@company.com
      subject: "Operation failed"
      
  - id: continue_flow
    condition: "${risky_operation.status} == 'completed'"
    dependencies: [risky_operation]
```

## Storage Considerations

### Task Status Storage

```
Key: {shard:N}:task:status:{task_id}

New fields for conditional tasks:
  condition: Original condition expression
  condition_evaluated: Evaluated result (true/false/error)
  skip_reason: Why task was skipped
  evaluated_at: When condition was evaluated
```

### Workflow Metadata

```
Key: {shard:N}:workflow:metadata:{workflow_id}

New fields:
  total_tasks: Total number of tasks
  executed_tasks: Tasks that ran
  skipped_tasks: Tasks that were skipped
  conditional_tasks: Tasks with conditions
```

## Benefits

1. **Dynamic Workflows**: Adapt to runtime data
2. **Resource Efficiency**: Skip unnecessary tasks
3. **Error Handling**: Conditional error recovery
4. **A/B Testing**: Different paths based on conditions
5. **Feature Flags**: Enable/disable features dynamically
6. **Cost Optimization**: Only run expensive operations when needed

## Challenges and Solutions

### Challenge 1: Circular Dependencies
**Problem**: Task A depends on B's result, B has condition based on A
**Solution**: Detect cycles during workflow validation

### Challenge 2: Complex Condition Debugging
**Problem**: Hard to understand why task was skipped
**Solution**: Store detailed evaluation results and provide debugging tools

### Challenge 3: Condition Security
**Problem**: Arbitrary code execution in conditions
**Solution**: Use AST parsing and whitelist allowed operations

### Challenge 4: Performance Impact
**Problem**: Condition evaluation overhead
**Solution**: Cache evaluation results, optimize expression parser

## Migration Path

### Phase 1: Basic Support (2 weeks)
- Add condition field to Task model
- Implement simple expression evaluation
- Update DependencyWorker to handle conditions
- Add SKIPPED status

### Phase 2: Advanced Conditions (2 weeks)
- Implement logical operators (AND/OR/NOT)
- Add comparison objects
- Support nested conditions
- Add condition validation

### Phase 3: Tooling (1 week)
- Condition debugging UI
- Workflow visualization with branches
- Condition testing framework

### Phase 4: Optimization (1 week)
- Condition result caching
- Parallel condition evaluation
- Performance monitoring

## Alternative Patterns

### Pattern 1: Decision Tasks
Create specific decision tasks that output routing information:
```yaml
tasks:
  - id: router
    protocol: decision/v1
    method: route
    params:
      rules:
        - condition: "amount > 1000"
          route: "high_value_flow"
        - condition: "amount <= 1000"
          route: "standard_flow"
```

### Pattern 2: Conditional Handlers
Handlers that internally handle conditions:
```yaml
tasks:
  - id: conditional_email
    protocol: conditional/v1
    method: execute_if
    params:
      condition: "${alert_needed}"
      handler:
        protocol: email/v1
        method: send
```

### Pattern 3: Workflow Templates
Predefined workflow templates with variation points:
```yaml
workflow:
  template: approval_flow
  variations:
    high_value: "amount > 10000"
    expedited: "priority == 'urgent'"
```

## Conclusion

The recommended approach is to implement conditions as a field in the Task model, evaluated by the DependencyWorker. This provides:

1. **Simplicity**: Minimal changes to existing architecture
2. **Flexibility**: Supports various condition types
3. **Compatibility**: Works with current workflow model
4. **Performance**: Conditions evaluated once during dependency resolution
5. **Clarity**: Clear workflow definition with inline conditions

This design enables powerful conditional execution while maintaining Gleitzeit's clean architecture and distributed processing model.