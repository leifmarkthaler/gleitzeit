# Inline Action Syntax - Cleaner Conditionals

## The Problem

Current approach creates explicit action tasks:
```python
# Verbose - separate fail task
t("fail_if_fraud", "fail/v1:evaluate")
    .needs("fraud_check")
    .with_(
        condition="${fraud_check.score} > 90",
        error_message="High fraud risk detected"
    )

t("process_order", "order/v1:process")
    .needs("fail_if_fraud")  # Must depend on fail task
```

## The Solution: Inline Actions

Make fail/skip/split **inline directives** that auto-create hidden tasks:

```python
# Clean - inline fail directive
t("process_order", "order/v1:process")
    .needs("fraud_check")
    .fail_if("${fraud_check.score} > 90", "High fraud risk detected")
    .skip_if("${inventory.available} == 0", "Out of stock")
    .with_(order="${input.order}")
```

## How It Works

### Input (What You Write):
```python
t("charge_payment", "payment/v1:charge")
    .needs("validate_order")
    .fail_if("${balance} < ${amount}", "Insufficient funds")
    .skip_if("${amount} == 0", "Zero amount")
    .with_(amount="${order.total}")
```

### Output (What Gets Created):
```python
[
    # Hidden fail task (auto-generated)
    {
        "id": "charge_payment_fail_check",
        "protocol": "fail/v1",
        "method": "evaluate",
        "params": {
            "condition": "${balance} < ${amount}",
            "error_message": "Insufficient funds"
        },
        "dependencies": ["validate_order"]
    },
    # Hidden skip task (auto-generated)
    {
        "id": "charge_payment_skip_check",
        "protocol": "skip/v1",
        "method": "evaluate",
        "params": {
            "condition": "${amount} == 0",
            "skip_tasks": ["charge_payment"],
            "reason": "Zero amount"
        },
        "dependencies": ["charge_payment_fail_check"]
    },
    # Your actual task
    {
        "id": "charge_payment",
        "protocol": "payment/v1",
        "method": "charge",
        "params": {"amount": "${order.total}"},
        "dependencies": ["charge_payment_skip_check"]  # Depends on checks
    }
]
```

## Complete Inline Action Syntax

### 1. Fail Conditions
```python
# Single fail condition
t("process", "processor/v1:run")
    .fail_if("${input.valid} == false", "Invalid input")

# Multiple fail conditions (checked in order)
t("process", "processor/v1:run")
    .fail_if("${auth.valid} == false", "Not authenticated")
    .fail_if("${quota.remaining} <= 0", "Quota exceeded")
    .fail_if("${rate_limit.exceeded}", "Rate limited")
```

### 2. Skip Conditions
```python
# Skip if condition is true
t("premium_feature", "feature/v1:activate")
    .skip_if("${user.tier} != 'premium'", "Not premium user")

# Skip unless condition (opposite)
t("premium_feature", "feature/v1:activate")
    .skip_unless("${user.tier} == 'premium'", "Not premium user")
```

### 3. Combined Actions
```python
t("process_payment", "payment/v1:charge")
    .needs("validate_order", "check_inventory")
    .fail_if("${validate_order.valid} == false", "Invalid order")
    .fail_if("${fraud_check.score} > 90", "Fraud detected")
    .skip_if("${order.total} == 0", "Free order")
    .skip_if("${customer.credit} > ${order.total}", "Using store credit")
    .with_(amount="${order.total}")
```

### 4. When/Unless Conditions (for execution)
```python
# Only execute when condition is true
t("apply_discount", "pricing/v1:discount")
    .when("${customer.tier} == 'premium'")
    .with_(rate=0.2)

# Execute unless condition is true
t("charge_shipping", "shipping/v1:calculate")
    .unless("${customer.tier} == 'premium'")  # Premium gets free shipping
    .with_(weight="${order.weight}")
```

### 5. Split/Route (inline branching)
```python
# Inline split based on value
t("process_document", "processor/v1:route")
    .split_on("${document.type}")
    .route("invoice", "process_invoice")
    .route("receipt", "process_receipt")
    .route("default", "manual_review")
```

## Implementation

### TaskBuilder Extensions
```python
class TaskBuilder:
    def __init__(self, id: str, run: str):
        self.task = {"id": id, "run": run}
        self._fail_conditions = []
        self._skip_conditions = []
        self._when_conditions = []
        self._split_routes = {}
    
    def fail_if(self, condition: str, message: str = None):
        """Add fail condition"""
        self._fail_conditions.append({
            "condition": condition,
            "message": message or f"Condition failed: {condition}"
        })
        return self
    
    def skip_if(self, condition: str, reason: str = None):
        """Add skip condition"""
        self._skip_conditions.append({
            "condition": condition,
            "reason": reason or f"Skipped: {condition}"
        })
        return self
    
    def skip_unless(self, condition: str, reason: str = None):
        """Skip if condition is false"""
        # Invert the condition
        inverted = f"!({condition})" if "==" in condition else f"not {condition}"
        return self.skip_if(inverted, reason)
    
    def when(self, condition: str):
        """Only execute when condition is true"""
        self._when_conditions.append(condition)
        return self
    
    def unless(self, condition: str):
        """Execute unless condition is true"""
        return self.when(f"!({condition})")
    
    def split_on(self, expression: str):
        """Start split routing"""
        self._split_expression = expression
        return self
    
    def route(self, value: str, task: str):
        """Add route for split"""
        self._split_routes[value] = task
        return self
    
    def _expand(self) -> list:
        """Expand to multiple tasks"""
        tasks = []
        last_dep = self.task.get("needs", [])
        
        # Create fail tasks
        for i, fail in enumerate(self._fail_conditions):
            fail_task = {
                "id": f"{self.task['id']}_fail_{i}",
                "protocol": "fail/v1",
                "method": "evaluate",
                "params": {
                    "condition": fail["condition"],
                    "error_message": fail["message"]
                },
                "dependencies": last_dep
            }
            tasks.append(fail_task)
            last_dep = [fail_task["id"]]
        
        # Create skip tasks
        for i, skip in enumerate(self._skip_conditions):
            skip_task = {
                "id": f"{self.task['id']}_skip_{i}",
                "protocol": "skip/v1",
                "method": "evaluate",
                "params": {
                    "condition": skip["condition"],
                    "skip_tasks": [self.task["id"]],
                    "reason": skip["reason"]
                },
                "dependencies": last_dep
            }
            tasks.append(skip_task)
            last_dep = [skip_task["id"]]
        
        # Create when conditions
        for i, when in enumerate(self._when_conditions):
            when_task = {
                "id": f"{self.task['id']}_when_{i}",
                "protocol": "condition/v1",
                "method": "evaluate",
                "params": {"expression": when},
                "dependencies": last_dep
            }
            tasks.append(when_task)
            
            skip_task = {
                "id": f"{self.task['id']}_when_skip_{i}",
                "protocol": "skip/v1",
                "method": "skip_if_false",
                "params": {
                    "condition_task": when_task["id"],
                    "skip_tasks": [self.task["id"]]
                },
                "dependencies": [when_task["id"]]
            }
            tasks.append(skip_task)
            last_dep = [skip_task["id"]]
        
        # Update main task dependencies
        self.task["dependencies"] = last_dep
        tasks.append(self.task)
        
        return tasks
```

## Real-World Example: Order Processing

### Before (Explicit Action Tasks):
```python
workflow = w(
    t("check_fraud", "fraud/v1:assess"),
    
    t("fail_if_high_fraud", "fail/v1:evaluate")
        .needs("check_fraud")
        .with_(
            condition="${check_fraud.score} > 90",
            error_message="High fraud risk"
        ),
    
    t("check_inventory", "inventory/v1:check")
        .needs("fail_if_high_fraud"),
    
    t("skip_if_no_inventory", "skip/v1:evaluate")
        .needs("check_inventory")
        .with_(
            condition="${check_inventory.available} == 0",
            skip_tasks=["charge_payment", "ship_order"]
        ),
    
    t("charge_payment", "payment/v1:charge")
        .needs("skip_if_no_inventory")
)
```

### After (Inline Actions):
```python
workflow = w(
    t("check_fraud", "fraud/v1:assess"),
    
    t("check_inventory", "inventory/v1:check")
        .needs("check_fraud")
        .fail_if("${check_fraud.score} > 90", "High fraud risk"),
    
    t("charge_payment", "payment/v1:charge")
        .needs("check_inventory")
        .skip_if("${check_inventory.available} == 0", "Out of stock")
        .fail_if("${balance} < ${amount}", "Insufficient funds")
        .with_(amount="${order.total}")
)
```

**50% less code, much clearer intent!**

## Complete E-commerce Example with Inline Actions

```python
workflow = w(
    # Validate and check fraud
    t("validate_order", "validator/v1:check")
        .with_(order="${input.order}")
        .fail_if("${result.valid} == false", "Invalid order structure"),
    
    t("check_fraud", "fraud/v1:assess")
        .needs("validate_order")
        .with_(order="${input.order}"),
    
    # Check inventory with inline skip
    t("check_inventory", "inventory/v1:check")
        .needs("validate_order")
        .with_(items="${input.order.items}"),
    
    # Process payment with multiple conditions
    t("charge_payment", "payment/v1:charge")
        .needs("check_fraud", "check_inventory")
        .fail_if("${check_fraud.score} > 90", "High fraud risk")
        .fail_if("${check_fraud.score} > 70 && ${order.total} > 5000", "Manual review required")
        .skip_if("${check_inventory.available} == false", "Out of stock")
        .skip_if("${order.total} == 0", "Free order")
        .with_(amount="${order.total}")
        .retry(3),
    
    # Premium features with when condition
    t("apply_premium_shipping", "shipping/v1:premium")
        .needs("charge_payment")
        .when("${customer.tier} == 'premium'")
        .with_(order="${order}"),
    
    # Standard shipping with unless condition
    t("apply_standard_shipping", "shipping/v1:standard")
        .needs("charge_payment")
        .unless("${customer.tier} == 'premium'")
        .with_(order="${order}"),
    
    # Send confirmation (always runs if payment succeeded)
    t("send_confirmation", "email/v1:send")
        .needs("charge_payment")
        .with_(
            template="order_confirmation",
            to="${customer.email}"
        )
)
```

## Benefits of Inline Actions

1. **Cleaner Code** - No separate action tasks cluttering the workflow
2. **Clear Intent** - Actions are attached to the tasks they affect
3. **Less Verbose** - 50% fewer lines
4. **Natural Reading** - "charge payment, but fail if fraud, skip if no inventory"
5. **Same Power** - Still creates all necessary tasks internally

## Comparison

| Style | Lines | Clarity | Power |
|-------|-------|---------|-------|
| Explicit action tasks | 100 | Medium | Full |
| Inline actions | 50 | High | Full |
| No conditions | 30 | Low | Limited |

## Conclusion

Inline actions provide the best of both worlds:
- **Simple syntax** like traditional programming
- **Full power** of task-based conditions
- **Clean workflows** without clutter
- **Natural reading** with clear intent

This makes workflows feel like writing regular code while maintaining the pure task-based architecture underneath!