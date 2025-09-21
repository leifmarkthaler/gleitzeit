# Signal Worker Design

## Overview

Similar to timer workers, we'll implement **dedicated signal workers with leader election** to handle signal-based task synchronization. Tasks can wait for external signals without blocking worker threads.

**Important**: Signals are scoped per-workflow for security and isolation. A signal sent to workflow A cannot wake tasks in workflow B.

## Architecture

```
External System
      │
      ▼ POST /workflows/{workflow_id}/send/{signal_name}
   API Endpoint
      │
      ▼ Store signal
Redis: workflow:signals:{workflow_id}
      │
      ▼
Signal Workers (Leader Election)
      │
      ▼ Process workflow signals
Match with waiting tasks IN SAME WORKFLOW
      │
      ▼ Emit task:ready events
Redis Streams
      │
      ▼
Stream Workers resume tasks
```

## Key Differences from Timer Workers

| Aspect | Timer Workers | Signal Workers |
|--------|--------------|----------------|
| **Trigger** | Time expiry | External signal |
| **Storage** | Sorted set (by time) | Hash (by signal_id) |
| **Processing** | Check expired | Match signal→task |
| **API** | Not needed | POST endpoint |
| **Timeout** | Natural (time passes) | Optional timeout |

## Implementation Plan

### 1. SignalWorker (`src/gleitzeit/workers/signal_worker.py`)

```python
class SignalWorker:
    """
    Dedicated signal worker with leader election.
    Processes received signals and resumes waiting tasks.
    """

    def __init__(self, system_manager, worker_id=None, priority=0):
        self.system_manager = system_manager
        self.redis = system_manager.persistence.redis
        self.worker_id = worker_id or f"signal-{uuid.uuid4().hex[:8]}"
        self.priority = priority

        # Leadership configuration (same as timer)
        self.is_leader = False
        self.leader_key = "signal:leader"
        self.leader_ttl = 10
        self.heartbeat_interval = 3

    async def _run_loop(self):
        """Main loop - election and signal processing"""
        while self._running:
            if not self.is_leader:
                await self._attempt_leadership()

            if self.is_leader:
                await self._process_signals_as_leader()
            else:
                await self._standby_mode()

            await asyncio.sleep(0.5)  # Faster than timers

    async def _process_signals_as_leader(self):
        """Process pending signals for all workflows"""

        # Scan for workflows with pending signals
        workflow_keys = []
        async for key in self.redis.scan_iter("workflow:signals:*"):
            workflow_keys.append(key)

        for workflow_key in workflow_keys:
            # Extract workflow_id from key
            workflow_id = workflow_key.decode().split(":")[-1]

            # Read signals from workflow stream
            signals = await self.redis.xread(
                {workflow_key: "0"},  # Read all signals
                count=100
            )

            if not signals:
                continue

            for signal_id, signal_data in signals[0][1]:  # signals[0] = (key, messages)
                signal_name = signal_data.get(b"signal", b"").decode()

                # Find waiting tasks for this signal IN THIS WORKFLOW
                waiting_tasks = await self.redis.smembers(
                    f"signal:waiters:{workflow_id}:{signal_name}"
                )

                if waiting_tasks:
                    logger.info(
                        f"Signal {signal_name} matched {len(waiting_tasks)} tasks "
                        f"in workflow {workflow_id}"
                    )

                    # Resume each waiting task
                    for task_id in waiting_tasks:
                        await self.redis.xadd(
                            "gleitzeit:events:stream:task:ready",
                            {
                                "event_type": "task:ready",
                                "task_id": task_id.decode() if isinstance(task_id, bytes) else task_id,
                                "workflow_id": workflow_id,
                                "reason": "signal_received",
                                "signal_name": signal_name,
                                "signal_data": signal_data.get(b"payload", b"").decode()
                            }
                        )

                    # Clean up waiters
                    await self.redis.delete(f"signal:waiters:{workflow_id}:{signal_name}")

                # ACK the signal message
                await self.redis.xack(workflow_key, "signal-workers", signal_id)

    async def _check_timeouts(self):
        """Check for signal timeouts (optional)"""

        now = time.time()

        # Get all timeout entries
        timeouts = await self.redis.zrangebyscore(
            "signal:timeouts", 0, now
        )

        for entry in timeouts:
            task_id = entry.decode().split(":")[-1]

            # Resume task with timeout error
            await self.redis.xadd(
                "gleitzeit:events:stream:task:ready",
                {
                    "event_type": "task:ready",
                    "task_id": task_id,
                    "reason": "signal_timeout",
                    "error": "Signal wait timed out"
                }
            )

            # Remove from timeouts
            await self.redis.zrem("signal:timeouts", entry)
```

### 2. SignalProvider (`src/gleitzeit/providers/signal_provider.py`)

```python
class SignalProvider(SimpleProvider):
    """Handles signal/v1 protocol requests"""

    async def execute(self, method: str, params: dict):
        """Process signal methods"""

        if method == "wait":
            return await self._handle_wait(params)
        elif method == "wait_any":
            return await self._handle_wait_any(params)
        elif method == "wait_all":
            return await self._handle_wait_all(params)

    async def _handle_wait(self, params):
        """Wait for a specific signal within the workflow"""

        signal_name = params.get("signal_name")
        workflow_id = params.get("_workflow_id")
        task_id = params.get("_task_id")
        timeout = params.get("timeout", None)  # Optional

        if not workflow_id:
            raise ValueError("Signal wait requires workflow context")

        # Check if signal already received in this workflow
        # Read the workflow's signal stream to check for existing signals
        existing = await self.redis.xread(
            {f"workflow:signals:{workflow_id}": "0"},
            count=1000
        )

        if existing:
            for msg_id, data in existing[0][1]:
                if data.get(b"signal", b"").decode() == signal_name:
                    # Signal already received, complete immediately
                    return {
                        "status": "completed",
                        "result": {
                            "signal_name": signal_name,
                            "data": data.get(b"payload", b"").decode()
                        }
                    }

        # Register task as waiting for signal IN THIS WORKFLOW
        await self.redis.sadd(f"signal:waiters:{workflow_id}:{signal_name}", task_id)

        # Store waiter metadata
        await self.redis.hset(
            f"signal:metadata:{workflow_id}:{task_id}",
            mapping={
                "signal_name": signal_name,
                "workflow_id": workflow_id,
                "waiting_since": str(time.time()),
                "timeout": str(timeout) if timeout else "none"
            }
        )

        # Set timeout if specified
        if timeout:
            timeout_at = time.time() + timeout
            await self.redis.zadd(
                "signal:timeouts",
                {f"signal:task:{task_id}": timeout_at}
            )

        # Return waiting status
        return {
            "status": "waiting",
            "signal_id": signal_id,
            "timeout": timeout
        }

    async def _handle_wait_any(self, params):
        """Wait for any of multiple signals"""

        signal_ids = params.get("signal_ids", [])
        task_id = params.get("_task_id")

        # Check if any signal already received
        for signal_id in signal_ids:
            if await self.redis.sismember("signals:received", signal_id):
                signal_data = await self.redis.hget("signals:data", signal_id)
                return {
                    "status": "completed",
                    "result": {
                        "signal_id": signal_id,
                        "data": signal_data
                    }
                }

        # Register for all signals
        for signal_id in signal_ids:
            await self.redis.sadd(f"signal:waiters:{signal_id}", task_id)

        # Store metadata
        await self.redis.hset(
            f"signal:metadata:{task_id}",
            mapping={
                "signal_ids": json.dumps(signal_ids),
                "mode": "any",
                "waiting_since": str(time.time())
            }
        )

        return {
            "status": "waiting",
            "signal_ids": signal_ids,
            "mode": "any"
        }

    async def _handle_wait_all(self, params):
        """Wait for all of multiple signals"""

        signal_ids = params.get("signal_ids", [])
        task_id = params.get("_task_id")

        # Check which signals are already received
        received = []
        for signal_id in signal_ids:
            if await self.redis.sismember("signals:received", signal_id):
                received.append(signal_id)

        if len(received) == len(signal_ids):
            # All signals received, complete immediately
            return {
                "status": "completed",
                "result": {
                    "signal_ids": signal_ids,
                    "all_received": True
                }
            }

        # Store pending signals
        pending = [s for s in signal_ids if s not in received]
        await self.redis.hset(
            f"signal:pending:{task_id}",
            mapping={
                "required": json.dumps(signal_ids),
                "received": json.dumps(received),
                "pending": json.dumps(pending)
            }
        )

        # Register for pending signals only
        for signal_id in pending:
            await self.redis.sadd(f"signal:waiters:{signal_id}", task_id)

        return {
            "status": "waiting",
            "signal_ids": signal_ids,
            "mode": "all",
            "received": received,
            "pending": pending
        }
```

### 3. Signal API Endpoints (Already Exist!)

The existing API already has the right endpoints:

```python
# src/gleitzeit/api/routes/signals.py

@router.post("/workflows/{workflow_id}/send")
async def send_signal(
    workflow_id: str,
    request: SignalRequest  # Contains signal_name and payload
):
    """Send signal to specific workflow"""
    # Already implemented - stores in workflow:signals:{workflow_id}

@router.post("/workflows/{workflow_id}/send/{signal_name}")
async def send_signal_wake(
    workflow_id: str,
    signal_name: str
):
    """Quick signal send without payload"""
    # Already implemented

@router.get("/workflows/{workflow_id}/waiting")
async def list_waiting_signals(workflow_id: str):
    """List signals that workflow is waiting for"""
    # Already implemented

@router.get("/signals/{signal_id}/waiters")
async def get_signal_waiters(signal_id: str):
    """Get list of tasks waiting for a signal"""

    waiters = await redis.smembers(f"signal:waiters:{signal_id}")

    # Get metadata for each waiter
    waiter_info = []
    for task_id in waiters:
        metadata = await redis.hgetall(f"signal:metadata:{task_id}")
        waiter_info.append({
            "task_id": task_id,
            "waiting_since": metadata.get("waiting_since"),
            "timeout": metadata.get("timeout")
        })

    return {
        "signal_id": signal_id,
        "waiters": waiter_info,
        "count": len(waiter_info)
    }

@router.delete("/signals/{signal_id}")
async def cancel_signal(signal_id: str):
    """Cancel a signal and fail waiting tasks"""

    # Get waiting tasks
    waiters = await redis.smembers(f"signal:waiters:{signal_id}")

    # Fail each waiting task
    for task_id in waiters:
        await redis.xadd(
            "gleitzeit:events:stream:task:ready",
            {
                "event_type": "task:ready",
                "task_id": task_id,
                "reason": "signal_cancelled",
                "error": f"Signal {signal_id} was cancelled"
            }
        )

    # Clean up
    await redis.delete(f"signal:waiters:{signal_id}")
    await redis.srem("signals:received", signal_id)
    await redis.hdel("signals:data", signal_id)

    return {
        "signal_id": signal_id,
        "tasks_failed": len(waiters)
    }
```

### 4. CLI Integration

```python
@cli.command()
@click.option('--type', choices=['stream', 'timer', 'signal', 'auto'])
def worker(type, workers, priority):
    """Start workers for event/timer/signal processing"""

    if type == 'signal':
        # Start dedicated signal workers
        for i in range(workers):
            SignalWorker(
                system_manager,
                worker_id=f"signal-{i}",
                priority=priority
            )
    # ... rest of implementation
```

## Usage Examples

### 1. Simple Signal Wait

```yaml
# workflow.yaml
id: approval-workflow-123
tasks:
  - name: wait_for_approval
    protocol: signal/v1
    method: wait
    params:
      signal_name: "approval"  # Signal name within workflow
      timeout: 300  # 5 minute timeout

  - name: process_after_approval
    depends_on: [wait_for_approval]
    protocol: python/v1
    method: process
```

Send signal:
```bash
# Signal is sent to specific workflow
curl -X POST http://localhost:8000/workflows/approval-workflow-123/send \
  -H "Content-Type: application/json" \
  -d '{
    "signal_name": "approval",
    "payload": {"approved": true, "approver": "john"}
  }'

# Or simpler without payload
curl -X POST http://localhost:8000/workflows/approval-workflow-123/send/approval
```

### 2. Wait for Any Signal

```yaml
id: multi-approval-workflow
tasks:
  - name: wait_for_any_approval
    protocol: signal/v1
    method: wait_any
    params:
      signal_names: ["manager-approval", "director-approval"]
```

```bash
# Either signal will wake the task
curl -X POST http://localhost:8000/workflows/multi-approval-workflow/send/manager-approval
# OR
curl -X POST http://localhost:8000/workflows/multi-approval-workflow/send/director-approval
```

### 3. Wait for All Signals

```yaml
id: consensus-workflow
tasks:
  - name: wait_for_consensus
    protocol: signal/v1
    method: wait_all
    params:
      signal_names: ["team1-ready", "team2-ready", "team3-ready"]
```

```bash
# All three signals must be sent to wake the task
curl -X POST http://localhost:8000/workflows/consensus-workflow/send/team1-ready
curl -X POST http://localhost:8000/workflows/consensus-workflow/send/team2-ready
curl -X POST http://localhost:8000/workflows/consensus-workflow/send/team3-ready
```

### 4. Human-in-the-Loop Workflow

```yaml
id: report-workflow-{{ uuid }}
tasks:
  - name: generate_report
    protocol: python/v1
    method: generate_report

  - name: wait_for_review
    protocol: signal/v1
    method: wait
    params:
      signal_name: "report-approved"
      timeout: 86400  # 24 hours

  - name: publish_report
    depends_on: [wait_for_review]
    protocol: python/v1
    method: publish
```

```bash
# After human review, send approval signal to specific workflow
curl -X POST http://localhost:8000/workflows/report-workflow-abc123/send \
  -d '{
    "signal_name": "report-approved",
    "payload": {
      "reviewer": "jane",
      "comments": "Looks good",
      "timestamp": "2024-01-15T10:30:00Z"
    }
  }'
```

## Signal vs Timer Comparison

| Feature | Timer | Signal |
|---------|-------|--------|
| **Trigger** | Time-based | Event-based |
| **Use Case** | Delays, scheduling | Synchronization, approvals |
| **Deterministic** | Yes (time always passes) | No (signal may never come) |
| **Timeout** | Natural | Optional parameter |
| **External Input** | No | Yes (API/CLI) |
| **Cancellable** | No (time passes) | Yes (cancel signal) |

## Deployment

```bash
# Start all worker types
gleitzeit worker --type timer --workers 3 &
gleitzeit worker --type signal --workers 3 &
gleitzeit worker --type stream --workers 6 &

# Or mixed mode
gleitzeit worker --type auto --workers 10
# Auto-detects and allocates: 1 timer, 1 signal, 8 stream
```

## Monitoring

```bash
# Check signal workers
redis-cli HGETALL signal:workers

# View signal leader
redis-cli GET signal:leader

# List pending signals
redis-cli SMEMBERS signals:received

# View signal waiters
redis-cli SMEMBERS signal:waiters:approval-123

# Monitor signal events
redis-cli XREAD STREAMS gleitzeit:events:stream:signal:received 0
```

## Benefits

1. **Non-blocking**: No worker threads held during waits
2. **External Integration**: Easy API for external systems
3. **Flexible Synchronization**: Any/all signal patterns
4. **Human-in-the-Loop**: Perfect for approval workflows
5. **High Availability**: Leader election ensures reliability
6. **Observable**: Full monitoring and metrics
7. **Secure**: Workflow-scoped signals prevent cross-workflow interference

## Security Benefits of Per-Workflow Signals

### Isolation
- Workflow A cannot interfere with Workflow B
- No global signal namespace pollution
- Each workflow has its own signal context

### Access Control
- Can implement per-workflow permissions
- Audit trail shows which workflow received which signals
- Easy to revoke access to specific workflows

### Debugging
- Clear signal ownership (workflow + signal name)
- No confusion about signal scope
- Easy to trace signal flow

### Example Attack Prevention
```bash
# This CANNOT wake tasks in other workflows
curl -X POST http://localhost:8000/workflows/workflow-A/send/approval

# Would need explicit access to workflow-B
curl -X POST http://localhost:8000/workflows/workflow-B/send/approval
```

## Implementation Priority

1. **Phase 1**: Basic signal wait (single signal)
2. **Phase 2**: Signal API endpoints
3. **Phase 3**: Leader election for signal workers
4. **Phase 4**: Advanced patterns (any/all)
5. **Phase 5**: Timeouts and cancellation

This gives us a complete event-driven signaling system that complements the timer system perfectly!