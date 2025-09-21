# Replayability Analysis - Inline Events and Conditions

## The Challenge

With inline event handlers and conditions, we need to ensure workflows remain deterministic and replayable.

## Short Answer: YES, Still Replayable!

The key insight: **Everything still becomes tasks** under the hood, so replay works exactly the same.

## How Replay Works

### 1. During Initial Execution

```python
# Your inline code:
t("charge_payment", "payment/v1:charge")
    .fail_if("${balance} < ${amount}", "Insufficient funds")
    .on_error("INSUFFICIENT_FUNDS")
        .run("notify_customer", "email/v1:send")
    .on_success()
        .run("send_receipt", "email/v1:send")
```

**Expands to these tasks at workflow start:**
```json
[
    {
        "id": "charge_payment_fail_check",
        "protocol": "fail/v1",
        "method": "evaluate",
        "params": {"condition": "${balance} < ${amount}"}
    },
    {
        "id": "charge_payment",
        "protocol": "payment/v1",
        "method": "charge"
    }
]
```

**Event handlers registered in Redis:**
```json
{
    "workflow:123:listeners": {
        "task:failed": {
            "filter": "task_id == 'charge_payment' AND error_code == 'INSUFFICIENT_FUNDS'",
            "action": "queue_task('notify_customer')"
        }
    }
}
```

### 2. During Replay

```python
# Replay sees the SAME expanded tasks
# Event handlers are re-registered identically
# Everything replays deterministically
```

## Deterministic Replay Guarantees

### ✅ **What IS Replayable:**

1. **Task Execution Order**
   ```python
   # These always create the same task graph
   t("task1").needs("task2").fail_if("${x} > 5")
   # Creates: task2 → fail_check → task1
   ```

2. **Condition Evaluations**
   ```python
   # Conditions are tasks with stored results
   .if_("${customer.tier} == 'premium'")
   # Creates condition task with result: true/false
   ```

3. **Event-Triggered Tasks**
   ```python
   # Event creates new task with unique ID
   .on_error("INSUFFICIENT_FUNDS")
       .run("notify_customer")
   # Creates: notify_customer_[timestamp]_[uuid]
   ```

4. **Error Paths**
   ```python
   # Errors and their handlers are deterministic
   raise TokenLimitError(5000, 4000)
   # Always triggers same error handlers
   ```

### ❌ **What Could Break Replay (and Solutions):**

1. **Non-Deterministic Task IDs**
   ```python
   # Problem:
   task_id = f"task_{random.random()}"
   
   # Solution: Use deterministic IDs
   task_id = f"task_{workflow_id}_{sequence_number}"
   ```

2. **Time-Based Conditions**
   ```python
   # Problem:
   .if_("${now()} > '2024-01-01'")  # Different on replay!
   
   # Solution: Capture time at start
   .if_("${workflow.start_time} > '2024-01-01'")
   ```

3. **External State Changes**
   ```python
   # Problem:
   .if_("${external_api.status} == 'up'")  # Might change!
   
   # Solution: Capture state in task result
   t("check_api_status", "monitor/v1:check")
   .if_("${check_api_status.result} == 'up'")
   ```

## Replay Scenarios

### Scenario 1: Task Fails, Triggers Error Handler

**Original Execution:**
```
1. charge_payment → fails with INSUFFICIENT_FUNDS
2. Event emitted to stream
3. Handler queues notify_customer task
4. notify_customer executes
```

**Replay:**
```
1. charge_payment → fails with INSUFFICIENT_FUNDS (same error)
2. Event emitted to stream (identical)
3. Handler queues notify_customer task (same task)
4. notify_customer executes (deterministic)
```

### Scenario 2: Conditional Skip

**Original Execution:**
```
1. is_premium condition → evaluates to false
2. premium_feature task → skipped
3. Continue with next task
```

**Replay:**
```
1. is_premium condition → result loaded from storage (false)
2. premium_feature task → skipped (same decision)
3. Continue with next task (identical flow)
```

### Scenario 3: Event-Driven Compensation

**Original Execution:**
```
1. payment fails
2. on_failure handler triggers
3. restore_inventory task queued
4. restore_inventory executes
```

**Replay:**
```
1. payment fails (same failure)
2. on_failure handler triggers (same registration)
3. restore_inventory task found in history
4. restore_inventory result loaded (no re-execution)
```

## Implementation for Replayability

### 1. Deterministic Task ID Generation
```python
class TaskBuilder:
    def _generate_task_id(self, base: str, suffix: str) -> str:
        """Generate deterministic task IDs"""
        # Use workflow ID and sequence for determinism
        return f"{base}_{suffix}_{self.sequence_number}"
    
    def on_error(self, error_code: str):
        # Deterministic ID for error handler tasks
        handler_id = self._generate_task_id(
            self.task["id"],
            f"on_error_{error_code}"
        )
```

### 2. Event Handler Registration
```python
async def register_workflow_handlers(workflow_id: str, handlers: list):
    """Register handlers in a replayable way"""
    
    # Store handler definitions with workflow
    await redis.hset(
        f"workflow:{workflow_id}:handlers",
        "definition",
        json.dumps(handlers)  # Store for replay
    )
    
    # On replay, re-register identical handlers
    if is_replay:
        handlers = await redis.hget(
            f"workflow:{workflow_id}:handlers",
            "definition"
        )
        await register_handlers(json.loads(handlers))
```

### 3. Task Result Storage
```python
async def execute_task(task: Task):
    """Execute task with replay support"""
    
    # Check if already executed (replay)
    result = await redis.hget(
        f"task:{task.id}:result",
        "data"
    )
    
    if result and is_replay:
        # Don't re-execute, use stored result
        return json.loads(result)
    
    # Execute and store for replay
    result = await provider.execute(task)
    await redis.hset(
        f"task:{task.id}:result",
        "data",
        json.dumps(result)
    )
    return result
```

## Replay Best Practices

### 1. **Immutable Workflow Definition**
```python
# Store expanded workflow at start
await redis.set(
    f"workflow:{workflow_id}:definition",
    json.dumps(expanded_workflow)
)

# On replay, use stored definition
if is_replay:
    workflow = await redis.get(f"workflow:{workflow_id}:definition")
```

### 2. **Capture External State**
```python
# Instead of:
.if_("${api.is_available}")

# Do:
t("check_api", "monitor/v1:check")
.if_("${check_api.available}")  # Use task result
```

### 3. **Versioned Handlers**
```python
# Version your error handlers
.on_error("INSUFFICIENT_FUNDS")
    .version("v1")  # Can update handlers without breaking old replays
    .run("notify_customer_v1")
```

### 4. **Idempotent Operations**
```python
# Make sure retried tasks are idempotent
t("send_email", "email/v1:send")
    .with_(
        idempotency_key="${workflow_id}_${task_id}",
        # Email service checks if already sent
    )
```

## Testing Replay

```python
async def test_workflow_replay():
    """Test that workflow replays identically"""
    
    # Run workflow first time
    workflow_id = await run_workflow(test_workflow)
    original_events = await get_workflow_events(workflow_id)
    original_results = await get_workflow_results(workflow_id)
    
    # Clear execution state (keep results)
    await clear_execution_state(workflow_id)
    
    # Replay workflow
    await replay_workflow(workflow_id)
    replay_events = await get_workflow_events(workflow_id)
    replay_results = await get_workflow_results(workflow_id)
    
    # Should be identical
    assert original_events == replay_events
    assert original_results == replay_results
```

## Conclusion

**YES, inline syntax is fully replayable because:**

1. **Everything becomes tasks** - Inline syntax is just sugar
2. **Tasks are deterministic** - Same inputs → same outputs
3. **Event handlers are registered** - Not dynamic, stored in Redis
4. **Results are stored** - Replay uses stored results
5. **Order is preserved** - Task graph is immutable

The inline syntax doesn't change the fundamental architecture - it just makes it prettier to write. Under the hood, it's still the same deterministic, replayable task system!

## Key Takeaway

```python
# This pretty syntax:
t("payment", "payment/v1:charge")
    .fail_if("${amount} > ${limit}")
    .on_error("DECLINED")
        .run("notify")

# Is EXACTLY the same as:
t("payment_fail_check", "fail/v1:evaluate", ...)
t("payment", "payment/v1:charge", ...)
register_handler("task:failed", "payment", "DECLINED", "notify")

# Both are equally replayable!
```