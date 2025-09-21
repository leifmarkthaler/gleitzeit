# Simplified Task Conditionals - Python API

## Current Verbose Python Syntax

```python
from gleitzeit import Workflow, Task

workflow = Workflow(
    tasks=[
        Task(
            id="get_customer",
            protocol="api/v1",
            method="fetch",
            params={"customer_id": "${input.customer_id}"}
        ),
        Task(
            id="is_premium",
            protocol="condition/v1",
            method="equals",
            params={
                "value": "${get_customer.tier}",
                "expected": "premium"
            },
            dependencies=["get_customer"]
        ),
        Task(
            id="skip_if_not_premium",
            protocol="skip/v1",
            method="skip_if_false",
            params={
                "condition_task": "is_premium",
                "skip_tasks": ["apply_discount"]
            },
            dependencies=["is_premium"]
        ),
        Task(
            id="apply_discount",
            protocol="pricing/v1",
            method="apply",
            params={"rate": 0.2},
            dependencies=["skip_if_not_premium"]
        )
    ]
)
```

## Simplified Python Syntax

### Option 1: Fluent Builder Pattern

```python
from gleitzeit import workflow

wf = (workflow()
    .task("get_customer", "api/v1", "fetch")
        .params(customer_id="${input.customer_id}")
    
    .task("apply_discount", "pricing/v1", "apply")
        .when("get_customer.tier == 'premium'")  # Auto-creates condition task
        .params(rate=0.2)
    
    .task("charge_card", "payment/v1", "charge")
        .skip_unless("validate_payment")  # Auto-creates skip task
        .fail_if("amount <= 0", "Invalid amount")  # Auto-creates fail task
    
    .build()
)
```

### Option 2: Decorator-Based

```python
from gleitzeit import workflow, task, when, skip_unless, fail_if

@workflow
class OrderProcessing:
    
    @task("api/v1", "fetch")
    def get_order(self, order_id: str):
        return {"order_id": order_id}
    
    @task("inventory/v1", "check")
    def check_inventory(self, items: list):
        return {"items": items}
    
    @task("payment/v1", "charge")
    @when("check_inventory.available == true")
    @fail_if("order.total <= 0", "Invalid order amount")
    def charge_payment(self, amount: float, card: str):
        return {"amount": amount, "card": card}
    
    @task("shipping/v1", "ship")
    @when("charge_payment.success")
    @skip_unless("check_inventory.available")
    def ship_order(self, order: dict):
        return {"order": order}
```

### Option 3: Context Manager Style

```python
from gleitzeit import Workflow

with Workflow() as wf:
    # Simple task
    get_customer = wf.task("get_customer", "api/v1", "fetch")
    
    # Task with condition
    with wf.task("apply_discount", "pricing/v1", "apply") as t:
        t.when(get_customer.tier == "premium")  # Python expression!
        t.params(rate=0.2)
    
    # Task with multiple guards
    with wf.task("process_payment", "payment/v1", "charge") as t:
        t.guards(
            get_customer.tier == "premium",
            wf.ref("order.total") > 1000,
            wf.ref("payment.valid") == True
        )
        t.fail_if(wf.ref("payment.declined"), "Payment declined")
```

### Option 4: Pythonic Class-Based

```python
from gleitzeit import Task, When, Skip, Fail

class GetCustomer(Task):
    protocol = "api/v1"
    method = "fetch"
    
class ApplyDiscount(Task):
    protocol = "pricing/v1"
    method = "apply"
    when = When("get_customer.tier == 'premium'")
    params = {"rate": 0.2}

class ChargePayment(Task):
    protocol = "payment/v1"
    method = "charge"
    guards = [
        When("order.total > 0"),
        When("payment_method.valid")
    ]
    actions = [
        Fail.if_true("payment.declined", "Payment was declined"),
        Skip.unless("inventory.available")
    ]

# Compose workflow
workflow = Workflow(
    GetCustomer(id="get_customer"),
    ApplyDiscount(id="apply_discount"),
    ChargePayment(id="charge_payment")
)
```

## Most Pythonic: Function-Based with Type Hints

```python
from gleitzeit import workflow, when, skip, fail
from typing import Dict, Any

@workflow
def process_order(order_id: str):
    """Process an order with conditional logic"""
    
    # Each function becomes a task
    @task("api/v1", "fetch")
    def get_order() -> Dict:
        return {"order_id": order_id}
    
    @task("api/v1", "fetch")
    def get_customer(order: Dict = get_order) -> Dict:
        # Dependencies inferred from function params!
        return {"customer_id": order["customer_id"]}
    
    @task("inventory/v1", "check")
    def check_stock(order: Dict = get_order) -> Dict:
        return {"items": order["items"]}
    
    @task("pricing/v1", "calculate")
    @when(lambda c: c.get_customer.tier == "premium")
    def apply_discount(order: Dict = get_order) -> Dict:
        return {"discount": 0.2}
    
    @task("payment/v1", "charge")
    @skip.unless(lambda c: c.check_stock.available)
    @fail.if_true(lambda c: c.get_customer.blocked, "Customer blocked")
    def charge_card(
        order: Dict = get_order,
        customer: Dict = get_customer
    ) -> Dict:
        return {"amount": order["total"]}
    
    @task("shipping/v1", "ship")
    @when(lambda c: c.charge_card.success)
    def ship_order(order: Dict = get_order) -> Dict:
        return {"shipped": True}
```

## Ultra-Simple: DSL-Style

```python
from gleitzeit import flow

# Almost like natural language
wf = flow(
    "get_customer" >> "api/v1:fetch",
    "check_age" >> "validator/v1:validate",
    
    "adult_content" >> "content/v1:serve" | when("check_age.result >= 18"),
    "kids_content" >> "content/v1:serve" | when("check_age.result < 18"),
    
    "charge_payment" >> "payment/v1:charge" | guards(
        "amount > 0",
        "card.valid",
        fail_if("card.declined")
    )
)
```

## Lambda-Based Conditions

```python
from gleitzeit import Workflow, task

wf = Workflow()

# Use Python lambdas for conditions
wf.add(
    task("get_customer", "api/v1", "fetch"),
    
    task("vip_features", "feature/v1", "enable")
        .when(lambda ctx: ctx.get_customer.tier == "premium"),
    
    task("process", "processor/v1", "run")
        .skip_if(lambda ctx: ctx.validation.errors > 0)
        .fail_if(lambda ctx: ctx.critical_check.failed, "Critical check failed")
)
```

## Switch/Case Pattern

```python
from gleitzeit import Workflow, switch

wf = Workflow()

# Document classification
classify = wf.task("classify", "llm/v1", "classify")

# Switch based on classification
wf.switch(on=classify.result.type).cases(
    invoice=lambda: [
        wf.task("extract_invoice", "extraction/v1", "invoice"),
        wf.task("update_books", "accounting/v1", "update")
    ],
    receipt=lambda: [
        wf.task("track_expense", "expense/v1", "track")
    ],
    default=lambda: [
        wf.task("manual_review", "queue/v1", "add")
    ]
)
```

## Real-World Example: E-commerce Order

```python
from gleitzeit import workflow, when, fail, skip

@workflow
def process_ecommerce_order(order_id: str):
    """Complete e-commerce order processing"""
    
    # Fetch data
    order = task("get_order", "api/v1", "fetch", order_id=order_id)
    customer = task("get_customer", "api/v1", "fetch", 
                   customer_id=order.customer_id)
    
    # Validations
    validate = task("validate_order", "validator/v1", "validate", 
                   order=order)
    
    fraud_check = task("check_fraud", "fraud/v1", "check", 
                      order=order, customer=customer) \
                 .fail_if(lambda c: c.result.score > 95, "Fraud detected") \
                 .pause_if(lambda c: c.result.score > 80, "Manual review needed")
    
    inventory = task("check_inventory", "inventory/v1", "check",
                    items=order.items)
    
    # Conditional processing
    priority_shipping = task("priority_ship", "shipping/v1", "priority") \
                       .when(lambda c: (
                           c.customer.tier == "premium" or 
                           c.order.total > 500
                       ))
    
    standard_shipping = task("standard_ship", "shipping/v1", "standard") \
                       .when(lambda c: (
                           c.customer.tier != "premium" and
                           c.order.total <= 500
                       ))
    
    # Payment with guards
    payment = task("charge", "payment/v1", "charge",
                  amount=order.total,
                  method=order.payment_method) \
             .guards(
                 lambda c: c.inventory.all_available,
                 lambda c: c.validate.passed,
                 lambda c: not c.customer.blocked
             ) \
             .fail_if(lambda c: c.result.declined, "Payment declined")
    
    # Notification
    notify = task("notify", "email/v1", "send",
                 to=customer.email,
                 order=order) \
            .when(lambda c: c.payment.success)
```

## Implementation: Task Class with Conditions

```python
class Task:
    def __init__(self, id: str, protocol: str, method: str, **params):
        self.id = id
        self.protocol = protocol
        self.method = method
        self.params = params
        self._conditions = []
        self._guards = []
        self._actions = []
    
    def when(self, condition):
        """Add a condition - can be string or lambda"""
        if callable(condition):
            # Lambda: when(lambda c: c.customer.tier == "premium")
            self._conditions.append(("lambda", condition))
        else:
            # String: when("customer.tier == 'premium'")
            self._conditions.append(("expression", condition))
        return self
    
    def skip_if(self, condition, reason=None):
        """Skip this task if condition is true"""
        self._actions.append(("skip_if", condition, reason))
        return self
    
    def fail_if(self, condition, message):
        """Fail workflow if condition is true"""
        self._actions.append(("fail_if", condition, message))
        return self
    
    def guards(self, *conditions):
        """Multiple conditions that must all pass"""
        self._guards.extend(conditions)
        return self
    
    def _expand(self):
        """Expand this task into multiple tasks (internal)"""
        expanded = []
        
        # Create condition tasks for each when/guard
        for cond_type, condition in self._conditions:
            condition_task = self._create_condition_task(condition)
            expanded.append(condition_task)
        
        # Create action tasks for skip/fail
        for action_type, condition, param in self._actions:
            action_task = self._create_action_task(action_type, condition, param)
            expanded.append(action_task)
        
        # Add self
        expanded.append(self)
        return expanded
```

## Benefits of Python Syntax

1. **Type Safety** - IDE support and type checking
2. **Refactorable** - Use variables, functions, classes
3. **Testable** - Unit test individual conditions
4. **Debuggable** - Set breakpoints in conditions
5. **Pythonic** - Feels natural to Python developers

## Migration Example

```python
# Old verbose way
workflow = Workflow(
    tasks=[
        Task(id="check", protocol="validator/v1", method="validate"),
        Task(id="is_valid", protocol="condition/v1", method="equals",
             params={"value": "${check.valid}", "expected": True}),
        Task(id="skip_if_invalid", protocol="skip/v1", method="skip_if_false",
             params={"condition_task": "is_valid", "skip_tasks": ["process"]}),
        Task(id="process", protocol="processor/v1", method="run",
             dependencies=["skip_if_invalid"])
    ]
)

# New simplified way
workflow = Workflow()
workflow.task("check", "validator/v1", "validate")
workflow.task("process", "processor/v1", "run").when("check.valid")

# Or even simpler with builder
workflow = (Workflow()
    .task("check", "validator/v1", "validate")
    .task("process", "processor/v1", "run").when("check.valid")
    .build()
)
```

## Conclusion

The Python API can be dramatically simplified while maintaining the pure task-based approach:

- **80% less code** for common patterns
- **Natural Python syntax** with lambdas and decorators
- **Progressive disclosure** - simple cases simple, complex possible
- **Full backward compatibility** - can mix styles
- **Automatic expansion** - still creates all the tasks internally

The key is that the simplified syntax is just a **builder API** that generates the full task graph behind the scenes!