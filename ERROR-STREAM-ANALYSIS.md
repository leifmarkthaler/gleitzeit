# Error Stream Analysis

## Current Error Event System

### ✅ **Errors ARE Already Emitted to Streams!**

Looking at the code, errors are already being emitted:

```python
# In scalable_redis.py:
async def _emit_task_event(self, event_type: str, task: Task):
    stream_key = f"gleitzeit:events:stream:{event_type}"
    event_data = {
        "event_type": event_type,
        "task_id": task.id,
        "workflow_id": task.workflow_id,
        "task_status": str(task.status),
        "error": task.error_message if hasattr(task, 'error_message') else None
    }
    await self._execute("xadd", stream_key, event_data)
```

### Event Types for Errors:

```python
# In core/events.py:
TASK_FAILED = "task:failed"
TASK_TIMEOUT = "task:timeout"
WORKFLOW_FAILED = "workflow:failed"
PROVIDER_ERROR = "provider:error"
```

### When Task Fails:

```python
# Task fails → Status = FAILED → Event emitted
task.status = TaskStatus.FAILED
task.error_message = "Connection timeout"
await save_task(task)  # This triggers emit_task_event("task:failed", task)
```

## 🎯 **How to Consume Error Events**

### 1. **Direct Stream Consumption (Already Works!)**

```python
# Read error events from Redis Stream
async def consume_error_events(redis):
    while True:
        # Read from error streams
        events = await redis.xread({
            "gleitzeit:events:stream:task:failed": "$",
            "gleitzeit:events:stream:task:timeout": "$",
            "gleitzeit:events:stream:workflow:failed": "$"
        }, block=1000)
        
        for stream, messages in events.items():
            for msg_id, data in messages:
                # Process error
                if "task:failed" in stream:
                    await handle_task_failure(data)
```

### 2. **With Event Listeners (Proposed Syntax)**

```python
workflow = w(
    t("risky_operation", "api/v1:call")
        .retry(3),
    
    # Listen for failures
    on("task:failed")
        .filter("${event.task_id} == 'risky_operation'")
        .run("send_alert", "alert/v1:notify")
        .with_(
            error="${event.error}",
            task="${event.task_id}"
        ),
    
    on("task:timeout")
        .run("escalate", "pagerduty/v1:alert")
        .with_(severity="critical"),
    
    # Global error handler
    on("*:failed")
        .run("log_error", "logging/v1:error")
        .with_(
            event="${event}",
            timestamp="${event.timestamp}"
        )
)
```

## 📊 **What's in the Error Stream Now**

### Current Error Event Structure:

```json
{
    "event_type": "task:failed",
    "task_id": "process_payment_123",
    "workflow_id": "order_workflow_456",
    "task_status": "failed",
    "timestamp": "2024-01-01T12:00:00Z",
    "error": "Payment gateway timeout",
    "source": "persistence"
}
```

### Available Error Information:
- ✅ Task/Workflow ID
- ✅ Error message
- ✅ Timestamp
- ✅ Status
- ❌ Stack trace (not included)
- ❌ Retry count (not included)
- ❌ Error code (not structured)

## 🔧 **Improvements Needed**

### 1. **Richer Error Context**

```python
# Enhanced error event
async def emit_task_error(self, task: Task, error: Exception):
    event_data = {
        "event_type": "task:failed",
        "task_id": task.id,
        "workflow_id": task.workflow_id,
        "error": {
            "message": str(error),
            "type": error.__class__.__name__,
            "code": getattr(error, 'code', None),
            "retryable": is_retryable_error(error),
            "stack_trace": traceback.format_exc() if debug else None
        },
        "context": {
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
            "protocol": task.protocol,
            "method": task.method
        }
    }
    await redis.xadd(stream_key, event_data)
```

### 2. **Error Classification**

```python
class ErrorCategory(Enum):
    NETWORK = "network"          # Retryable
    AUTHENTICATION = "auth"       # Not retryable
    VALIDATION = "validation"     # Not retryable
    TIMEOUT = "timeout"          # Retryable
    RATE_LIMIT = "rate_limit"   # Retryable with backoff
    INTERNAL = "internal"        # Maybe retryable
```

### 3. **Structured Error Codes**

```python
# Instead of just string message
error_event = {
    "error": {
        "code": "PAYMENT_GATEWAY_TIMEOUT",
        "message": "Payment gateway did not respond within 30s",
        "category": "timeout",
        "retryable": True,
        "retry_after": 60,
        "details": {
            "gateway": "stripe",
            "amount": 100.00,
            "currency": "USD"
        }
    }
}
```

## 🚀 **How to React to Errors NOW**

### Pattern 1: Retry with Different Config

```python
# When task fails, retry with different model
on("task:failed")
    .filter("${event.task_id} == 'generate_content'")
    .filter("${event.error.code} == 'TOKEN_LIMIT_EXCEEDED'")
    .run("retry_smaller_model", "llm/v1:generate")
    .with_(
        model="gpt-3.5-turbo",
        prompt="${event.context.params.prompt}"
    )
```

### Pattern 2: Circuit Breaker

```python
# Track failures and circuit break
on("task:failed")
    .filter("${event.protocol} == 'payment/v1'")
    .run("increment_failure_count", "redis/v1:incr")
    .with_(key="payment_failures:${event.context.gateway}")
    
on("payment_failures:*")
    .filter("${value} > 10")
    .run("circuit_break", "config/v1:set")
    .with_(
        key="payment.enabled",
        value=False,
        ttl=300  # 5 minutes
    )
```

### Pattern 3: Compensating Transactions

```python
# On failure, run compensation
on("task:failed")
    .filter("${event.task_id} == 'charge_payment'")
    .run("release_inventory", "inventory/v1:release")
    .with_(items="${event.context.reserved_items}")
    .run("notify_customer", "email/v1:send")
    .with_(
        template="payment_failed",
        reason="${event.error.message}"
    )
```

## 📈 **Error Monitoring Dashboard**

```python
# Aggregate error metrics from stream
async def error_metrics():
    # Count by error type
    errors_by_type = await redis.xread(
        "gleitzeit:events:stream:task:failed",
        count=1000
    )
    
    metrics = {
        "total_errors": len(errors_by_type),
        "by_protocol": {},
        "by_error_code": {},
        "retryable": 0,
        "non_retryable": 0
    }
    
    for error in errors_by_type:
        protocol = error.get("protocol")
        metrics["by_protocol"][protocol] += 1
        
        if error.get("retryable"):
            metrics["retryable"] += 1
```

## ✅ **What Works Today**

1. **Errors emit to streams** ✅
2. **Can read with `xread`** ✅
3. **Contains basic error info** ✅
4. **Can filter by type** ✅

## ❌ **What's Missing**

1. **Event listener registration** (need to implement)
2. **Auto task creation from events** (need to implement)
3. **Rich error context** (easy to add)
4. **Error categorization** (easy to add)

## 🎯 **Recommendation**

### Short Term (Works Today):
```python
# Direct stream consumption
async def monitor_errors():
    while True:
        errors = await redis.xread({
            "gleitzeit:events:stream:task:failed": "$"
        })
        for error in errors:
            # React to errors
            if "timeout" in error["error"]:
                await retry_with_longer_timeout(error)
```

### Long Term (After Event System):
```python
# Declarative error handling
on("task:failed")
    .categorize()  # Auto-categorize error
    .retry_if_transient()  # Auto-retry network errors
    .alert_if_critical()  # Page on critical errors
    .compensate()  # Run compensations
```

## Conclusion

**Errors ARE consumable from streams RIGHT NOW!** You can:
1. Read error events from Redis Streams
2. Filter by error type/task/workflow
3. React programmatically

The proposed event listener syntax would make it cleaner, but the infrastructure for error streaming already exists!