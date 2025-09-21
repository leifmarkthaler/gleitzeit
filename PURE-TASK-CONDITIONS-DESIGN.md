# Pure Task-Based Conditions - No Inline Code

## The Pure Approach

EVERYTHING is a task - conditions, actions, everything. No inline expressions!

## Pattern: Condition Tasks + Action Tasks

```yaml
tasks:
  # DATA TASK - Gets data
  - id: "fetch_customer"
    protocol: "api/v1"
    method: "get_customer"
    params:
      customer_id: "${input.customer_id}"
  
  # CONDITION TASK - Evaluates condition (returns true/false)
  - id: "is_premium_customer"
    protocol: "condition/v1"
    method: "equals"
    params:
      value: "${fetch_customer.tier}"
      expected: "premium"
    dependencies: ["fetch_customer"]
  
  # ACTION TASK - Skip based on condition task result
  - id: "skip_non_premium_features"
    protocol: "skip/v1"
    method: "skip_if_false"
    params:
      condition_task: "is_premium_customer"  # References the condition task
      skip_tasks: ["premium_dashboard", "vip_support", "priority_shipping"]
    dependencies: ["is_premium_customer"]
  
  # FEATURE TASKS - Will be skipped if not premium
  - id: "premium_dashboard"
    protocol: "ui/v1"
    method: "enable_dashboard"
    dependencies: ["skip_non_premium_features"]
```

## Complete Example: Document Processing

```yaml
tasks:
  # STEP 1: Analyze document
  - id: "analyze_document"
    protocol: "llm/v1"
    method: "analyze"
    params:
      document: "${input.document}"
  
  # STEP 2: Condition checks (all are tasks!)
  
  - id: "check_if_invoice"
    protocol: "condition/v1"
    method: "equals"
    params:
      value: "${analyze_document.type}"
      expected: "invoice"
    dependencies: ["analyze_document"]
  
  - id: "check_if_contract"
    protocol: "condition/v1"
    method: "equals"
    params:
      value: "${analyze_document.type}"
      expected: "contract"
    dependencies: ["analyze_document"]
  
  - id: "check_if_receipt"
    protocol: "condition/v1"
    method: "equals"
    params:
      value: "${analyze_document.type}"
      expected: "receipt"
    dependencies: ["analyze_document"]
  
  - id: "check_confidence_high"
    protocol: "condition/v1"
    method: "greater_than"
    params:
      value: "${analyze_document.confidence}"
      threshold: 0.8
    dependencies: ["analyze_document"]
  
  # STEP 3: Action tasks based on conditions
  
  - id: "skip_invoice_flow"
    protocol: "skip/v1"
    method: "skip_if_false"
    params:
      condition_task: "check_if_invoice"
      skip_tasks: ["extract_invoice_data", "process_invoice", "update_accounting"]
    dependencies: ["check_if_invoice"]
  
  - id: "skip_contract_flow"
    protocol: "skip/v1"
    method: "skip_if_false"
    params:
      condition_task: "check_if_contract"
      skip_tasks: ["extract_contract_terms", "legal_review", "store_contract"]
    dependencies: ["check_if_contract"]
  
  - id: "skip_receipt_flow"
    protocol: "skip/v1"
    method: "skip_if_false"
    params:
      condition_task: "check_if_receipt"
      skip_tasks: ["extract_receipt_data", "expense_tracking"]
    dependencies: ["check_if_receipt"]
  
  - id: "fail_if_low_confidence"
    protocol: "fail/v1"
    method: "fail_if_false"
    params:
      condition_task: "check_confidence_high"
      error_message: "Document classification confidence too low"
    dependencies: ["check_confidence_high"]
  
  # STEP 4: Processing tasks (each flow)
  
  - id: "extract_invoice_data"
    protocol: "extraction/v1"
    method: "extract_invoice"
    dependencies: ["skip_invoice_flow", "fail_if_low_confidence"]
  
  - id: "extract_contract_terms"
    protocol: "extraction/v1"
    method: "extract_contract"
    dependencies: ["skip_contract_flow", "fail_if_low_confidence"]
  
  # ... more tasks
```

## Condition Task Types

### 1. Comparison Conditions

```yaml
# EQUALS
- id: "is_premium"
  protocol: "condition/v1"
  method: "equals"
  params:
    value: "${customer.tier}"
    expected: "premium"

# GREATER THAN
- id: "is_high_value"
  protocol: "condition/v1"
  method: "greater_than"
  params:
    value: "${order.total}"
    threshold: 1000

# LESS THAN
- id: "is_under_budget"
  protocol: "condition/v1"
  method: "less_than"
  params:
    value: "${project.cost}"
    threshold: "${project.budget}"

# IN LIST
- id: "is_supported_region"
  protocol: "condition/v1"
  method: "in_list"
  params:
    value: "${user.country}"
    list: ["US", "CA", "UK", "AU"]

# CONTAINS
- id: "has_keyword"
  protocol: "condition/v1"
  method: "contains"
  params:
    text: "${document.content}"
    substring: "urgent"
```

### 2. Logical Combination Conditions

```yaml
# AND - All must be true
- id: "can_expedite"
  protocol: "condition/v1"
  method: "all"
  params:
    conditions: ["is_premium", "is_high_value", "has_inventory"]
  dependencies: ["is_premium", "is_high_value", "has_inventory"]

# OR - Any must be true
- id: "needs_review"
  protocol: "condition/v1"
  method: "any"
  params:
    conditions: ["is_flagged", "is_suspicious", "is_high_risk"]
  dependencies: ["is_flagged", "is_suspicious", "is_high_risk"]

# NOT
- id: "is_not_premium"
  protocol: "condition/v1"
  method: "not"
  params:
    condition: "is_premium"
  dependencies: ["is_premium"]
```

### 3. Complex Conditions

```yaml
# RANGE CHECK
- id: "is_valid_age"
  protocol: "condition/v1"
  method: "in_range"
  params:
    value: "${user.age}"
    min: 18
    max: 65

# REGEX MATCH
- id: "is_valid_email"
  protocol: "condition/v1"
  method: "matches_pattern"
  params:
    value: "${user.email}"
    pattern: "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"

# NULL CHECK
- id: "has_payment_method"
  protocol: "condition/v1"
  method: "is_not_null"
  params:
    value: "${order.payment_method}"
```

## Action Task Types

### 1. Skip Actions

```yaml
# Skip if condition is false
- id: "skip_if_not_eligible"
  protocol: "skip/v1"
  method: "skip_if_false"
  params:
    condition_task: "is_eligible"
    skip_tasks: ["task1", "task2"]
  dependencies: ["is_eligible"]

# Skip if condition is true
- id: "skip_if_already_processed"
  protocol: "skip/v1"
  method: "skip_if_true"
  params:
    condition_task: "was_processed"
    skip_tasks: ["reprocess", "update"]
  dependencies: ["was_processed"]
```

### 2. Fail Actions

```yaml
# Fail if condition is true
- id: "fail_if_invalid"
  protocol: "fail/v1"
  method: "fail_if_true"
  params:
    condition_task: "is_invalid"
    error_message: "Validation failed"
  dependencies: ["is_invalid"]

# Fail if condition is false
- id: "fail_if_not_authorized"
  protocol: "fail/v1"
  method: "fail_if_false"
  params:
    condition_task: "is_authorized"
    error_message: "Not authorized"
  dependencies: ["is_authorized"]
```

### 3. Split Actions

```yaml
# First, create condition tasks for each branch
- id: "is_type_a"
  protocol: "condition/v1"
  method: "equals"
  params:
    value: "${data.type}"
    expected: "A"

- id: "is_type_b"
  protocol: "condition/v1"
  method: "equals"
  params:
    value: "${data.type}"
    expected: "B"

# Then use split task to route
- id: "route_by_type"
  protocol: "split/v1"
  method: "route"
  params:
    conditions:
      - condition_task: "is_type_a"
        activate_tasks: ["process_type_a", "validate_a"]
      - condition_task: "is_type_b"
        activate_tasks: ["process_type_b", "validate_b"]
      - default:
        activate_tasks: ["handle_unknown"]
  dependencies: ["is_type_a", "is_type_b"]
```

## Real-World Example: Order Processing

```yaml
tasks:
  # FETCH DATA
  - id: "get_order"
    protocol: "api/v1"
    method: "fetch_order"
    params:
      order_id: "${input.order_id}"
  
  - id: "get_customer"
    protocol: "api/v1"
    method: "fetch_customer"
    params:
      customer_id: "${get_order.customer_id}"
    dependencies: ["get_order"]
  
  # CONDITIONS (all are tasks!)
  
  - id: "is_premium_customer"
    protocol: "condition/v1"
    method: "equals"
    params:
      value: "${get_customer.tier}"
      expected: "premium"
    dependencies: ["get_customer"]
  
  - id: "is_high_value_order"
    protocol: "condition/v1"
    method: "greater_than"
    params:
      value: "${get_order.total}"
      threshold: 500
    dependencies: ["get_order"]
  
  - id: "has_express_shipping"
    protocol: "condition/v1"
    method: "equals"
    params:
      value: "${get_order.shipping_type}"
      expected: "express"
    dependencies: ["get_order"]
  
  - id: "inventory_available"
    protocol: "inventory/v1"
    method: "check_availability"
    params:
      items: "${get_order.items}"
    dependencies: ["get_order"]
  
  # LOGICAL COMBINATIONS
  
  - id: "qualifies_for_upgrade"
    protocol: "condition/v1"
    method: "all"
    params:
      conditions: ["is_premium_customer", "is_high_value_order"]
    dependencies: ["is_premium_customer", "is_high_value_order"]
  
  - id: "needs_expedite"
    protocol: "condition/v1"
    method: "any"
    params:
      conditions: ["has_express_shipping", "qualifies_for_upgrade"]
    dependencies: ["has_express_shipping", "qualifies_for_upgrade"]
  
  # ACTIONS
  
  - id: "skip_regular_shipping"
    protocol: "skip/v1"
    method: "skip_if_true"
    params:
      condition_task: "needs_expedite"
      skip_tasks: ["standard_shipping", "economy_packaging"]
    dependencies: ["needs_expedite"]
  
  - id: "skip_expedited_shipping"
    protocol: "skip/v1"
    method: "skip_if_false"
    params:
      condition_task: "needs_expedite"
      skip_tasks: ["priority_shipping", "premium_packaging"]
    dependencies: ["needs_expedite"]
  
  - id: "fail_if_no_inventory"
    protocol: "fail/v1"
    method: "fail_if_false"
    params:
      condition_task: "inventory_available"
      error_message: "Items out of stock"
    dependencies: ["inventory_available"]
  
  # PROCESSING TASKS
  
  - id: "standard_shipping"
    protocol: "shipping/v1"
    method: "standard"
    dependencies: ["skip_regular_shipping", "fail_if_no_inventory"]
  
  - id: "priority_shipping"
    protocol: "shipping/v1"
    method: "priority"
    dependencies: ["skip_expedited_shipping", "fail_if_no_inventory"]
```

## Implementation: Condition and Action Providers

```python
class ConditionProvider:
    """Provider for condition/v1 protocol"""
    
    async def equals(self, value: Any, expected: Any) -> bool:
        return value == expected
    
    async def greater_than(self, value: float, threshold: float) -> bool:
        return value > threshold
    
    async def less_than(self, value: float, threshold: float) -> bool:
        return value < threshold
    
    async def in_list(self, value: Any, list: List[Any]) -> bool:
        return value in list
    
    async def all(self, conditions: List[str], context: Dict) -> bool:
        """All condition tasks must return true"""
        for condition_id in conditions:
            if not context.get(condition_id, {}).get('result'):
                return False
        return True
    
    async def any(self, conditions: List[str], context: Dict) -> bool:
        """Any condition task must return true"""
        for condition_id in conditions:
            if context.get(condition_id, {}).get('result'):
                return True
        return False

class SkipProvider:
    """Provider for skip/v1 protocol"""
    
    async def skip_if_true(self, condition_task: str, skip_tasks: List[str], context: Dict) -> Dict:
        condition_result = context.get(condition_task, {}).get('result')
        
        if condition_result:
            for task_id in skip_tasks:
                context[f"{task_id}.skip"] = True
            return {"skipped": skip_tasks}
        
        return {"skipped": []}
    
    async def skip_if_false(self, condition_task: str, skip_tasks: List[str], context: Dict) -> Dict:
        condition_result = context.get(condition_task, {}).get('result')
        
        if not condition_result:
            for task_id in skip_tasks:
                context[f"{task_id}.skip"] = True
            return {"skipped": skip_tasks}
        
        return {"skipped": []}
```

## Benefits of Pure Task Approach

1. **No Inline Code** - Everything is a declarative task
2. **Testable** - Each condition is a testable unit
3. **Reusable** - Condition tasks can be referenced multiple times
4. **Observable** - Every decision shows in logs
5. **Debuggable** - Can pause/rewind at any condition
6. **Type-Safe** - No string evaluation, just task protocols

## Conclusion

By making conditions AND actions both tasks:
- **No inline expressions** - Everything is a task with a protocol
- **Pure data flow** - Tasks produce data, conditions check data, actions control flow
- **Maximum composability** - Build complex logic from simple tasks
- **Complete observability** - Every decision point is visible

This is the purest expression of the Gleitzeit philosophy: **Everything is a task!**