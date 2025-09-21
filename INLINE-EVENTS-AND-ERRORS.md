# Inline Events and Error Handling in Task Chains

## The Vision: Everything in the Chain

Instead of separate event handlers, attach error handling and event reactions directly to tasks:

```python
# Complete inline style - everything in one chain!
t("charge_payment", "payment/v1:charge")
    .needs("validate_order")
    .with_(amount="${order.total}")
    .retry(3)
    .on_error("INSUFFICIENT_FUNDS", "notify_customer", "email/v1:send")  # React to specific error
    .on_error("CARD_DECLINED", "try_backup_payment", "payment/v1:charge")
    .on_timeout("alert_ops", "pagerduty/v1:alert")
    .on_success("send_receipt", "email/v1:send")
    .on_failure("restore_inventory", "inventory/v1:release")
```

## Complete Inline Event Syntax

### 1. Error-Specific Handlers
```python
t("process_payment", "payment/v1:charge")
    .with_(amount="${order.total}")
    .on_error("INSUFFICIENT_FUNDS")
        .run("notify_nsf", "email/v1:send")
        .with_(template="insufficient_funds")
    .on_error("CARD_EXPIRED")
        .run("request_update", "email/v1:send")
        .with_(template="update_payment_method")
    .on_error("RATE_LIMITED")
        .wait(60)
        .retry_self()  # Retry this task
```

### 2. Standard Event Handlers
```python
t("risky_operation", "api/v1:call")
    .on_success()
        .run("log_success", "audit/v1:log")
        .run("update_metrics", "metrics/v1:increment")
    .on_failure()
        .run("compensate", "cleanup/v1:run")
        .run("alert_team", "slack/v1:notify")
    .on_timeout()
        .run("use_fallback", "api/v2:call")
    .on_retry()
        .run("log_retry", "monitoring/v1:log")
```

### 3. Conditional Event Handlers
```python
t("generate_content", "llm/v1:generate")
    .with_(prompt="${input.prompt}")
    .on_error("TOKEN_LIMIT_EXCEEDED")
        .run("retry_smaller", "llm/v1:generate")
        .with_(model="gpt-3.5-turbo")
    .on_failure()
        .if_("${retry_count} >= 3")
        .run("escalate", "support/v1:ticket")
    .on_success()
        .if_("${result.flagged}")
        .run("review", "moderation/v1:queue")
```

### 4. Chained Reactions
```python
t("charge_payment", "payment/v1:charge")
    .on_failure()
        .run("restore_inventory", "inventory/v1:release")
            .on_success()
                .run("notify_restored", "log/v1:info")
            .on_failure()
                .run("alert_critical", "pagerduty/v1:alert")
```

### 5. Promise-Style (then/catch/finally)
```python
t("critical_operation", "critical/v1:process")
    .then()  # On success
        .run("celebrate", "metrics/v1:success")
        .run("continue_flow", "next/v1:step")
    .catch()  # On any error
        .run("cleanup", "cleanup/v1:run")
        .run("notify", "alert/v1:send")
    .finally()  # Always runs
        .run("log_complete", "audit/v1:log")
```

## Implementation Approach

### TaskBuilder Extensions
```python
class TaskBuilder:
    def __init__(self, id: str, run: str):
        self.task = {"id": id, "run": run}
        self._event_handlers = []
        self._error_handlers = {}
    
    def on_error(self, error_code: str = None):
        """Handle specific error or any error"""
        handler = ErrorHandler(self.task["id"], error_code)
        self._error_handlers[error_code or "*"] = handler
        return handler
    
    def on_success(self):
        """Handle successful completion"""
        handler = EventHandler(self.task["id"], "success")
        self._event_handlers.append(handler)
        return handler
    
    def on_failure(self):
        """Handle any failure"""
        handler = EventHandler(self.task["id"], "failure")
        self._event_handlers.append(handler)
        return handler
    
    def on_timeout(self):
        """Handle timeout"""
        handler = EventHandler(self.task["id"], "timeout")
        self._event_handlers.append(handler)
        return handler
    
    def then(self):
        """Promise-style success handler"""
        return self.on_success()
    
    def catch(self, error_code: str = None):
        """Promise-style error handler"""
        return self.on_error(error_code)
    
    def finally_(self):
        """Always runs regardless of outcome"""
        handler = EventHandler(self.task["id"], "completed")
        self._event_handlers.append(handler)
        return handler

class EventHandler:
    """Fluent handler for events"""
    def __init__(self, task_id: str, event_type: str):
        self.task_id = task_id
        self.event_type = event_type
        self.actions = []
        self.condition = None
    
    def run(self, task_id: str, protocol: str):
        """Queue a task on this event"""
        action = {
            "task_id": task_id,
            "protocol": protocol,
            "params": {}
        }
        self.actions.append(action)
        return self
    
    def with_(self, **params):
        """Add parameters to last action"""
        if self.actions:
            self.actions[-1]["params"] = params
        return self
    
    def if_(self, condition: str):
        """Only trigger if condition is true"""
        self.condition = condition
        return self
    
    def wait(self, seconds: int):
        """Wait before continuing"""
        self.run("wait", "timer/v1:sleep").with_(seconds=seconds)
        return self
    
    def retry_self(self):
        """Retry the original task"""
        self.run(f"retry_{self.task_id}", "retry/v1:retry").with_(task_id=self.task_id)
        return self

class ErrorHandler(EventHandler):
    """Handler specifically for errors"""
    def __init__(self, task_id: str, error_code: str = None):
        super().__init__(task_id, "error")
        self.error_code = error_code
```

### How It Expands

When compiled, inline event handlers become event listener registrations:

```python
# Your code:
t("charge_payment", "payment/v1:charge")
    .on_error("INSUFFICIENT_FUNDS")
        .run("notify_customer", "email/v1:send")
    .on_success()
        .run("send_receipt", "email/v1:send")

# Generates:
{
    "task": {
        "id": "charge_payment",
        "protocol": "payment/v1",
        "method": "charge"
    },
    "event_listeners": [
        {
            "event": "task:failed",
            "filter": "task_id == 'charge_payment' AND error_code == 'INSUFFICIENT_FUNDS'",
            "actions": [
                {"task": "notify_customer", "protocol": "email/v1:send"}
            ]
        },
        {
            "event": "task:completed",
            "filter": "task_id == 'charge_payment'",
            "actions": [
                {"task": "send_receipt", "protocol": "email/v1:send"}
            ]
        }
    ]
}
```

### Integration with Event Processor

```python
# Event processor reads the registered handlers
async def process_task_event(event):
    """Process events using registered inline handlers"""
    
    task_id = event["task_id"]
    event_type = event["event_type"]  # task:failed, task:completed, etc.
    
    # Find inline handlers for this task
    handlers = get_inline_handlers(task_id, event_type)
    
    for handler in handlers:
        # Check error code if specified
        if handler.error_code:
            if event.get("error_code") != handler.error_code:
                continue
        
        # Check condition if specified
        if handler.condition:
            if not evaluate_condition(handler.condition, event):
                continue
        
        # Execute actions
        for action in handler.actions:
            await queue_task(
                action["task_id"],
                action["protocol"],
                action["params"]
            )
```

## Complete Real-World Example

```python
from gleitzeit.easy import t, w

order_workflow = w(
    # Validate with inline error handling
    t("validate_order", "validator/v1:check")
        .with_(order="${input.order}")
        .on_failure()
            .run("log_validation_error", "audit/v1:log")
            .run("return_error", "response/v1:error"),
    
    # Check fraud with conditional reactions
    t("check_fraud", "fraud/v1:assess")
        .needs("validate_order")
        .with_(order="${input.order}")
        .on_success()
            .if_("${result.score} > 70")
            .run("flag_for_review", "review/v1:queue"),
    
    # Check inventory with compensations
    t("check_inventory", "inventory/v1:check")
        .needs("validate_order")
        .with_(items="${order.items}")
        .on_error("OUT_OF_STOCK")
            .run("suggest_alternatives", "recommendation/v1:find")
            .run("notify_backorder", "email/v1:send"),
    
    # Payment with comprehensive error handling
    t("charge_payment", "payment/v1:charge")
        .needs("check_fraud", "check_inventory")
        .with_(amount="${order.total}")
        .retry(3)
        .fail_if("${check_fraud.score} > 90", "High fraud risk")
        .skip_if("${order.total} == 0", "Free order")
        
        # Error-specific handlers
        .on_error("INSUFFICIENT_FUNDS")
            .run("notify_nsf", "email/v1:send")
                .with_(template="nsf_notice")
            .run("suspend_order", "order/v1:suspend")
        
        .on_error("CARD_EXPIRED")
            .run("request_update", "email/v1:send")
                .with_(template="update_card")
        
        .on_error("RATE_LIMITED")
            .wait(60)
            .retry_self()
        
        # Standard handlers
        .on_success()
            .run("send_receipt", "email/v1:send")
                .with_(template="payment_receipt")
            .run("update_accounting", "ledger/v1:record")
        
        .on_failure()
            .if_("${retry_count} >= 3")
            .run("escalate_to_support", "support/v1:ticket")
            .run("restore_inventory", "inventory/v1:release")
        
        .on_timeout()
            .run("try_backup_gateway", "payment/v2:charge")
                .with_(gateway="backup"),
    
    # Shipping with promise-style
    t("ship_order", "shipping/v1:ship")
        .needs("charge_payment")
        .when("${charge_payment.success}")
        .with_(order="${order}")
        
        .then()  # Success
            .run("send_tracking", "email/v1:send")
                .with_(template="tracking_info")
            .run("update_inventory", "inventory/v1:decrement")
        
        .catch("CARRIER_ERROR")  # Specific error
            .run("try_alternate_carrier", "shipping/v2:ship")
        
        .catch()  # Any other error
            .run("notify_shipping_issue", "support/v1:alert")
        
        .finally()  # Always
            .run("log_shipping_attempt", "audit/v1:log")
)
```

## Benefits of Inline Events

1. **Complete Story in One Place** - Task definition includes all reactions
2. **No Separate Handlers** - Everything is in the workflow
3. **Natural Reading** - "charge payment, on error X do Y"
4. **Type Safety** - IDE can validate inline handlers
5. **Debugging** - See all behaviors at task definition

## Comparison with Separate Handlers

### Separate Event Handlers (Current):
```python
# Workflow definition
t("charge_payment", "payment/v1:charge")

# Somewhere else...
@on("task:failed")
async def handle_payment_failure(event):
    if event["task_id"] == "charge_payment":
        if "INSUFFICIENT_FUNDS" in event["error"]:
            await queue_task("notify_customer")
```

### Inline Event Handlers (Proposed):
```python
# Everything together
t("charge_payment", "payment/v1:charge")
    .on_error("INSUFFICIENT_FUNDS")
        .run("notify_customer", "email/v1:send")
```

## Implementation Strategy

### Phase 1: Basic Inline Events (4 hours)
- Add on_success(), on_failure(), on_error()
- Generate event listener registrations
- Wire to existing event processor

### Phase 2: Conditional Handlers (2 hours)
- Add .if_() to handlers
- Add error code matching
- Add retry_self() helper

### Phase 3: Promise Style (2 hours)
- Add then(), catch(), finally()
- Add chaining support
- Add wait() helper

## Conclusion

Inline events and error handling makes workflows:
- **Self-contained** - Complete behavior in one place
- **Readable** - Natural flow of "do this, then handle that"
- **Maintainable** - No hunting for event handlers
- **Powerful** - Full event-driven capabilities

This completes the vision of everything in the chain - conditions, actions, AND event handling!