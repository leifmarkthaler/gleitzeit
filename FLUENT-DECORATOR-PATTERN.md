# Fluent Pattern with Decorators - Best of Both Worlds

## The Hybrid Approach

Combine decorators for task definition with fluent methods for conditions and actions.

## Basic Pattern

```python
from gleitzeit import workflow, task

@workflow
class OrderProcessing:
    
    @task("api/v1", "fetch")
    def get_customer(self, customer_id: str):
        """Fetch customer data"""
        return self.when("input.customer_id != null") \
                   .params(customer_id=customer_id) \
                   .cache(ttl=3600)
    
    @task("pricing/v1", "calculate")
    def calculate_discount(self, customer):
        """Calculate discount based on customer tier"""
        return self.when(lambda c: c.get_customer.tier == "premium") \
                   .params(rate=0.2) \
                   .fail_if(lambda c: c.get_customer.blocked, "Customer blocked") \
                   .timeout(30)
    
    @task("payment/v1", "charge")
    def charge_payment(self, amount: float):
        """Charge customer payment method"""
        return self.guards(
                     lambda c: c.calculate_discount.completed,
                     lambda c: c.amount > 0
                   ) \
                   .skip_if(lambda c: c.test_mode == True) \
                   .retry(max_attempts=3, backoff="exponential") \
                   .on_failure(self.handle_payment_failure)
```

## Advanced: Fluent Task Builder via Decorator

```python
from gleitzeit import workflow, task, Task

@workflow
class DocumentProcessor:
    
    @task  # Decorator returns a Task builder instance
    def classify_document(self) -> Task:
        """Classify document using LLM"""
        return (Task("llm/v1", "classify")
            .params(
                prompt="Classify this document",
                model="gpt-4"
            )
            .timeout(60)
            .retry(max_attempts=2)
        )
    
    @task
    def process_invoice(self) -> Task:
        """Process invoice document"""
        return (Task("extraction/v1", "extract_invoice")
            .when(lambda c: c.classify_document.type == "invoice")
            .depends_on(self.classify_document)
            .fail_if(lambda c: c.classify_document.confidence < 0.8)
            .params(
                format="structured",
                fields=["amount", "date", "vendor"]
            )
        )
    
    @task
    def process_receipt(self) -> Task:
        """Process receipt document"""
        return (Task("extraction/v1", "extract_receipt")
            .when(lambda c: c.classify_document.type == "receipt")
            .depends_on(self.classify_document)
            .params(format="simple")
            .parallel_with(self.send_notification)  # Run in parallel
        )
    
    @task
    def send_notification(self) -> Task:
        return (Task("notify/v1", "send")
            .when(lambda c: c.classify_document.confidence > 0.9)
            .skip_if(lambda c: c.user.notifications_disabled)
        )
```

## Method Chaining on Decorated Functions

```python
from gleitzeit import workflow

@workflow
class DataPipeline:
    
    @task("api/v1", "fetch")
    .when(lambda c: c.input.source != None)  # Chain on decorator!
    .timeout(30)
    .cache(ttl=3600)
    def fetch_data(self, source: str):
        return {"source": source}
    
    @task("validator/v1", "validate")
    .depends_on(fetch_data)
    .fail_if(lambda c: c.fetch_data.error != None)
    .retry(max_attempts=3)
    def validate_data(self, data):
        return {"data": data}
    
    @task("ml/v1", "predict")
    .when(lambda c: c.validate_data.valid == True)
    .guards(
        lambda c: c.fetch_data.size < 1000000,  # Less than 1MB
        lambda c: c.quota.remaining > 0
    )
    .on_failure(lambda: self.fallback_prediction())
    def run_ml_model(self, data):
        return {"prediction": "..."}
```

## Using Property Decorators for Fluent API

```python
from gleitzeit import Workflow, task_property

class SmartWorkflow(Workflow):
    
    @task_property
    def get_user(self):
        """Property that returns a fluent task builder"""
        return self.task("api/v1", "get_user") \
                   .params(user_id="${input.user_id}") \
                   .cache(ttl=300)
    
    @task_property
    def check_permissions(self):
        return self.task("auth/v1", "check") \
                   .depends_on(self.get_user) \
                   .when(lambda c: c.get_user.active == True) \
                   .fail_if(lambda c: c.get_user.banned == True, "User banned")
    
    @task_property  
    def process_request(self):
        return self.task("processor/v1", "run") \
                   .depends_on(self.check_permissions) \
                   .when(lambda c: c.check_permissions.authorized) \
                   .timeout(120) \
                   .retry(max_attempts=5)

# Usage
workflow = SmartWorkflow()
result = await workflow.run(input={"user_id": "123"})
```

## Context-Aware Fluent Decorators

```python
from gleitzeit import workflow, auto_task

@workflow
class SmartPipeline:
    """Decorators that understand context and build fluent chains"""
    
    @auto_task  # Infers protocol from return type
    def fetch_customer(self, customer_id: str) -> "api/customer":
        """Auto-task infers this is api/v1 protocol"""
        return self.when(customer_id != None) \
                   .cache(ttl=3600)
    
    @auto_task
    def calculate_risk(self, customer) -> "risk/assessment":
        """Auto-task infers risk/v1 protocol"""
        return self.depends_on(self.fetch_customer) \
                   .when(lambda c: c.fetch_customer.data != None) \
                   .parallel_with([
                       self.check_credit,
                       self.check_fraud,
                       self.check_history
                   ])
    
    @auto_task
    def make_decision(self) -> "decision/final":
        return self.after_all([  # Wait for all to complete
                       self.calculate_risk,
                       self.check_credit,
                       self.check_fraud
                   ]) \
                   .switch(lambda c: c.calculate_risk.score) \
                   .cases(
                       high=self.auto_approve,
                       medium=self.manual_review,
                       low=self.reject
                   )
```

## Mixing Decorators with Builder Pattern

```python
from gleitzeit import Workflow, task

class HybridWorkflow(Workflow):
    
    def __init__(self):
        super().__init__()
        
        # Use decorators for simple tasks
        self.add_tasks(
            self.get_data,
            self.validate
        )
        
        # Use builder for complex conditional logic
        self.add(
            self.task("processor/v1", "run")
                .when(lambda c: c.validate.passed)
                .guards(
                    lambda c: c.get_data.size > 0,
                    lambda c: c.permissions.allowed
                )
                .split_on(lambda c: c.get_data.type)
                .routes(
                    json=self.process_json,
                    xml=self.process_xml,
                    csv=self.process_csv
                )
        )
    
    @task("api/v1", "fetch")
    def get_data(self):
        return self.params(endpoint="${input.endpoint}")
    
    @task("validator/v1", "validate")  
    def validate(self):
        return self.depends_on(self.get_data) \
                   .fail_if(lambda c: c.get_data.error != None)
```

## Ultimate: Decorator Factory Pattern

```python
from gleitzeit import workflow, make_task

@workflow
class UltimateWorkflow:
    
    # Decorator factory creates custom decorators
    validate_age = make_task("validator/v1", "check_age") \
                      .when(lambda c: c.user.age != None) \
                      .fail_if(lambda c: c.user.age < 0, "Invalid age")
    
    check_premium = make_task("condition/v1", "is_premium") \
                       .when(lambda c: c.user.tier == "premium")
    
    @validate_age  # Use custom decorator
    @check_premium  # Stack decorators
    def process_premium_user(self):
        return self.task("processor/v1", "premium") \
                   .params(features="all")
    
    @validate_age
    .skip_if(lambda c: c.result < 18)  # Chain on decorator!
    def adult_content(self):
        return self.task("content/v1", "adult")
```

## Real-World Example: Complete Order Flow

```python
from gleitzeit import workflow, task

@workflow
class OrderWorkflow:
    
    @task("api/v1", "fetch")
    def get_order(self, order_id: str):
        return self.params(order_id=order_id) \
                   .cache(ttl=60) \
                   .fail_if(lambda c: c.result == None, "Order not found")
    
    @task("api/v1", "fetch")
    def get_customer(self):
        return self.depends_on(self.get_order) \
                   .params(customer_id="${get_order.customer_id}") \
                   .cache(ttl=300)
    
    @task("inventory/v1", "check")
    def check_inventory(self):
        return self.depends_on(self.get_order) \
                   .params(items="${get_order.items}") \
                   .parallel_with(self.get_customer)  # Run parallel
    
    @task("fraud/v1", "check")
    def check_fraud(self):
        return self.after_all([self.get_order, self.get_customer]) \
                   .timeout(10) \
                   .on_timeout(lambda: {"score": 50})  # Default on timeout
    
    @task("pricing/v1", "calculate")
    def calculate_total(self):
        return self.depends_on(self.get_order) \
                   .when(lambda c: c.get_customer.tier == "premium") \
                   .then(lambda: self.params(discount=0.2)) \
                   .otherwise(lambda: self.params(discount=0))
    
    @task("payment/v1", "charge")
    def charge_payment(self):
        return self.after_all([
                       self.check_inventory,
                       self.check_fraud,
                       self.calculate_total
                   ]) \
                   .guards(
                       lambda c: c.check_inventory.available,
                       lambda c: c.check_fraud.score < 80,
                       lambda c: c.calculate_total.amount > 0
                   ) \
                   .retry(
                       max_attempts=3,
                       backoff="exponential",
                       on_retry=self.log_retry
                   ) \
                   .on_success(self.send_receipt) \
                   .on_failure(self.handle_payment_failure)
    
    @task("shipping/v1", "ship")
    def ship_order(self):
        return self.depends_on(self.charge_payment) \
                   .when(lambda c: c.charge_payment.success) \
                   .switch_on(lambda c: c.get_customer.tier) \
                   .cases(
                       premium=lambda: self.params(method="express"),
                       regular=lambda: self.params(method="standard")
                   )
```

## Implementation Sketch

```python
class FluentTask:
    """Task builder with fluent interface"""
    
    def __init__(self, protocol: str, method: str):
        self.protocol = protocol
        self.method = method
        self._conditions = []
        self._dependencies = []
        self._guards = []
        self._params = {}
    
    def when(self, condition):
        self._conditions.append(condition)
        return self  # Enable chaining
    
    def depends_on(self, *tasks):
        self._dependencies.extend(tasks)
        return self
    
    def guards(self, *guards):
        self._guards.extend(guards)
        return self
    
    def params(self, **kwargs):
        self._params.update(kwargs)
        return self
    
    def retry(self, max_attempts=3, backoff="linear", on_retry=None):
        self._retry_config = {
            "max_attempts": max_attempts,
            "backoff": backoff,
            "on_retry": on_retry
        }
        return self
    
    def __call__(self, func):
        """Allow use as decorator"""
        # Attach fluent config to function
        func._task_config = self
        return func

# Decorator factory
def task(protocol: str, method: str):
    """Create a fluent task decorator"""
    return FluentTask(protocol, method)
```

## Benefits of Fluent + Decorators

1. **Best of Both Worlds** - Decorators for structure, fluent for configuration
2. **Readable** - Decorators show workflow structure at a glance
3. **Flexible** - Chain methods for complex conditions
4. **Composable** - Mix patterns as needed
5. **IDE-Friendly** - Full autocomplete and type checking
6. **Testable** - Each decorated method is testable

This hybrid approach gives you the clarity of decorators with the expressiveness of fluent APIs!