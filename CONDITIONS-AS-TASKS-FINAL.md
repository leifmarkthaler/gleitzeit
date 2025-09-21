# Conditions as Tasks - The Clean Solution

## The Core Challenge

If conditions are tasks, they need to:
1. Run BEFORE the tasks they gate (so must be in dependencies)
2. But not all dependencies are conditions
3. We need to distinguish which dependencies are conditions

## Solution: Mark Condition Tasks, Not Consumer Tasks

Instead of adding complexity to every task, mark the **condition tasks themselves**:

```python
class Task(BaseModel):
    # Existing fields
    dependencies: List[str] = []
    
    # NEW: Mark this task as a condition/gate
    is_condition: bool = False  # This task returns a boolean that gates others
    # OR
    task_type: str = "normal"  # "normal", "condition", "validator"
```

## The Elegant Pattern

```yaml
tasks:
  # CONDITION TASK - marked as such
  - id: "is_premium_customer"
    task_type: "condition"  # THIS IS A CONDITION
    protocol: "python/v1"
    method: "evaluate"
    params:
      expression: "${customer.tier} == 'premium'"
  
  # NORMAL TASK - depends on condition
  - id: "apply_premium_discount"
    protocol: "pricing/v1"
    method: "apply_discount"
    dependencies: ["is_premium_customer"]  # Just list it as dependency!
    # System automatically knows is_premium_customer is a condition
    # and will skip this task if condition returns false
```

## Even Better: Semantic Task Types

```python
class TaskType(Enum):
    NORMAL = "normal"          # Regular task
    CONDITION = "condition"    # Returns boolean, gates dependent tasks
    VALIDATOR = "validator"    # Validates data, can fail workflow
    TRANSFORM = "transform"    # Data transformation
    BRANCH = "branch"         # Determines path selection

class Task(BaseModel):
    # Existing
    dependencies: List[str] = []
    
    # NEW: Semantic type
    task_type: TaskType = TaskType.NORMAL
    
    # Optional: How to handle condition failure
    on_condition_false: str = "skip"  # "skip", "fail", "pause"
```

## The Execution Logic

```python
class TaskExecutor:
    async def should_execute_task(self, task: Task, context: Dict) -> bool:
        """Check if task should execute based on dependencies"""
        
        # Check all dependencies are complete (existing)
        for dep_id in task.dependencies:
            dep_task = context.get(dep_id)
            if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                return False  # Not ready yet
            
            # NEW: If dependency is a condition, check its result
            if dep_task.task_type == TaskType.CONDITION:
                if not dep_task.result:  # Condition returned false
                    # Handle based on configuration
                    if task.on_condition_false == "skip":
                        await self.mark_task_skipped(task, f"Condition {dep_id} was false")
                        return False
                    elif task.on_condition_false == "fail":
                        await self.mark_task_failed(task, f"Required condition {dep_id} not met")
                        return False
                    elif task.on_condition_false == "pause":
                        await self.pause_workflow(task.workflow_id, f"Condition {dep_id} requires attention")
                        return False
        
        return True
```

## Or Even Cleaner: Condition Results Are Special

```python
class ConditionResult(BaseModel):
    """Special result type for condition tasks"""
    passed: bool
    reason: Optional[str] = None
    details: Optional[Dict] = None

class Task(BaseModel):
    # When a task's protocol is "condition/v1", 
    # the system knows to treat its result specially
    protocol: str
    
    # Or use method to indicate condition
    method: str  # "evaluate_condition", "check_condition", etc.
```

## Real-World Examples

### Example 1: Multi-Path Workflow

```yaml
tasks:
  # Condition tasks
  - id: "is_high_value"
    protocol: "condition/v1"  # Protocol indicates this is a condition
    method: "evaluate"
    params:
      expression: "${order.total} > 1000"
  
  - id: "has_premium_shipping"
    protocol: "condition/v1"
    method: "evaluate"
    params:
      expression: "${order.shipping_type} == 'premium'"
  
  - id: "is_international"
    protocol: "condition/v1"
    method: "evaluate"
    params:
      expression: "${order.country} != 'US'"
  
  # These tasks automatically skip if their condition dependencies are false
  - id: "apply_vip_discount"
    dependencies: ["is_high_value"]  # Only runs if true
    
  - id: "expedite_shipping"
    dependencies: ["has_premium_shipping"]  # Only runs if true
    
  - id: "customs_processing"
    dependencies: ["is_international"]  # Only runs if true
  
  # This needs multiple conditions
  - id: "special_handling"
    dependencies: ["is_high_value", "is_international"]  # Needs BOTH true
```

### Example 2: Validation Chain

```yaml
tasks:
  - id: "validate_schema"
    protocol: "validator/v1"  # Validator protocol
    method: "json_schema"
    params:
      schema: "${schemas.order}"
      data: "${input}"
  
  - id: "validate_inventory"
    protocol: "validator/v1"
    method: "check_inventory"
    params:
      items: "${input.items}"
    dependencies: ["validate_schema"]  # Only check if schema valid
  
  - id: "validate_payment"
    protocol: "validator/v1"
    method: "verify_payment"
    params:
      method: "${input.payment}"
    dependencies: ["validate_inventory"]  # Only check if inventory valid
  
  - id: "process_order"
    protocol: "order/v1"
    method: "process"
    dependencies: ["validate_payment"]  # Only process if all validations pass
    # This automatically won't run if any validator fails
```

## The Ultimate Insight: Protocol-Based Behavior

The cleanest solution might be to use **protocols** to determine behavior:

```python
CONDITION_PROTOCOLS = ["condition/v1", "validator/v1", "gate/v1"]

class TaskExecutor:
    async def should_execute_task(self, task: Task, context: Dict) -> bool:
        for dep_id in task.dependencies:
            dep_task = context.get(dep_id)
            
            # Check if dependency is a condition based on protocol
            if dep_task.protocol in CONDITION_PROTOCOLS:
                if not self.evaluate_condition_result(dep_task.result):
                    return False  # Skip this task
        
        return True
```

## Why This is the Best Approach

1. **No New Fields on Consumer Tasks** - Tasks don't need to know which dependencies are conditions
2. **Semantic Protocols** - `condition/v1` clearly indicates purpose
3. **Automatic Behavior** - System handles condition logic based on protocol
4. **Backward Compatible** - Existing tasks work unchanged
5. **Composable** - Conditions can depend on other conditions

## Special Case: Multiple Condition Logic

What if we need OR logic instead of AND?

```yaml
tasks:
  # Create a composite condition task!
  - id: "can_expedite"
    protocol: "condition/v1"
    method: "any"  # OR logic
    params:
      conditions: ["is_premium", "is_high_value", "is_urgent"]
    dependencies: ["is_premium", "is_high_value", "is_urgent"]
  
  - id: "expedite_order"
    dependencies: ["can_expedite"]  # Clean and simple!
```

## Implementation Requirements

1. **Add TaskType or protocol recognition** (minimal change)
2. **Enhance executor to check condition results** (small change)
3. **Add SKIPPED status** for tasks that don't run due to conditions

```python
class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # NEW - condition not met
```

## Conclusion

By marking **condition tasks** rather than their consumers, we get:

- **Clean Dependencies** - Just list conditions as dependencies
- **Automatic Gating** - System handles the logic
- **No Ambiguity** - Protocols/types make intent clear
- **Full Power** - Conditions are real tasks with all capabilities
- **Backward Compatible** - No changes to existing workflows

This is the cleanest solution that preserves the "everything is a task" philosophy while adding powerful conditional execution!