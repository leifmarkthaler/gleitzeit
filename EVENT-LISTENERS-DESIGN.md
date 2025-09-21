# Event Listeners in Workflows

## Simple Event Listener Syntax

Adding event listeners to our chainable builder is straightforward!

## Approach 1: Chain Event Handlers

```python
from gleitzeit.easy import t, w

workflow = w(
    t("process_payment", "payment/v1:charge")
        .with_(amount="${order.total}")
        .on("success", "send_receipt")           # Trigger task on success
        .on("failure", "send_payment_failed")    # Trigger task on failure
        .on("retry", "log_retry_attempt")        # On each retry
        .on("timeout", "handle_timeout"),        # On timeout
    
    t("analyze_document", "llm/v1:analyze")
        .with_(document="${input.doc}")
        .on("started", "update_ui_processing")
        .on("progress", "update_progress_bar")   # For streaming/progress
        .on("completed", "cache_result")
        .on("error", "notify_admin"),
    
    # Event handler tasks
    t("send_receipt", "email/v1:send")
        .with_(template="receipt", to="${customer.email}"),
    
    t("send_payment_failed", "email/v1:send")
        .with_(template="payment_failed", to="${customer.email}")
)
```

## Approach 2: Event Blocks

```python
workflow = w(
    t("process_order", "order/v1:process")
        .needs("validate_order")
        .with_(order="${input.order}")
        .events({
            "success": ["update_inventory", "send_confirmation"],
            "failure": ["restore_inventory", "send_failure_email"],
            "timeout": "escalate_to_support",
            "retry": lambda attempt: f"log_retry_{attempt}",  # Dynamic
        }),
    
    t("charge_payment", "payment/v1:charge")
        .with_(amount="${order.total}")
        .on_success("send_receipt", "update_accounting")  # Multiple handlers
        .on_failure("refund_order")
        .on_any("log_event")  # Catch all events
)
```

## Approach 3: Event Listeners as First-Class Tasks

```python
from gleitzeit.easy import t, w, listener

workflow = w(
    # Main tasks
    t("fetch_data", "api/v1:fetch")
        .with_(url="${input.url}")
        .emit("data_fetched"),  # Emit custom event
    
    t("process_data", "processor/v1:run")
        .needs("fetch_data")
        .emit("processing_complete", data="${result}"),
    
    # Event listener tasks
    listener("data_fetched")  # Listen for event
        .run("cache/v1:store")
        .with_(ttl=3600),
    
    listener("processing_complete")
        .run("notify/v1:send")
        .with_(message="Processing done: ${event.data}"),
    
    listener("*.failed")  # Wildcard listener
        .run("alert/v1:send")
        .with_(severity="high", task="${event.task_id}")
)
```

## Approach 4: Reactive Chains

```python
from gleitzeit.easy import t, w, on

workflow = w(
    t("validate_input", "validator/v1:check")
        .with_(data="${input}")
        .then("process_valid")      # On success, run this
        .catch("handle_invalid")    # On failure, run this
        .finally("cleanup"),        # Always run this
    
    # Using on() for specific events
    on("validate_input.success")
        .run("process_valid", "processor/v1:run")
        .with_(data="${validate_input.result}"),
    
    on("validate_input.failure")
        .run("handle_invalid", "error/v1:handle")
        .with_(errors="${validate_input.errors}"),
    
    on("*.timeout")  # Listen to all timeouts
        .run("alert_ops", "pagerduty/v1:alert")
        .with_(severity="critical")
)
```

## Implementation (Simple Extension!)

```python
class TaskBuilder:
    def __init__(self, id: str, run: str):
        self.task = {"id": id, "run": run}
        self.task["events"] = {}  # Event handlers
    
    # Existing methods...
    
    def on(self, event: str, *handlers):
        """Add event handlers"""
        if event not in self.task["events"]:
            self.task["events"][event] = []
        self.task["events"][event].extend(handlers)
        return self
    
    def on_success(self, *handlers):
        return self.on("success", *handlers)
    
    def on_failure(self, *handlers):
        return self.on("failure", *handlers)
    
    def on_error(self, *handlers):
        return self.on("error", *handlers)
    
    def on_timeout(self, *handlers):
        return self.on("timeout", *handlers)
    
    def on_retry(self, handler):
        return self.on("retry", handler)
    
    def on_any(self, handler):
        """Catch-all event handler"""
        return self.on("*", handler)
    
    def emit(self, event_name: str, **data):
        """Emit custom event"""
        self.task.setdefault("emits", []).append({
            "event": event_name,
            "data": data
        })
        return self
    
    def then(self, *success_tasks):
        """Shorthand for on_success"""
        return self.on_success(*success_tasks)
    
    def catch(self, *error_tasks):
        """Shorthand for on_failure"""
        return self.on_failure(*error_tasks)
    
    def finally_(self, *always_tasks):
        """Tasks to run regardless of outcome"""
        return self.on("completed", *always_tasks)

# Listener builder
class ListenerBuilder:
    def __init__(self, event_pattern: str):
        self.task = {
            "id": f"listener_{event_pattern.replace('*', 'any').replace('.', '_')}",
            "type": "listener",
            "listens_to": event_pattern
        }
    
    def run(self, task_name: str, protocol: str = None):
        self.task["run"] = protocol or task_name
        self.task["id"] = task_name
        return self
    
    def with_(self, **params):
        self.task["with"] = params
        return self
    
    def filter(self, expression: str):
        """Only handle events matching filter"""
        self.task["filter"] = expression
        return self
    
    def throttle(self, seconds: int):
        """Throttle event handling"""
        self.task["throttle"] = seconds
        return self
    
    def debounce(self, seconds: int):
        """Debounce event handling"""
        self.task["debounce"] = seconds
        return self

def listener(event_pattern: str) -> ListenerBuilder:
    return ListenerBuilder(event_pattern)

def on(event_pattern: str) -> ListenerBuilder:
    """Alias for listener"""
    return listener(event_pattern)
```

## Real-World Example: E-commerce with Events

```python
from gleitzeit.easy import t, w, on

order_workflow = w(
    # Main flow
    t("validate_order", "validator/v1:check")
        .with_(order="${input.order}")
        .on_failure("log_validation_error", "notify_customer_invalid")
        .emit("order_validated"),
    
    t("check_inventory", "inventory/v1:check")
        .needs("validate_order")
        .with_(items="${input.order.items}")
        .on("insufficient", "suggest_alternatives")
        .emit("inventory_checked", available="${result.available}"),
    
    t("calculate_pricing", "pricing/v1:calculate")
        .needs("check_inventory")
        .with_(items="${input.order.items}", customer="${input.customer}")
        .on_success("apply_discounts")
        .emit("pricing_calculated", total="${result.total}"),
    
    t("charge_payment", "payment/v1:charge")
        .needs("calculate_pricing")
        .with_(amount="${calculate_pricing.total}")
        .retry(3)
        .on_retry("log_payment_retry")
        .on_success("confirm_order", "update_inventory")
        .on_failure("cancel_order", "notify_payment_failed")
        .timeout(30)
        .on_timeout("queue_manual_review"),
    
    # Event handlers
    on("order_validated")
        .run("update_order_status", "db/v1:update")
        .with_(status="validated", timestamp="${event.timestamp}"),
    
    on("inventory_checked")
        .run("cache_inventory", "cache/v1:set")
        .with_(key="${input.order.id}_inventory", value="${event.available}")
        .filter("${event.available} == true"),  # Only cache if available
    
    on("payment.retry")
        .run("increment_retry_metric", "metrics/v1:increment")
        .with_(metric="payment_retries", tags={"customer": "${input.customer.tier}"}),
    
    # Global error handler
    on("*.error")
        .run("error_handler", "logging/v1:error")
        .with_(
            task="${event.task_id}",
            error="${event.error}",
            context="${event.context}"
        )
        .throttle(60),  # Max once per minute per error type
    
    # Audit all events
    on("*")
        .run("audit_log", "audit/v1:log")
        .with_(
            event="${event.type}",
            task="${event.task_id}",
            timestamp="${event.timestamp}",
            data="${event}"
        )
)
```

## Advanced: Event-Driven Sagas

```python
from gleitzeit.easy import t, w, saga

# Saga pattern with compensating transactions
order_saga = saga(
    t("reserve_inventory", "inventory/v1:reserve")
        .with_(items="${order.items}")
        .compensate("release_inventory"),  # Rollback action
    
    t("charge_payment", "payment/v1:charge")
        .with_(amount="${order.total}")
        .compensate("refund_payment"),
    
    t("create_shipment", "shipping/v1:create")
        .with_(order="${order}")
        .compensate("cancel_shipment"),
    
    # Automatic rollback on failure
    on_failure="rollback"  # Runs compensations in reverse
)
```

## Event Flow Visualization

```yaml
# How events flow through the system
process_payment:
  emits:
    - payment.started
    - payment.success | payment.failure
    - payment.completed
  
  listeners:
    payment.success:
      - send_receipt
      - update_accounting
      - notify_warehouse
    
    payment.failure:
      - send_failure_email
      - restore_inventory
      - log_error
    
    payment.retry:
      - increment_retry_counter
      - check_retry_limit
```

## Expansion Example

```python
# This:
t("charge_payment", "payment/v1:charge")
    .on_success("send_receipt")
    .on_failure("refund_order")

# Expands to:
[
    {
        "id": "charge_payment",
        "protocol": "payment/v1",
        "method": "charge",
        "events": {
            "success": ["send_receipt"],
            "failure": ["refund_order"]
        }
    },
    {
        "id": "charge_payment_success_handler",
        "protocol": "event/v1",
        "method": "on_event",
        "params": {
            "event": "charge_payment.success",
            "trigger_tasks": ["send_receipt"]
        }
    },
    {
        "id": "charge_payment_failure_handler",
        "protocol": "event/v1",
        "method": "on_event",
        "params": {
            "event": "charge_payment.failure",
            "trigger_tasks": ["refund_order"]
        }
    }
]
```

## Benefits of Event-Driven Workflows

1. **Decoupling** - Tasks don't need to know about each other
2. **Flexibility** - Add handlers without changing main flow
3. **Observability** - Every event can be logged/monitored
4. **Resilience** - Automatic retry/compensation patterns
5. **Scalability** - Events can trigger parallel processing

## Integration with Existing Event System

Gleitzeit already has events via Redis Streams, so this just adds a nice syntax on top:

```python
# These event handlers automatically subscribe to Redis Streams
on("task.completed")
    .run("update_metrics", "metrics/v1:track")
    
on("workflow.failed")
    .run("alert_ops", "pagerduty/v1:alert")
    
on("llm.token_limit_exceeded")
    .run("switch_model", "llm/v1:fallback")
```

This gives you powerful event-driven workflows with minimal syntax!