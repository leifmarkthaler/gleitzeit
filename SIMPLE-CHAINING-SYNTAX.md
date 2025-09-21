# Simple Chaining Syntax - Best of Both Worlds

## The Idea: Chain Simple Dict Builders

No complex classes or metaprogramming - just simple functions that return dicts and can chain!

## Approach 1: Lightweight Chainable Builder

```python
from gleitzeit.easy import t, w

# Simple chaining with dict builders
workflow = w(
    t("get_customer", "api/v1:fetch")
        .with_(customer_id="${input.customer_id}")
        .cache(300),
    
    t("check_premium", "condition/v1:check")
        .needs("get_customer")
        .if_("${get_customer.tier} == 'premium'"),
    
    t("apply_discount", "pricing/v1:apply")
        .needs("get_customer")
        .when("check_premium")  # Reference condition task
        .with_(rate=0.2)
        .fail_if("${get_customer.blocked}", "Customer blocked"),
    
    t("charge_payment", "payment/v1:charge")
        .needs("apply_discount")
        .with_(amount="${order.total}")
        .retry(3)
        .timeout(30)
)
```

**Implementation (Super Simple!):**

```python
class TaskBuilder:
    """Simple chainable dict builder"""
    
    def __init__(self, id: str, run: str):
        self.task = {"id": id, "run": run}
    
    def needs(self, *deps):
        self.task["needs"] = list(deps)
        return self
    
    def if_(self, expression):
        self.task["if"] = expression
        return self
    
    def when(self, condition_task):
        """Reference another condition task"""
        self.task["when"] = condition_task
        return self
    
    def with_(self, **params):
        self.task["with"] = params
        return self
    
    def fail_if(self, expression, message=None):
        self.task["fail_if"] = expression
        if message:
            self.task["fail_message"] = message
        return self
    
    def skip_if(self, expression):
        self.task["skip_if"] = expression
        return self
    
    def retry(self, attempts):
        self.task["retry"] = attempts
        return self
    
    def timeout(self, seconds):
        self.task["timeout"] = seconds
        return self
    
    def cache(self, ttl):
        self.task["cache"] = ttl
        return self
    
    def to_dict(self):
        return self.task

# Helper functions
def t(id: str, run: str) -> TaskBuilder:
    """Create a task builder"""
    return TaskBuilder(id, run)

def w(*tasks) -> dict:
    """Create workflow from tasks"""
    return {
        "tasks": [t.to_dict() if hasattr(t, 'to_dict') else t for t in tasks]
    }
```

## Approach 2: Even Simpler - Just Dicts with Helpers

```python
from gleitzeit.simple import task, when, needs, fail_if, retry

# Each function returns a dict that gets merged
workflow = {
    "tasks": [
        task("get_customer", "api/v1:fetch",
            {"customer_id": "${input.customer_id}"},
            cache=300),
        
        task("apply_discount", "pricing/v1:apply",
            {"rate": 0.2},
            needs("get_customer"),
            when("${get_customer.tier} == 'premium'"),
            fail_if("${get_customer.blocked}", "Customer blocked")),
        
        task("charge_payment", "payment/v1:charge",
            {"amount": "${order.total}"},
            needs("apply_discount"),
            retry(3),
            timeout(30))
    ]
}
```

**Implementation:**

```python
def task(id: str, run: str, params=None, **modifiers):
    """Build task with modifiers"""
    t = {"id": id, "run": run}
    
    if params:
        t["with"] = params
    
    # Apply all modifiers
    for mod in modifiers.values():
        if isinstance(mod, dict):
            t.update(mod)
    
    return t

def needs(*deps):
    return {"needs": list(deps)}

def when(expression):
    return {"if": expression}

def fail_if(expr, msg=None):
    d = {"fail_if": expr}
    if msg:
        d["fail_message"] = msg
    return d

def retry(attempts):
    return {"retry": attempts}

def timeout(seconds):
    return {"timeout": seconds}

def cache(ttl):
    return {"cache": ttl}
```

## Approach 3: Pipeline Operator Style

```python
from gleitzeit.pipe import task, pipe

# Use >> for chaining (or | if you prefer)
workflow = pipe(
    task("get_customer", "api/v1:fetch") 
        >> needs("${input.customer_id}"),
    
    task("check_premium") 
        >> when("${get_customer.tier} == 'premium'"),
    
    task("apply_discount", "pricing/v1:apply")
        >> needs("get_customer")
        >> when("check_premium")
        >> params(rate=0.2)
        >> fail_if("${blocked}"),
    
    task("charge_payment", "payment/v1:charge")
        >> needs("apply_discount")
        >> params(amount="${order.total}")
        >> retry(3)
        >> timeout(30)
)
```

## Approach 4: Arrow Functions (Most Concise)

```python
from gleitzeit.arrow import w, t

# Super concise with arrow notation
workflow = w([
    t("get_customer") >> "api/v1:fetch" >> {"customer_id": "${input.id}"},
    
    t("apply_discount") 
        >> "pricing/v1:apply"
        >> needs("get_customer")
        >> when("${get_customer.tier} == 'premium'")
        >> {"rate": 0.2},
    
    t("charge_payment")
        >> "payment/v1:charge" 
        >> needs("apply_discount")
        >> {"amount": "${total}"}
        >> retry(3)
])
```

## My Recommendation: Simple Builder (Approach 1)

The `TaskBuilder` approach is best because:

1. **Intuitive** - Methods clearly show what they do
2. **Chainable** - Familiar pattern from jQuery, pandas, etc.
3. **Simple Implementation** - Just 50 lines
4. **Type-Safe** - IDE autocomplete works
5. **No Magic** - Just returns dicts

## Real-World Example with Chaining

```python
from gleitzeit.easy import t, w

order_workflow = w(
    # Fetch data in parallel
    t("get_order", "api/v1:fetch")
        .with_(order_id="${input.order_id}")
        .cache(60),
    
    t("get_customer", "api/v1:fetch")
        .with_(customer_id="${input.customer_id}")
        .cache(300),
    
    # Validations
    t("validate_order", "validator/v1:check")
        .needs("get_order")
        .fail_if("${get_order.items} == []", "Empty order"),
    
    t("check_fraud", "fraud/v1:assess")
        .needs("get_order", "get_customer")
        .timeout(10),
    
    # Conditional processing
    t("apply_premium_discount", "pricing/v1:discount")
        .needs("get_customer", "validate_order")
        .if_("${get_customer.tier} == 'premium'")
        .with_(rate=0.2),
    
    t("apply_bulk_discount", "pricing/v1:discount")
        .needs("get_order", "validate_order")
        .if_("${get_order.quantity} > 10")
        .with_(rate=0.1),
    
    # Payment with guards
    t("charge_payment", "payment/v1:charge")
        .needs("apply_premium_discount", "apply_bulk_discount", "check_fraud")
        .fail_if("${check_fraud.score} > 80", "High fraud risk")
        .with_(amount="${order.total}")
        .retry(3)
        .timeout(30)
        .on_failure("send_payment_failed_email"),
    
    # Shipping
    t("ship_order", "shipping/v1:ship")
        .needs("charge_payment")
        .if_("${charge_payment.success}")
        .with_(
            method="${'express' if get_customer.tier == 'premium' else 'standard'}",
            address="${get_order.shipping_address}"
        )
)

# Still just returns a dict!
print(order_workflow)
# {"tasks": [{"id": "get_order", "run": "api/v1:fetch", ...}, ...]}
```

## How It Expands

The builder just creates dicts that get expanded:

```python
# This:
t("apply_discount", "pricing/v1:apply")
    .needs("get_customer")
    .if_("${get_customer.tier} == 'premium'")
    .with_(rate=0.2)

# Becomes this dict:
{
    "id": "apply_discount",
    "run": "pricing/v1:apply",
    "needs": ["get_customer"],
    "if": "${get_customer.tier} == 'premium'",
    "with": {"rate": 0.2}
}

# Which expands to these tasks:
[
    {
        "id": "apply_discount_cond",
        "protocol": "condition/v1",
        "method": "evaluate",
        "params": {"expression": "${get_customer.tier} == 'premium'"},
        "dependencies": ["get_customer"]
    },
    {
        "id": "apply_discount_skip",
        "protocol": "skip/v1",
        "method": "skip_if_false",
        "params": {
            "condition_task": "apply_discount_cond",
            "skip_tasks": ["apply_discount"]
        },
        "dependencies": ["apply_discount_cond"]
    },
    {
        "id": "apply_discount",
        "protocol": "pricing/v1",
        "method": "apply",
        "params": {"rate": 0.2},
        "dependencies": ["apply_discount_skip"]
    }
]
```

## Complete Implementation (Under 100 Lines!)

```python
# gleitzeit/easy.py

class TaskBuilder:
    def __init__(self, id: str, run: str):
        self.task = {"id": id, "run": run}
    
    def needs(self, *deps):
        self.task["needs"] = list(deps)
        return self
    
    def if_(self, expression):
        self.task["if"] = expression
        return self
    
    def with_(self, **params):
        self.task["with"] = params
        return self
    
    def fail_if(self, expression, message=None):
        self.task["fail_if"] = expression
        if message:
            self.task["fail_message"] = message
        return self
    
    def skip_if(self, expression):
        self.task["skip_if"] = expression
        return self
    
    def retry(self, attempts):
        self.task["retry"] = attempts
        return self
    
    def timeout(self, seconds):
        self.task["timeout"] = seconds
        return self
    
    def cache(self, ttl):
        self.task["cache"] = ttl
        return self
    
    def on_failure(self, handler):
        self.task["on_failure"] = handler
        return self
    
    def to_dict(self):
        return self.task

def t(id: str, run: str) -> TaskBuilder:
    return TaskBuilder(id, run)

def w(*tasks) -> dict:
    task_dicts = []
    for task in tasks:
        if hasattr(task, 'to_dict'):
            task_dicts.append(task.to_dict())
        else:
            task_dicts.append(task)
    
    return {"tasks": task_dicts}

def expand_workflow(workflow: dict) -> dict:
    """Expand simplified syntax to full Gleitzeit format"""
    expanded_tasks = []
    
    for task in workflow["tasks"]:
        # Expand convenience fields
        result = expand_task(task)
        expanded_tasks.extend(result)
    
    workflow["tasks"] = expanded_tasks
    return workflow
```

## Why This Works

1. **Familiar Pattern** - Like jQuery, pandas, SQLAlchemy
2. **No Magic** - Just building dicts
3. **Tiny Implementation** - Under 100 lines total
4. **Full Power** - Can express everything
5. **Easy to Debug** - Can print intermediate dicts

This gives you chaining without any of the complexity of decorators or metaprogramming!