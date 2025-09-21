# Complete Workflow Design - Simplification + Conditionals + Validators

## Executive Summary

A comprehensive design for simplified Gleitzeit workflows that includes:
- **Simple chaining syntax** (70% less verbose)
- **Pure task-based conditionals** (no inline code)
- **Validators as tasks** (consistent model)
- **Error-driven control flow** (leverages existing infrastructure)
- **100-200 lines total** to implement

## Part 1: Simple Chaining Syntax

### Basic Builder Pattern
```python
from gleitzeit.easy import t, w

workflow = w(
    t("get_customer", "api/v1:fetch")
        .with_(customer_id="${input.customer_id}")
        .cache(300),
    
    t("apply_discount", "pricing/v1:apply")
        .needs("get_customer")
        .with_(rate=0.2)
        .retry(3)
)
```

### Implementation (50 lines)
```python
class TaskBuilder:
    def __init__(self, id: str, run: str):
        self.task = {"id": id, "run": run}
    
    def needs(self, *deps):
        self.task["needs"] = list(deps)
        return self
    
    def with_(self, **params):
        self.task["with"] = params
        return self
    
    def retry(self, attempts):
        self.task["retry"] = attempts
        return self
    
    def to_dict(self):
        return self.task
```

## Part 2: Pure Task-Based Conditionals

### The Philosophy: Everything is a Task

Instead of inline expressions, conditions become tasks that return boolean values.

### Condition Tasks
```python
workflow = w(
    # Data task
    t("get_customer", "api/v1:fetch")
        .with_(customer_id="${input.customer_id}"),
    
    # CONDITION TASK - evaluates to true/false
    t("is_premium", "condition/v1:equals")
        .needs("get_customer")
        .with_(
            value="${get_customer.tier}",
            expected="premium"
        ),
    
    # Task that depends on condition
    t("apply_premium_discount", "pricing/v1:apply")
        .needs("is_premium")
        .when("is_premium")  # Only runs if condition is true
        .with_(rate=0.3)
)
```

### Simplified Syntax for Conditions
```python
# Auto-create condition tasks with .if_()
t("apply_discount", "pricing/v1:apply")
    .needs("get_customer")
    .if_("${get_customer.tier} == 'premium'")  # Creates condition task automatically
    .with_(rate=0.2)

# Expands to:
[
    {
        "id": "apply_discount_condition",
        "protocol": "condition/v1",
        "method": "evaluate",
        "params": {"expression": "${get_customer.tier} == 'premium'"}
    },
    {
        "id": "apply_discount",
        "protocol": "pricing/v1",
        "method": "apply",
        "when": "apply_discount_condition",  # References condition task
        "params": {"rate": 0.2}
    }
]
```

### Complex Conditions
```python
# Multiple conditions (AND logic)
t("process_vip_order", "order/v1:process")
    .needs("get_customer", "get_order")
    .if_("${get_customer.tier} == 'premium'")
    .if_("${get_order.total} > 1000")  # Multiple conditions = AND
    .with_(priority="high")

# OR logic using condition tasks
t("needs_review", "condition/v1:any")
    .with_(conditions=[
        "${order.flagged} == true",
        "${order.amount} > 10000",
        "${customer.risk_score} > 80"
    ]),

t("manual_review", "review/v1:queue")
    .when("needs_review")
```

## Part 3: Action Tasks (fail, skip, split)

### Skip Tasks
```python
# Skip tasks based on conditions
t("skip_if_not_premium", "skip/v1:evaluate")
    .needs("is_premium")
    .with_(
        condition="${is_premium.result} == false",
        skip_tasks=["premium_feature_1", "premium_feature_2"]
    )
```

### Fail Tasks
```python
# Fail workflow if condition met
t("fail_if_invalid", "fail/v1:evaluate")
    .needs("validate_order")
    .with_(
        condition="${validate_order.valid} == false",
        error_message="Order validation failed: ${validate_order.errors}"
    )
```

### Split Tasks (Branching)
```python
# Route based on conditions
t("route_by_type", "split/v1:route")
    .needs("classify_document")
    .with_(
        switch_on="${classify_document.type}",
        routes={
            "invoice": ["process_invoice", "update_accounting"],
            "receipt": ["track_expense", "file_receipt"],
            "default": ["manual_review"]
        }
    )
```

### Simplified Action Syntax
```python
# These create action tasks automatically
t("charge_payment", "payment/v1:charge")
    .needs("validate_order")
    .skip_if("${order.total} == 0")  # Creates skip task
    .fail_if("${balance} < ${total}", "Insufficient funds")  # Creates fail task
    .with_(amount="${order.total}")
```

## Part 4: Validators as Tasks

### Validation Tasks
```python
workflow = w(
    # VALIDATOR TASK - can fail the workflow
    t("validate_order", "validator/v1:schema")
        .with_(
            data="${input.order}",
            schema="${schemas.order_schema}"
        ),
    
    # Chain validators
    t("validate_inventory", "validator/v1:check_stock")
        .needs("validate_order")  # Only check if schema valid
        .with_(items="${input.order.items}"),
    
    t("validate_payment", "validator/v1:verify_card")
        .needs("validate_inventory")  # Only check if inventory valid
        .with_(card="${input.payment_method}"),
    
    # Process only if all validations pass
    t("process_order", "order/v1:process")
        .needs("validate_payment")  # Implicitly needs all validations
)
```

### Validation with Recovery
```python
# Validator with fallback
t("validate_primary_payment", "validator/v1:verify")
    .with_(method="${order.payment.primary}"),

t("try_backup_payment", "validator/v1:verify")
    .needs("validate_primary_payment")
    .if_("${validate_primary_payment.valid} == false")  # Only if primary fails
    .with_(method="${order.payment.backup}"),

t("process_payment", "payment/v1:charge")
    .needs("validate_primary_payment", "try_backup_payment")
    .when_any(["validate_primary_payment", "try_backup_payment"])  # If either succeeds
```

## Part 5: Error-Driven Control Flow

### Custom Errors Instead of Events
```python
# Provider throws structured error
class TokenLimitError(ProviderError):
    def __init__(self, tokens, limit):
        super().__init__(
            code="TOKEN_LIMIT_EXCEEDED",
            message=f"{tokens} tokens exceeds {limit} limit",
            details={
                "tokens": tokens,
                "limit": limit,
                "suggested_model": "gpt-3.5-turbo"
            }
        )

# Errors automatically go to Redis Stream
# React to them with listeners (Phase 2)
on("task:failed")
    .filter("${event.error_code} == 'TOKEN_LIMIT_EXCEEDED'")
    .run("retry_with_smaller_model", "llm/v1:generate")
    .with_(model="${event.error_details.suggested_model}")
```

## Part 6: Complete Real-World Example

### E-commerce Order with All Features
```python
from gleitzeit.easy import t, w

order_workflow = w(
    # === VALIDATION PHASE ===
    
    t("validate_order_schema", "validator/v1:schema")
        .with_(
            data="${input.order}",
            schema="${schemas.order_v2}"
        ),
    
    t("validate_customer", "validator/v1:check_customer")
        .needs("validate_order_schema")
        .with_(customer_id="${input.order.customer_id}")
        .fail_if("${result.blocked}", "Customer is blocked"),
    
    # === CONDITION CHECKS ===
    
    t("is_premium_customer", "condition/v1:equals")
        .needs("validate_customer")
        .with_(
            value="${validate_customer.tier}",
            expected="premium"
        ),
    
    t("is_high_value_order", "condition/v1:greater_than")
        .needs("validate_order_schema")
        .with_(
            value="${input.order.total}",
            threshold=1000
        ),
    
    t("qualifies_for_free_shipping", "condition/v1:any")
        .needs("is_premium_customer", "is_high_value_order")
        .with_(conditions=[
            "${is_premium_customer.result}",
            "${is_high_value_order.result}"
        ]),
    
    # === INVENTORY CHECK ===
    
    t("check_inventory", "inventory/v1:check")
        .needs("validate_order_schema")
        .with_(items="${input.order.items}"),
    
    # === PRICING CALCULATIONS ===
    
    t("calculate_base_price", "pricing/v1:calculate")
        .needs("check_inventory")
        .with_(items="${input.order.items}"),
    
    t("apply_premium_discount", "pricing/v1:discount")
        .needs("calculate_base_price", "is_premium_customer")
        .when("is_premium_customer")  # Only if premium
        .with_(rate=0.2),
    
    t("apply_bulk_discount", "pricing/v1:discount")
        .needs("calculate_base_price")
        .if_("${input.order.quantity} > 10")  # Auto-creates condition
        .with_(rate=0.1),
    
    t("apply_free_shipping", "shipping/v1:free")
        .needs("qualifies_for_free_shipping")
        .when("qualifies_for_free_shipping"),
    
    # === FRAUD CHECK ===
    
    t("check_fraud", "fraud/v1:assess")
        .needs("validate_customer", "calculate_base_price")
        .with_(
            customer="${validate_customer}",
            order="${input.order}"
        )
        .fail_if("${result.score} > 90", "High fraud risk"),
    
    t("manual_fraud_review", "review/v1:queue")
        .needs("check_fraud")
        .if_("${check_fraud.score} > 70 && ${check_fraud.score} <= 90")
        .with_(priority="high"),
    
    # === PAYMENT PROCESSING ===
    
    t("validate_payment_method", "validator/v1:verify_card")
        .needs("check_fraud")
        .with_(card="${input.order.payment.card}"),
    
    t("charge_payment", "payment/v1:charge")
        .needs("validate_payment_method", "apply_premium_discount", "apply_bulk_discount")
        .with_(
            amount="${calculate_base_price.total}",
            card="${input.order.payment.card}"
        )
        .retry(3)
        .fail_if("${validate_payment_method.valid} == false", "Invalid payment method"),
    
    # === ORDER FULFILLMENT ===
    
    t("create_fulfillment", "fulfillment/v1:create")
        .needs("charge_payment")
        .if_("${charge_payment.success}")
        .with_(
            order="${input.order}",
            warehouse="${check_inventory.warehouse}"
        ),
    
    # === SHIPPING ===
    
    t("route_shipping", "split/v1:route")
        .needs("create_fulfillment", "qualifies_for_free_shipping")
        .with_(
            switch_on="${qualifies_for_free_shipping.result}",
            routes={
                "true": ["ship_express"],
                "false": ["ship_standard"]
            }
        ),
    
    t("ship_express", "shipping/v1:express")
        .needs("route_shipping")
        .with_(order="${input.order}"),
    
    t("ship_standard", "shipping/v1:standard")
        .needs("route_shipping")
        .with_(order="${input.order}"),
    
    # === NOTIFICATIONS ===
    
    t("send_confirmation", "email/v1:send")
        .needs("create_fulfillment")
        .with_(
            template="order_confirmation",
            to="${validate_customer.email}",
            order="${input.order}"
        ),
    
    # === ERROR HANDLING (via streams) ===
    # These would be registered separately
    
    on("task:failed")
        .filter("${event.task_id} == 'charge_payment'")
        .run("restore_inventory", "inventory/v1:release")
        .with_(items="${input.order.items}"),
    
    on("task:failed")
        .filter("${event.error_code} == 'INSUFFICIENT_INVENTORY'")
        .run("notify_backorder", "email/v1:send")
        .with_(
            template="backorder_notification",
            items="${event.error_details.unavailable_items}"
        )
)
```

## Implementation Roadmap

### Phase 1: Core Syntax (Day 1)
1. **TaskBuilder class** - 50 lines
2. **Expansion logic** - 100 lines
3. **Integration with client** - 20 lines

```python
# Total: ~170 lines for core functionality
def expand_workflow(workflow):
    """Expand simplified syntax to full Gleitzeit format"""
    expanded_tasks = []
    
    for task in workflow["tasks"]:
        # Handle .if_() → condition task
        if "if" in task:
            condition_task = create_condition_task(task["if"])
            expanded_tasks.append(condition_task)
            
        # Handle .skip_if() → skip task
        if "skip_if" in task:
            skip_task = create_skip_task(task["skip_if"])
            expanded_tasks.append(skip_task)
            
        # Handle .fail_if() → fail task
        if "fail_if" in task:
            fail_task = create_fail_task(task["fail_if"])
            expanded_tasks.append(fail_task)
            
        expanded_tasks.append(task)
    
    return expanded_tasks
```

### Phase 2: Condition/Action Providers (Day 2)
1. **ConditionProvider** - evaluates expressions
2. **SkipProvider** - skips tasks
3. **FailProvider** - fails workflows
4. **SplitProvider** - routes execution

```python
class ConditionProvider(ProtocolProvider):
    """Provider for condition/v1 protocol"""
    
    async def equals(self, value, expected):
        return value == expected
    
    async def greater_than(self, value, threshold):
        return value > threshold
    
    async def any(self, conditions):
        return any(conditions)
    
    async def all(self, conditions):
        return all(conditions)
```

### Phase 3: Error Enhancements (Day 3)
1. Add error_code and error_details to streams
2. Define error taxonomy
3. Update providers to throw rich errors

### Phase 4: Event Listeners (Optional, Week 2)
1. Event listener registration
2. Event-to-task creation
3. Pattern matching

## Benefits Summary

| Feature | Before | After | Reduction |
|---------|--------|-------|-----------|
| Simple Task | 8 lines | 2 lines | 75% |
| Conditional Task | 20 lines | 3 lines | 85% |
| Validation Chain | 50 lines | 15 lines | 70% |
| Complete Workflow | 200+ lines | 60 lines | 70% |

## Key Design Principles

1. **Everything is a Task**
   - Conditions are tasks
   - Validators are tasks
   - Actions (skip/fail) are tasks

2. **No Inline Code**
   - No lambda functions
   - No eval expressions
   - Everything is declarative

3. **Leverage Existing Infrastructure**
   - Redis Streams for events
   - Error system for control flow
   - Task model for everything

4. **Progressive Enhancement**
   - Start with basic chaining
   - Add conditions/validators
   - Add error reactions later

## Conclusion

This complete design provides:
- **70% reduction in verbosity**
- **Pure task-based approach** (no inline code)
- **Rich conditionals and validators**
- **Error-driven control flow**
- **1-3 days to implement fully**
- **No architecture changes**

The key insight: By making everything a task (conditions, validators, actions) and using errors for control flow, we get a powerful, simple, and scalable workflow system!