# Signals Implementation Plan for Gleitzeit

## Executive Summary

This plan details the implementation of Signals in Gleitzeit, enabling external systems and users to interact with running workflows in real-time. Building on the existing timer implementation pattern and leveraging Redis Streams, we can add this critical enterprise feature with minimal complexity.

## Current State Analysis

### Timer Implementation Pattern (Reference)
Based on the timer implementation, we have established patterns for:

1. **Protocol/Provider Pattern**
   - `TimerProvider` extends `SimpleProvider` with protocol `timer/v1`
   - Returns `TaskStatus.SLEEPING` for non-blocking operations
   - Uses Redis for state persistence

2. **Task Handler Pattern**
   - `TimerTaskHandler` manages timer state in Redis
   - Registers timers in sorted sets (`timers:pending`)
   - Sends events to workflow streams

3. **Monitor Service Pattern**
   - `TimerMonitorService` polls for expired timers
   - Triggers wake events via workflow streams
   - Manages cleanup and TTLs

4. **Integration Pattern**
   - Tasks use protocol `timer/v1` with methods like `sleep`, `wait_until`, `wait_or_signal`
   - Already has basic signal support via `wait_or_signal` method

## Signal Implementation Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        Signal System                             │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────────┐    ┌──────────────────┐                  │
│  │ SignalProvider   │    │ SignalHandler    │                  │
│  │ (signal/v1)      │    │ (Redis ops)      │                  │
│  └────────┬─────────┘    └────────┬─────────┘                  │
│           │                        │                             │
│           ▼                        ▼                             │
│  ┌──────────────────────────────────────────┐                  │
│  │          Redis Infrastructure             │                  │
│  │  • workflow:signals:{id} (stream)         │                  │
│  │  • signal:{id}:waiters (set)              │                  │
│  │  • signal:{id}:handlers (hash)            │                  │
│  └──────────────────────────────────────────┘                  │
│           │                        │                             │
│           ▼                        ▼                             │
│  ┌──────────────────┐    ┌──────────────────┐                  │
│  │ SignalMonitor    │    │ SignalProcessor  │                  │
│  │ (Background)     │    │ (Event handler)  │                  │
│  └──────────────────┘    └──────────────────┘                  │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: Core Signal Infrastructure (Day 1)

#### 1.1 Signal Provider (`src/gleitzeit/providers/signal_provider.py`)
```python
class SignalProvider(SimpleProvider):
    """
    Signal provider for workflow signaling (signal/v1 protocol).
    
    Following the timer provider pattern:
    - Returns SLEEPING status for wait operations
    - Manages signal state in Redis
    - Integrates with existing event system
    """
    
    def __init__(self):
        super().__init__(
            provider_id="signal",
            protocol_id="signal/v1",
            name="Signal Provider",
            description="Handles workflow signals and external events"
        )
        self.supported_methods = [
            "signal/wait",
            "signal/wait_any", 
            "signal/wait_all",
            "signal/send",
            "signal/broadcast"
        ]
```

#### 1.2 Signal Handler (`src/gleitzeit/signals/handler.py`)
```python
class SignalTaskHandler:
    """
    Handles signal operations, following timer handler pattern.
    
    Key operations:
    - Register signal waiters
    - Store signal handlers
    - Process incoming signals
    - Wake waiting tasks
    """
    
    async def handle_wait(self, workflow_id, task_id, params):
        # Register in Redis and return SLEEPING
        signal_name = params.get("signal")
        timeout = params.get("timeout")
        
        # Store in signal waiters set
        await self.redis.sadd(f"signal:{signal_name}:waiters", 
                             f"{workflow_id}:{task_id}")
        
        # Store timeout if specified (use timer infrastructure)
        if timeout:
            await self._register_timeout(workflow_id, task_id, timeout)
        
        return {
            "status": "waiting",
            "signal": signal_name,
            "timeout": timeout
        }
```

#### 1.3 Redis Structure
```python
# Signal waiters (tasks waiting for signal)
signal:approval:waiters = {"workflow123:task456", "workflow789:task012"}

# Signal handlers (inline handlers for running tasks)
workflow:123:signal:handlers = {
    "cancel": {
        "tasks": ["cleanup_task"],
        "action": "terminate"
    },
    "pause": {
        "action": "pause"
    }
}

# Signal stream (incoming signals)
workflow:signals:123 = [
    {
        "id": "sig_123",
        "name": "approval",
        "payload": {"approved": true},
        "sender": "user:admin",
        "timestamp": "2024-01-01T12:00:00Z"
    }
]

# Signal history (for replay)
workflow:123:signal:history = [...]
```

### Phase 2: Signal Processing & Monitoring (Day 1-2)

#### 2.1 Signal Monitor Service (`src/gleitzeit/signals/monitor.py`)
```python
class SignalMonitorService:
    """
    Background service for processing signals.
    Following timer monitor pattern.
    """
    
    async def _process_signals(self):
        # Read from signal streams
        signals = await self.redis.xread({
            "workflow:signals:*": "$"
        }, block=1000)
        
        for stream, messages in signals.items():
            workflow_id = self._extract_workflow_id(stream)
            
            for message_id, data in messages:
                await self._process_signal(workflow_id, data)
    
    async def _process_signal(self, workflow_id, signal_data):
        signal_name = signal_data["name"]
        
        # Wake waiting tasks
        waiters = await self.redis.smembers(f"signal:{signal_name}:waiters")
        for waiter in waiters:
            wf_id, task_id = waiter.split(":")
            if wf_id == workflow_id:
                await self._wake_task(wf_id, task_id, signal_data)
        
        # Process inline handlers
        handlers = await self.redis.hget(
            f"workflow:{workflow_id}:signal:handlers",
            signal_name
        )
        if handlers:
            await self._process_handlers(workflow_id, handlers, signal_data)
```

#### 2.2 Integration with Existing Systems
- Leverage existing `workflow:{id}:events` streams
- Use established task wake patterns from timer system
- Integrate with SystemManager lifecycle

### Phase 3: YAML Workflow Support (Day 2)

#### 3.1 YAML Signal Tasks
```yaml
# Simple signal wait
- name: wait_for_approval
  protocol: signal/v1
  method: signal/wait
  params:
    signal: manager_approval
    timeout: 86400  # 24 hours

# Wait for multiple signals
- name: wait_for_confirmations
  protocol: signal/v1
  method: signal/wait_all
  params:
    signals:
      - payment_confirmed
      - inventory_checked
    timeout: 3600

# Signal with conditional handling (via dependencies)
- name: handle_approval
  protocol: python/v1
  method: python/execute
  params:
    script: process_approval.py
  dependencies:
    - wait_for_approval
  when: "${wait_for_approval.result.payload.approved} == true"
```

#### 3.2 Inline Signal Handlers (Advanced)
```yaml
# Task with signal handlers
- name: long_running_process
  protocol: python/v1
  method: python/execute
  params:
    script: process.py
  signal_handlers:
    cancel:
      action: terminate
      cleanup_task: cleanup
    pause:
      action: pause
    update_config:
      action: run_task
      task:
        name: apply_config
        protocol: config/v1
        params:
          config: "${signal.payload.config}"
```

### Phase 4: API & CLI Integration (Day 2-3)

#### 4.1 API Endpoints (`src/gleitzeit/api/routes/signals.py`)
```python
@router.post("/workflows/{workflow_id}/signal")
async def send_signal(
    workflow_id: str,
    request: SignalRequest,
    current_user: Dict = Depends(get_current_user_auto)
):
    """Send signal to running workflow."""
    # Validate workflow state
    workflow = await get_workflow(workflow_id)
    if workflow.status not in ["running", "paused", "sleeping"]:
        raise HTTPException(400, "Workflow not in signalable state")
    
    # Publish to signal stream
    await redis.xadd(
        f"workflow:signals:{workflow_id}",
        {
            "name": request.signal_name,
            "payload": json.dumps(request.payload),
            "sender": current_user["id"],
            "timestamp": datetime.utcnow().isoformat()
        }
    )
    
    return {"status": "sent", "workflow_id": workflow_id}

@router.get("/workflows/{workflow_id}/signals")
async def list_signals(workflow_id: str):
    """List available signals and waiting tasks."""
    # Get registered handlers
    handlers = await redis.hgetall(f"workflow:{workflow_id}:signal:handlers")
    
    # Get waiting tasks
    waiting = []
    for key in await redis.scan_iter("signal:*:waiters"):
        signal_name = key.split(":")[1]
        waiters = await redis.smembers(key)
        for waiter in waiters:
            if waiter.startswith(f"{workflow_id}:"):
                waiting.append({"signal": signal_name, "task": waiter.split(":")[1]})
    
    return {
        "workflow_id": workflow_id,
        "handlers": handlers,
        "waiting_tasks": waiting
    }
```

#### 4.2 CLI Commands (`src/gleitzeit/cli/signals.py`)
```python
@click.group()
def signal():
    """Manage workflow signals."""
    pass

@signal.command()
@click.argument("workflow_id")
@click.argument("signal_name")
@click.option("--payload", type=json.loads, default={})
def send(workflow_id, signal_name, payload):
    """Send signal to workflow."""
    client = get_client()
    result = client.send_signal(workflow_id, signal_name, payload)
    click.echo(f"Signal sent: {result}")

@signal.command()
@click.argument("workflow_id")
def list(workflow_id):
    """List signals for workflow."""
    client = get_client()
    signals = client.list_signals(workflow_id)
    # Format and display
```

### Phase 5: Testing & Documentation (Day 3)

#### 5.1 Test Scenarios
```python
# Test signal wait and receive
async def test_signal_wait():
    workflow = submit_workflow({
        "tasks": [{
            "name": "wait_approval",
            "protocol": "signal/v1",
            "method": "wait",
            "params": {"signal": "approval"}
        }]
    })
    
    # Task should be sleeping
    assert workflow.tasks["wait_approval"].status == TaskStatus.SLEEPING
    
    # Send signal
    send_signal(workflow.id, "approval", {"approved": True})
    
    # Task should complete
    await wait_for_task(workflow.id, "wait_approval")
    assert workflow.tasks["wait_approval"].status == TaskStatus.COMPLETED

# Test timeout
async def test_signal_timeout():
    workflow = submit_workflow({
        "tasks": [{
            "name": "wait_approval",
            "protocol": "signal/v1",
            "method": "wait",
            "params": {"signal": "approval", "timeout": 1}
        }]
    })
    
    # Wait for timeout
    await asyncio.sleep(2)
    
    # Task should timeout
    assert workflow.tasks["wait_approval"].status == TaskStatus.FAILED
    assert "timeout" in workflow.tasks["wait_approval"].error
```

#### 5.2 Documentation Updates
- Update README with signal examples
- Add signal section to workflow guide
- Create signal best practices document

## Integration with Existing Features

### Leverage Timer Infrastructure
The timer system already has `wait_or_signal` support:
```python
# In TimerTaskHandler
async def handle_wait_or_signal(self, workflow_id, task_id, params):
    signal = params.get("signal", f"signal_{task_id}")
    # Register signal waiter
    await self.redis.sadd(f"signal:{signal}:waiters", f"{workflow_id}:{task_id}")
```

We can extend this pattern for dedicated signal operations.

### Event System Integration
- Use existing `workflow:{id}:events` streams
- Leverage EventBus for signal propagation
- Maintain event ordering for deterministic replay

### Task Status Management
- Use `TaskStatus.SLEEPING` for waiting tasks (like timers)
- Wake tasks via existing wake event mechanism
- Maintain task state consistency

## Implementation Priority

### High Priority (Core Features)
1. ✅ Basic signal wait/send functionality
2. ✅ Integration with existing timer `wait_or_signal`
3. ✅ API endpoints for sending signals
4. ✅ CLI support for basic operations

### Medium Priority (Enhanced Features)
1. ⏳ Multiple signal patterns (wait_any, wait_all)
2. ⏳ Signal handlers for running tasks
3. ⏳ Signal history and replay support
4. ⏳ WebSocket real-time signal updates

### Low Priority (Advanced Features)
1. ⏸️ Cross-workflow signals
2. ⏸️ Signal queries and filtering
3. ⏸️ Signal scheduling (delayed signals)
4. ⏸️ Signal batching and aggregation

## Risk Mitigation

### Technical Risks
1. **Race Conditions**
   - Mitigation: Use Redis atomic operations
   - Follow established patterns from timer system

2. **Signal Ordering**
   - Mitigation: Use Redis Streams for ordered delivery
   - Process signals sequentially per workflow

3. **Memory Usage**
   - Mitigation: Set TTLs on signal data
   - Clean up completed signal waiters

### Operational Risks
1. **Signal Flooding**
   - Mitigation: Rate limiting on signal API
   - Max signals per workflow configuration

2. **Orphaned Waiters**
   - Mitigation: Cleanup service for expired waiters
   - Timeout all signal waits

## Success Metrics

### Functional Metrics
- ✅ Signal wait/send working end-to-end
- ✅ Timeout handling correct
- ✅ Multiple signal patterns supported
- ✅ CLI and API fully functional

### Performance Metrics
- Signal delivery latency < 100ms
- Support 1000+ concurrent signal waiters
- Handle 100+ signals/second per workflow

### Quality Metrics
- 90%+ test coverage for signal code
- Zero data loss during signal processing
- Full replay determinism maintained

## Timeline

### Week 1: Core Implementation
- **Day 1**: Signal provider and handler
- **Day 2**: Monitor service and processing
- **Day 3**: API and CLI integration

### Week 2: Testing & Polish
- **Day 4-5**: Comprehensive testing
- **Day 6**: Documentation and examples
- **Day 7**: Performance optimization

## Conclusion

By following the established patterns from the timer implementation and leveraging existing Redis infrastructure, we can add robust signal support to Gleitzeit with minimal complexity. The implementation is straightforward, maintains system consistency, and provides critical enterprise workflow capabilities.

The phased approach ensures we deliver core functionality quickly while leaving room for enhanced features based on user feedback. With signals, Gleitzeit becomes a more complete workflow orchestration platform, capable of handling complex human-in-the-loop and event-driven workflows.