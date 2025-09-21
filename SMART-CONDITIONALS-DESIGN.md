# Smart Conditionals Design - Without Breaking Dependencies

## The Problem

You're absolutely right - dependencies are for **ordering** (run BEFORE), not for **conditional execution**. We need a clean way to express "only run this task IF condition X is true" without conflating it with dependency ordering.

## Solution 1: Separate 'conditions' Field (Cleanest)

```python
class Task(BaseModel):
    # Existing - for ordering
    dependencies: List[str] = []  # These tasks must complete BEFORE this one
    
    # NEW - for conditional execution
    conditions: Optional[List[str]] = None  # These tasks must return true for this to run
    
    # OR even cleaner with a dict
    conditions: Optional[Dict[str, Any]] = None  # More expressive conditions
```

### Example Usage

```yaml
tasks:
  # Dependency task - must complete first
  - id: "fetch_customer_data"
    protocol: "api/v1"
    method: "get_customer"
    params:
      customer_id: "${input.customer_id}"
  
  # Condition task - evaluates to true/false
  - id: "is_premium_customer"
    protocol: "condition/v1"
    method: "evaluate"
    params:
      expression: "${fetch_customer_data.tier} == 'premium'"
    dependencies: ["fetch_customer_data"]  # Must run AFTER fetch
  
  # This task has both dependencies AND conditions
  - id: "apply_premium_discount"
    protocol: "pricing/v1"
    method: "apply_discount"
    params:
      rate: 0.2
    dependencies: ["fetch_customer_data"]  # Needs the data
    conditions: ["is_premium_customer"]    # Only runs if true
```

## Solution 2: Enhanced 'validators' Field (Reuse Existing Concept)

```python
class Task(BaseModel):
    dependencies: List[str] = []
    
    # Extend validators to include pre-conditions
    validators: Optional[Dict[str, Any]] = None
    # {
    #   "pre": [...],   # Pre-execution validators/conditions
    #   "post": [...]   # Post-execution validators
    # }
```

### Example

```yaml
tasks:
  - id: "check_inventory"
    protocol: "inventory/v1"
    method: "check_stock"
    params:
      sku: "${order.sku}"
  
  - id: "process_order"
    protocol: "order/v1"
    method: "fulfill"
    dependencies: ["check_inventory"]  # Must check inventory first
    validators:
      pre:  # Pre-execution conditions
        - type: "task_result"
          task: "check_inventory"
          field: "in_stock"
          operator: "=="
          value: true
        - type: "expression"
          expression: "${order.total} < ${customer.credit_limit}"
      post:  # Post-execution validation
        - type: "schema"
          schema: "${schemas.order_confirmation}"
```

## Solution 3: Smart 'when' Expression (Most Flexible)

```python
class Task(BaseModel):
    dependencies: List[str] = []
    
    # Single expressive field that can reference any previous task
    when: Optional[str] = None  # Evaluated after dependencies complete
```

### This is different from dependencies because:
- Dependencies = "run these BEFORE me"
- When = "only run me IF this expression is true"

### Example

```yaml
tasks:
  - id: "analyze_risk"
    protocol: "risk/v1"
    method: "assess"
    params:
      data: "${application}"
  
  - id: "check_credit"
    protocol: "credit/v1"
    method: "check"
    params:
      ssn: "${application.ssn}"
  
  - id: "auto_approve"
    protocol: "approval/v1"
    method: "approve"
    dependencies: ["analyze_risk", "check_credit"]  # Need both results
    when: "${analyze_risk.score} < 3 AND ${check_credit.score} > 700"  # Conditional execution
  
  - id: "manual_review"
    protocol: "approval/v1"
    method: "queue_for_review"
    dependencies: ["analyze_risk", "check_credit"]  # Same dependencies
    when: "${analyze_risk.score} >= 3 OR ${check_credit.score} <= 700"  # Different condition
```

## Solution 4: Introduce 'gates' (New Concept, but Clean)

```python
class Task(BaseModel):
    dependencies: List[str] = []  # Tasks that must complete before
    gates: Optional[List[str]] = None  # Tasks that must return true to proceed
```

### Example

```yaml
tasks:
  # Gate task - returns boolean
  - id: "can_process_payment"
    protocol: "validator/v1"
    method: "validate_payment"
    params:
      amount: "${order.total}"
      payment_method: "${order.payment}"
    dependencies: ["fetch_order"]
  
  # Gated task - only runs if gate passes
  - id: "charge_payment"
    protocol: "payment/v1"
    method: "charge"
    dependencies: ["fetch_order"]  # Needs order data
    gates: ["can_process_payment"]  # Must pass this gate
```

## Solution 5: Task Modes (Elegant Type System)

```python
class TaskMode(Enum):
    NORMAL = "normal"        # Regular task
    CONDITION = "condition"  # Returns boolean, affects downstream
    VALIDATOR = "validator"  # Validates and can stop flow
    GATE = "gate"           # Guards execution of dependent tasks

class Task(BaseModel):
    dependencies: List[str] = []
    mode: TaskMode = TaskMode.NORMAL
    
    # For GATE mode tasks
    guards: Optional[List[str]] = None  # Tasks this gate guards
```

### Example

```yaml
tasks:
  - id: "is_business_hours"
    mode: "gate"
    protocol: "condition/v1"
    method: "check_hours"
    guards: ["send_sms", "make_call"]  # These tasks need this gate
  
  - id: "send_sms"
    protocol: "twilio/v1"
    method: "send_sms"
    dependencies: ["prepare_message"]
    # Automatically gated by is_business_hours
  
  - id: "send_email"
    protocol: "email/v1"
    method: "send"
    dependencies: ["prepare_message"]
    # Not gated - emails can go anytime
```

## My Recommendation: Hybrid Approach

Combine the best of these solutions:

```python
class Task(BaseModel):
    # Existing
    dependencies: List[str] = []  # Ordering constraints
    
    # NEW - Three complementary fields
    when: Optional[str] = None  # Simple expression for common cases
    conditions: Optional[List[str]] = None  # Explicit condition tasks
    validators: Optional[Dict[str, Any]] = None  # Complex validation rules
```

### Why This Works:

1. **'when' for simple cases**:
   ```yaml
   when: "${customer.age} >= 18"
   ```

2. **'conditions' for task-based conditions**:
   ```yaml
   conditions: ["is_premium_customer", "has_valid_payment"]
   ```

3. **'validators' for complex rules**:
   ```yaml
   validators:
     pre:
       - type: "business_rule"
         rule: "check_compliance"
   ```

## Implementation Strategy (Non-Breaking)

```python
class TaskExecutor:
    async def should_execute_task(self, task: Task, context: Dict) -> bool:
        """Enhanced to check conditions without breaking dependencies"""
        
        # 1. First check dependencies (existing behavior)
        if not await self.check_dependencies_complete(task, context):
            return False
        
        # 2. NEW: Check 'when' expression
        if task.when:
            if not await self.evaluate_expression(task.when, context):
                await self.mark_task_skipped(task, f"When condition false: {task.when}")
                return False
        
        # 3. NEW: Check condition tasks
        if task.conditions:
            for condition_task_id in task.conditions:
                condition_result = context.get(condition_task_id, {}).get('result')
                if not condition_result:
                    await self.mark_task_skipped(task, f"Condition {condition_task_id} not met")
                    return False
        
        # 4. NEW: Check pre-validators
        if task.validators and task.validators.get('pre'):
            validation = await self.run_pre_validators(task.validators['pre'], context)
            if not validation.valid:
                await self.mark_task_skipped(task, f"Pre-validation failed: {validation.errors}")
                return False
        
        return True
    
    async def mark_task_skipped(self, task: Task, reason: str):
        """Mark task as skipped with reason"""
        task.status = TaskStatus.SKIPPED  # NEW status
        task.metadata = task.metadata or {}
        task.metadata['skip_reason'] = reason
        task.metadata['skipped_at'] = datetime.utcnow().isoformat()
        
        # Important: Set a result so dependent tasks can check it
        task.result = None  # or could be {'skipped': True}
        
        await self.save_task(task)
        await self.emit_event('task.skipped', {
            'task_id': task.id,
            'reason': reason
        })
```

## The Power of This Approach

### 1. Clear Separation of Concerns

```yaml
tasks:
  - id: "prepare_data"
    # Just a normal task
    
  - id: "validate_data"
    # Returns validation result
    dependencies: ["prepare_data"]
    
  - id: "check_budget"
    # Returns boolean
    dependencies: ["prepare_data"]
    
  - id: "expensive_processing"
    dependencies: ["prepare_data"]  # Needs the data (ordering)
    conditions: ["validate_data", "check_budget"]  # Only run if both true (gating)
```

### 2. Multiple Conditions with Different Logic

```yaml
tasks:
  - id: "process_premium"
    dependencies: ["load_data"]
    when: "${customer.tier} == 'premium'"  # Simple expression
    conditions: ["is_business_hours"]  # Task-based condition
    validators:
      pre:
        - type: "rate_limit"
          max_per_hour: 100
```

### 3. Branching Without Complexity

```yaml
tasks:
  # Three paths, same dependencies, different conditions
  - id: "path_a"
    dependencies: ["setup"]
    when: "${score} > 80"
    
  - id: "path_b"
    dependencies: ["setup"]
    when: "${score} > 50 AND ${score} <= 80"
    
  - id: "path_c"
    dependencies: ["setup"]
    when: "${score} <= 50"
```

## Benefits

1. **Non-Breaking**: Existing workflows continue to work
2. **Clear Semantics**: Dependencies = ordering, Conditions = gating
3. **Flexible**: Multiple ways to express conditions
4. **Composable**: Conditions can depend on other conditions
5. **Observable**: Every skip is tracked with reason
6. **Rewindable**: Can rewind to fix failed conditions

## Conclusion

By keeping dependencies for ordering and adding separate fields for conditions, we get:
- **Clarity**: No confusion about what dependencies mean
- **Power**: Express complex conditional logic
- **Compatibility**: No breaking changes
- **Flexibility**: Multiple ways to express conditions

The key insight is that **dependencies and conditions are orthogonal concerns**:
- Dependencies = "what must happen before"  
- Conditions = "whether this should happen"

This separation makes workflows much more expressive while keeping them understandable!