# Signals Implementation for Gleitzeit

## Executive Summary

Signals allow external systems and users to interact with running workflows in real-time. This design shows how to implement Temporal-style signals in Gleitzeit using our existing Redis Streams infrastructure, adding a critical enterprise feature with minimal complexity.

**Key Benefits:**
- **Runtime Interaction** - Modify workflow behavior while running
- **Human-in-the-loop** - Enable approval workflows and manual interventions
- **External Integration** - React to webhooks, user actions, system events
- **Zero Architecture Changes** - Uses existing Redis Streams
- **3 Days to Implement** - Leverages current event system

## What Are Signals?

Signals are external events sent to running workflows that can:
- Trigger new tasks
- Cancel or modify execution
- Provide additional data
- Change workflow state
- Enable human decisions

### Temporal.io Example
```go
// Temporal workflow waiting for signal
func OrderWorkflow(ctx workflow.Context) error {
    // Wait for payment confirmation signal
    var paymentConfirmed bool
    signalChan := workflow.GetSignalChannel(ctx, "payment-confirmed")
    signalChan.Receive(ctx, &paymentConfirmed)
    
    if paymentConfirmed {
        // Continue with order
    }
}
```

### Gleitzeit Equivalent (Proposed)
```python
t("wait_for_payment", "signal/v1:wait")
    .with_(signal="payment_confirmed", timeout=3600)
    .on_signal("payment_confirmed")
        .run("process_order", "order/v1:process")
    .on_timeout()
        .run("cancel_order", "order/v1:cancel")
```

## Complete Signal Syntax

### 1. Waiting for Signals
```python
# Simple signal wait
t("wait_approval", "signal/v1:wait")
    .with_(signal="manager_approval")
    .timeout(86400)  # 24 hours

# Wait with payload
t("wait_for_data", "signal/v1:wait")
    .with_(signal="external_data")
    .on_signal()
        .run("process_data", "processor/v1:run")
        .with_(data="${signal.payload.data}")
```

### 2. Inline Signal Handlers
```python
# React to signals at any point
t("long_running_process", "processor/v1:run")
    .on_signal("cancel")
        .run("cleanup", "cleanup/v1:run")
        .terminate()  # Stop workflow
    
    .on_signal("pause")
        .pause()  # Pause workflow
    
    .on_signal("update_config")
        .run("apply_config", "config/v1:update")
        .with_(config="${signal.payload.config}")
```

### 3. Multiple Signal Patterns
```python
# Wait for any of multiple signals
t("wait_for_decision", "signal/v1:wait_any")
    .with_(signals=["approve", "reject", "escalate"])
    .on_signal("approve")
        .run("process_approval", "approval/v1:process")
    .on_signal("reject")
        .run("handle_rejection", "rejection/v1:process")
    .on_signal("escalate")
        .run("escalate_to_manager", "escalation/v1:create")

# Wait for all signals
t("wait_for_confirmations", "signal/v1:wait_all")
    .with_(signals=["payment_confirmed", "inventory_reserved"])
    .timeout(3600)
    .then()
        .run("ship_order", "shipping/v1:ship")
```

### 4. Signal with Conditions
```python
t("process_order", "order/v1:process")
    .on_signal("modify_order")
        .if_("${signal.payload.amount} > 1000")
        .run("require_approval", "approval/v1:request")
    
    .on_signal("expedite")
        .if_("${customer.tier} == 'premium'")
        .run("upgrade_shipping", "shipping/v1:expedite")
```

## Implementation Architecture

### Signal Flow
```
1. External System sends signal via API
   POST /workflows/{id}/signal
   
2. Signal published to Redis Stream
   XADD workflow:signals:{id} * signal_name "cancel" payload "{...}"
   
3. Signal processor reads stream
   - Finds waiting tasks or handlers
   - Triggers configured actions
   
4. Workflow continues with signal data
   - Tasks can access ${signal.payload.*}
   - Handlers execute based on signal
```

### Redis Structure
```python
# Signal definitions (registered at workflow start)
workflow:123:signals = {
    "cancel": {
        "handlers": ["cleanup_task", "notify_task"],
        "action": "terminate"
    },
    "update_config": {
        "handlers": ["apply_config_task"],
        "action": "continue"
    }
}

# Signal stream (runtime signals)
workflow:signals:123 = [
    {
        "id": "1234567890",
        "signal": "update_config",
        "payload": {"timeout": 30},
        "timestamp": "2024-01-01T12:00:00Z",
        "sender": "user:admin"
    }
]

# Waiting tasks
task:wait_approval:state = {
    "waiting_for": ["manager_approval"],
    "timeout": 86400,
    "started": "2024-01-01T11:00:00Z"
}
```

## Real-World Examples

### 1. Approval Workflow
```python
approval_workflow = w(
    t("submit_request", "request/v1:create")
        .with_(amount="${input.amount}", reason="${input.reason}"),
    
    t("wait_for_approval", "signal/v1:wait")
        .needs("submit_request")
        .with_(signal="manager_decision", timeout=86400)
        .on_signal("manager_decision")
            .if_("${signal.payload.approved}")
            .run("process_approved", "request/v1:approve")
        .on_signal("manager_decision")
            .unless("${signal.payload.approved}")
            .run("process_rejected", "request/v1:reject")
        .on_timeout()
            .run("auto_escalate", "escalation/v1:create"),
    
    t("execute_request", "executor/v1:run")
        .needs("process_approved")
)
```

### 2. Human-in-the-Loop LLM
```python
llm_workflow = w(
    t("generate_content", "llm/v1:generate")
        .with_(prompt="${input.prompt}")
        .on_signal("human_feedback")
            .run("incorporate_feedback", "llm/v1:refine")
            .with_(
                original="${result}",
                feedback="${signal.payload.feedback}"
            ),
    
    t("wait_for_review", "signal/v1:wait")
        .needs("generate_content")
        .with_(signal="content_approved", timeout=3600)
        .on_signal("content_approved")
            .run("publish_content", "publisher/v1:publish")
        .on_signal("request_revision")
            .run("revise_content", "llm/v1:generate")
            .with_(
                prompt="${signal.payload.revision_prompt}",
                context="${generate_content.result}"
            )
)
```

### 3. Order Processing with Cancellation
```python
order_workflow = w(
    t("process_payment", "payment/v1:charge")
        .with_(amount="${input.amount}")
        .on_signal("cancel_order")
            .run("refund_payment", "payment/v1:refund")
            .terminate(),
    
    t("prepare_shipment", "warehouse/v1:prepare")
        .needs("process_payment")
        .on_signal("cancel_order")
            .run("return_to_inventory", "inventory/v1:return")
            .terminate(),
    
    t("ship_order", "shipping/v1:ship")
        .needs("prepare_shipment")
        .on_signal("modify_shipping")
            .run("update_shipping", "shipping/v1:update")
            .with_(method="${signal.payload.shipping_method}")
)
```

### 4. Dynamic Workflow Modification
```python
dynamic_workflow = w(
    t("start_processing", "processor/v1:start")
        .on_signal("add_step")
            .run("dynamic_task", "${signal.payload.protocol}")
            .with_("${signal.payload.params}"),
    
    t("main_process", "processor/v1:run")
        .needs("start_processing")
        .on_signal("change_config")
            .update_params(config="${signal.payload.config}")
        .on_signal("pause_processing")
            .pause()
        .on_signal("resume_processing")
            .resume()
)
```

## Implementation Details

### 1. Signal Task Protocol
```python
# New protocol for signal operations
class SignalProtocol:
    """signal/v1 protocol for workflow signals"""
    
    async def wait(self, signal: str, timeout: int = None) -> Dict:
        """Wait for a signal"""
        # Block until signal received or timeout
        result = await redis.blpop(f"signal:{workflow_id}:{signal}", timeout)
        return json.loads(result) if result else None
    
    async def wait_any(self, signals: List[str], timeout: int = None) -> Dict:
        """Wait for any of the signals"""
        keys = [f"signal:{workflow_id}:{s}" for s in signals]
        result = await redis.blpop(keys, timeout)
        return json.loads(result[1]) if result else None
    
    async def wait_all(self, signals: List[str], timeout: int = None) -> List[Dict]:
        """Wait for all signals"""
        results = []
        for signal in signals:
            result = await self.wait(signal, timeout)
            if not result and timeout:
                raise TimeoutError(f"Signal {signal} not received")
            results.append(result)
        return results
```

### 2. Signal Handler Registration
```python
class TaskBuilder:
    def on_signal(self, signal_name: str):
        """Register signal handler"""
        handler = SignalHandler(self.task["id"], signal_name)
        self._signal_handlers.append(handler)
        return handler

class SignalHandler:
    def run(self, task_id: str, protocol: str):
        """Queue task when signal received"""
        self.actions.append({
            "task_id": task_id,
            "protocol": protocol,
            "trigger": "signal"
        })
        return self
    
    def terminate(self):
        """Terminate workflow on signal"""
        self.actions.append({"action": "terminate"})
        return self
    
    def pause(self):
        """Pause workflow on signal"""
        self.actions.append({"action": "pause"})
        return self
```

### 3. Signal Processor
```python
async def process_signals():
    """Process signals from Redis stream"""
    while True:
        # Read from signal streams
        signals = await redis.xread({
            "workflow:signals:*": "$"
        }, block=1000)
        
        for stream, messages in signals.items():
            workflow_id = stream.split(":")[-1]
            
            for message_id, data in messages:
                signal_name = data["signal_name"]
                payload = json.loads(data["payload"])
                
                # Find registered handlers
                handlers = await get_signal_handlers(workflow_id, signal_name)
                
                for handler in handlers:
                    if handler["action"] == "terminate":
                        await terminate_workflow(workflow_id)
                    elif handler["action"] == "pause":
                        await pause_workflow(workflow_id)
                    elif handler["action"] == "run_task":
                        await queue_task(
                            handler["task_id"],
                            handler["protocol"],
                            {**handler["params"], "signal": {"payload": payload}}
                        )
                
                # Wake up waiting tasks
                await redis.lpush(
                    f"signal:{workflow_id}:{signal_name}",
                    json.dumps(payload)
                )
```

### 4. API Endpoints
```python
# Send signal to workflow
@router.post("/workflows/{workflow_id}/signal")
async def send_signal(
    workflow_id: str,
    signal_name: str,
    payload: Dict = None
):
    """Send signal to running workflow"""
    
    # Validate workflow is running
    status = await redis.hget(f"workflow:{workflow_id}", "status")
    if status not in ["running", "paused"]:
        raise HTTPException(400, "Workflow not running")
    
    # Publish signal to stream
    await redis.xadd(
        f"workflow:signals:{workflow_id}",
        {
            "signal_name": signal_name,
            "payload": json.dumps(payload or {}),
            "timestamp": datetime.utcnow().isoformat(),
            "sender": current_user.id
        }
    )
    
    return {"status": "signal_sent", "workflow_id": workflow_id}

# List available signals
@router.get("/workflows/{workflow_id}/signals")
async def list_signals(workflow_id: str):
    """List registered signals for workflow"""
    signals = await redis.hgetall(f"workflow:{workflow_id}:signals")
    return {
        "workflow_id": workflow_id,
        "signals": list(signals.keys()),
        "details": signals
    }
```

## CLI Support
```bash
# Send signal from CLI
gleitzeit signal send <workflow_id> <signal_name> [--payload '{"key": "value"}']

# Wait for signal (useful in scripts)
gleitzeit signal wait <workflow_id> <signal_name> --timeout 60

# List signals for workflow
gleitzeit signal list <workflow_id>

# Interactive signal sending
gleitzeit signal interactive <workflow_id>
> Select signal: cancel_order
> Enter payload (JSON): {"reason": "Customer request"}
> Signal sent successfully
```

## Replayability Guarantees

Signals remain fully replayable:

1. **Signal History** - All signals stored in Redis stream
2. **Deterministic Order** - Signals processed in received order
3. **Idempotent Handlers** - Signal handlers create tasks with deterministic IDs
4. **Replay Mode** - During replay, signals are replayed from history

```python
# During replay
if is_replay:
    # Load signals from history
    signals = await redis.xrange(f"workflow:signals:{workflow_id}")
    for signal in signals:
        # Re-process in same order
        await process_signal(signal)
else:
    # Normal execution - read from stream
    await process_signals()
```

## Implementation Timeline

### Day 1: Core Signal Infrastructure (8 hours)
- Signal protocol implementation
- Redis stream setup
- Signal processor service
- Basic wait/send functionality

### Day 2: Inline Syntax & Handlers (8 hours)
- TaskBuilder signal extensions
- Signal handler registration
- Event processor integration
- Condition support

### Day 3: API, CLI & Testing (8 hours)
- REST API endpoints
- CLI commands
- Integration tests
- Documentation

## Comparison with Temporal

| Feature | Temporal | Gleitzeit (with Signals) |
|---------|----------|-------------------------|
| Signal Support | ✅ Native | ✅ Full support |
| Signal Queries | ✅ Yes | ✅ Via API |
| Signal History | ✅ Built-in | ✅ Redis Streams |
| Replay with Signals | ✅ Yes | ✅ Yes |
| Signal Conditions | ✅ In code | ✅ Task-based |
| Multiple Signals | ✅ Channels | ✅ wait_any/wait_all |
| Signal Timeouts | ✅ Yes | ✅ Yes |
| Cross-workflow Signals | ✅ Yes | ✅ Yes |

## Benefits Summary

✅ **Closes Major Gap** - Adds critical Temporal feature  
✅ **Human-in-the-Loop** - Enables approval workflows  
✅ **External Integration** - React to webhooks, events  
✅ **Zero Breaking Changes** - Pure addition  
✅ **Minimal Complexity** - Uses existing infrastructure  
✅ **Fast Implementation** - 3 days to production  
✅ **Fully Replayable** - Maintains determinism  

## Conclusion

Signals are a natural fit for Gleitzeit's architecture:
- **Redis Streams** already handle events perfectly
- **Task-based approach** makes signal handlers clean
- **Inline syntax** keeps workflows readable
- **Existing infrastructure** means fast implementation

With signals, Gleitzeit becomes a serious Temporal alternative for Python-first teams needing human-in-the-loop and external integration capabilities.

The implementation is straightforward, the syntax is clean, and it dramatically increases the types of workflows Gleitzeit can handle - making it truly enterprise-ready for modern async workflow needs.