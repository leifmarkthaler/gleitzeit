# Timer and Signal Provider Reimplementation Design

## Current State Analysis

### Problems
1. **Timer Provider**: Imports non-existent `TimerTaskHandler`
2. **Signal Provider**: References non-existent `wait_for_signal()` method
3. **No actual delays**: Neither implements sleep/wait functionality
4. **Broken execution**: Tasks fail at runtime due to missing imports

### Current (Broken) Flow
```python
# Timer task submitted with protocol: timer/v1
# Tries to: TimerTaskHandler.wait(duration=60)  # FAILS - class doesn't exist
# Actually: Just stores metadata in Redis

# Signal task submitted with protocol: signal/v1
# Tries to: StatelessSignalManager.wait_for_signal()  # FAILS - method doesn't exist
# Actually: Just emits events
```

## Proposed Architecture

### Core Design Principles
1. **Stateless operation**: No in-memory state, everything in Redis
2. **Stream-based**: Use Redis Streams for event-driven execution
3. **Non-blocking**: Don't hold worker threads during waits
4. **Resumable**: Can recover from crashes/restarts
5. **Kafka-style**: Integrate with the new StreamWorker pattern

## Implementation Options

### Option 1: Pure Event-Driven (Recommended)
**Concept**: Tasks pause and resume based on events, no actual sleep

```python
# Timer Flow
1. Task executes with timer/v1:wait
2. Provider creates a "timer:pending" entry in Redis with expiry time
3. Task marked as WAITING status
4. Separate timer service checks for expired timers (polling or Redis keyspace notifications)
5. When timer expires, emit "timer:expired" event
6. StreamWorker picks up event and resumes task

# Signal Flow
1. Task executes with signal/v1:wait
2. Provider creates "signal:waiting:{signal_id}" entry in Redis
3. Task marked as WAITING status
4. External system sends signal via API
5. API emits "signal:received" event
6. StreamWorker picks up event and resumes task
```

**Pros**:
- Fully stateless and scalable
- Workers don't block during waits
- Integrates with existing event system
- Can handle thousands of waiting tasks

**Cons**:
- Requires timer service for checking expirations
- More complex than simple sleep

### Option 2: Hybrid Blocking/Non-blocking
**Concept**: Short waits block, long waits use events

```python
# Timer Flow
if duration < 30 seconds:
    await asyncio.sleep(duration)  # Block the worker
    return result
else:
    # Use event-driven approach for long waits
    create_timer_event(task_id, duration)
    return TaskStatus.WAITING

# Signal Flow
if timeout < 30 seconds:
    # Poll Redis for signal with timeout
    result = await redis.blpop(f"signal:{signal_id}", timeout)
else:
    # Use event-driven approach
    create_signal_waiter(task_id, signal_id)
    return TaskStatus.WAITING
```

**Pros**:
- Simple for short waits
- Efficient for both short and long delays

**Cons**:
- Workers can still block
- Two different code paths to maintain

### Option 3: Redis Keyspace Notifications
**Concept**: Use Redis TTL and keyspace events for timers

```python
# Timer Flow
1. Set key with TTL: SET timer:task:{task_id} "data" EX {duration}
2. Subscribe to keyspace notifications for expiry
3. When key expires, Redis publishes notification
4. Handler resumes the task

# Signal Flow (same as Option 1)
```

**Pros**:
- Native Redis feature, no polling needed
- Automatic expiration handling

**Cons**:
- Requires Redis config change (notify-keyspace-events)
- Notifications are not guaranteed delivery
- Not suitable for production without backup polling

## Recommended Implementation Plan

### Phase 1: Fix Immediate Breaks
```python
# timer_provider.py
class TimerProvider(BaseProvider):
    async def handle_request(self, method: str, params: dict):
        if method == "wait":
            duration = params.get("duration", 60)
            task_id = params.get("task_id")

            # Store timer in Redis
            timer_key = f"timer:pending:{task_id}"
            expire_at = time.time() + duration
            await self.redis.zadd("timers:pending", {timer_key: expire_at})

            # Emit event for timer created
            await self._emit_timer_created(task_id, duration)

            # Return waiting status
            return {"status": "waiting", "resume_after": duration}

# signal_provider.py
class SignalProvider(BaseProvider):
    async def handle_request(self, method: str, params: dict):
        if method == "wait":
            signal_id = params.get("signal_id")
            task_id = params.get("task_id")

            # Register signal waiter
            await self.redis.hset(
                f"signal:waiters:{signal_id}",
                task_id,
                json.dumps({"waiting_since": time.time()})
            )

            # Emit event for signal waiter created
            await self._emit_signal_waiter_created(task_id, signal_id)

            # Return waiting status
            return {"status": "waiting", "signal_id": signal_id}
```

### Phase 2: Add Timer Checking via StreamWorker
```python
# workers/stream_worker.py - Extended for timer checking
class StreamWorker:
    """Extended StreamWorker that also processes timers"""

    def __init__(self, system_manager, worker_id=None):
        # ... existing code ...
        self.last_timer_check = 0
        self.timer_check_interval = 1  # seconds

    async def _consume_loop(self):
        """
        Main consumption loop with timer checking.
        Uses the same worker pool for both events AND timers!
        """
        streams = {
            "gleitzeit:events:stream:task:ready": ">",
            "gleitzeit:events:stream:task:completed": ">",
            # ... other streams ...
            "gleitzeit:events:stream:timer:check": ">"  # Timer check stream
        }

        while self._running:
            try:
                # Check if we should process timers
                now = time.time()
                if now - self.last_timer_check >= self.timer_check_interval:
                    await self._check_expired_timers()
                    self.last_timer_check = now

                # Normal event consumption (with timeout for timer checking)
                messages = await self.redis.xreadgroup(
                    self.consumer_group,
                    self.worker_id,
                    streams,
                    count=10,
                    block=1000  # 1 second timeout for timer checks
                )

                if messages:
                    await self._process_messages(messages)

            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(1)

    async def _check_expired_timers(self):
        """Check and process expired timers - runs IN the worker!"""
        try:
            now = time.time()

            # Use Redis sorted set to get expired timers
            expired = await self.redis.zrangebyscore(
                "timers:pending",
                0,
                now,
                start=0,
                num=10  # Process 10 at a time
            )

            for timer_key in expired:
                # Extract task_id
                task_id = timer_key.decode().split(":")[-1]

                # Emit timer expired event to stream
                await self.redis.xadd(
                    "gleitzeit:events:stream:timer:expired",
                    {
                        "event_type": "timer:expired",
                        "task_id": task_id,
                        "expired_at": str(now)
                    }
                )

                # Remove from pending
                await self.redis.zrem("timers:pending", timer_key)

        except Exception as e:
            logger.error(f"Timer check error: {e}")
```

### Alternative: Dedicated Timer Worker Type
```python
# workers/timer_worker.py - Specialized timer worker
class TimerWorker(StreamWorker):
    """
    Specialized worker that ONLY handles timer checking.
    Runs alongside regular StreamWorkers.
    """

    def __init__(self, system_manager, check_interval=1):
        super().__init__(system_manager, worker_id=f"timer-{uuid.uuid4().hex[:8]}")
        self.check_interval = check_interval
        self.consumer_group = "gleitzeit-timers"  # Different consumer group

    async def _consume_loop(self):
        """Dedicated timer checking loop"""
        while self._running:
            try:
                # Check expired timers
                await self._process_expired_timers()

                # Also listen for timer control events
                messages = await self.redis.xreadgroup(
                    self.consumer_group,
                    self.worker_id,
                    {"gleitzeit:events:stream:timer:control": ">"},
                    count=1,
                    block=self.check_interval * 1000  # Block for check_interval
                )

                if messages:
                    # Handle timer control messages (cancel, update, etc.)
                    await self._process_timer_control(messages)

            except Exception as e:
                logger.error(f"Timer worker error: {e}")
                await asyncio.sleep(1)

    async def _process_expired_timers(self):
        """Process ALL expired timers"""
        now = time.time()

        # Get ALL expired timers (not just 10)
        expired = await self.redis.zrangebyscore(
            "timers:pending", 0, now
        )

        for timer_key in expired:
            task_id = timer_key.decode().split(":")[-1]

            # Emit to the main event stream for regular workers to process
            await self.redis.xadd(
                "gleitzeit:events:stream:task:ready",  # Reuse existing stream!
                {
                    "event_type": "task:ready",
                    "task_id": task_id,
                    "reason": "timer_expired",
                    "expired_at": str(now)
                }
            )

            # Remove from pending
            await self.redis.zrem("timers:pending", timer_key)

        if expired:
            logger.info(f"Processed {len(expired)} expired timers")
```

### Phase 3: Add Signal API Endpoints
```python
# api/routes/signals.py
@router.post("/signals/{signal_id}/send")
async def send_signal(signal_id: str, data: dict = None):
    """Send a signal to waiting tasks"""

    # Get all tasks waiting for this signal
    waiters = await redis.hgetall(f"signal:waiters:{signal_id}")

    for task_id, waiter_data in waiters.items():
        # Emit signal received event
        await emit_event(
            "signal:received",
            task_id=task_id,
            signal_id=signal_id,
            data=data
        )

    # Clean up waiters
    await redis.delete(f"signal:waiters:{signal_id}")

    return {"tasks_signaled": len(waiters)}
```

### Phase 4: Integrate with StreamWorker
```python
# Add handlers to existing event processing
class StreamWorker:
    def __init__(self, system_manager, worker_id=None):
        # ... existing code ...

        # Register timer/signal handlers
        self.event_bus.on("timer:expired", self._handle_timer_expired)
        self.event_bus.on("signal:received", self._handle_signal_received)

    async def _handle_timer_expired(self, event):
        """Resume task after timer expiry"""
        task_id = event["task_id"]

        # Get task from persistence
        task = await self.persistence.get_task(task_id)

        # Update status and resume
        task.status = TaskStatus.READY
        await self.persistence.update_task(task)

        # Emit task ready event to resume execution
        await self.emit_event("task:ready", task.dict())

    async def _handle_signal_received(self, event):
        """Resume task after signal received"""
        # Similar to timer handling
        pass
```

## Task Status Extensions

Add new statuses for waiting tasks:

```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    READY = "ready"
    EXECUTING = "executing"
    WAITING = "waiting"        # NEW: Task is waiting for timer/signal
    WAITING_TIMER = "waiting_timer"    # NEW: Specifically waiting for timer
    WAITING_SIGNAL = "waiting_signal"  # NEW: Specifically waiting for signal
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

## Configuration

```yaml
# gleitzeit.yaml
timers:
  service:
    enabled: true
    check_interval: 1  # seconds
    batch_size: 100    # max timers to process per check

signals:
  api:
    enabled: true
    auth_required: true
    cleanup_after: 3600  # seconds to keep completed signals
```

## Testing Strategy

### Unit Tests
```python
# Test timer expiration
async def test_timer_expiration():
    provider = TimerProvider(redis)
    result = await provider.handle_request("wait", {
        "task_id": "task-1",
        "duration": 5
    })
    assert result["status"] == "waiting"

    # Check timer was stored
    timers = await redis.zrange("timers:pending", 0, -1)
    assert len(timers) == 1

# Test signal waiting
async def test_signal_waiting():
    provider = SignalProvider(redis)
    result = await provider.handle_request("wait", {
        "task_id": "task-1",
        "signal_id": "approval-1"
    })
    assert result["status"] == "waiting"

    # Check waiter was registered
    waiters = await redis.hkeys("signal:waiters:approval-1")
    assert "task-1" in waiters
```

### Integration Tests
```python
# Test full timer workflow
async def test_timer_workflow():
    # Submit workflow with timer
    workflow = {
        "id": "timer-test",
        "tasks": [
            {
                "name": "wait_5_seconds",
                "protocol": "timer/v1",
                "method": "wait",
                "params": {"duration": 5}
            }
        ]
    }

    # Start worker and timer service
    worker = StreamWorker(system_manager)
    timer_service = TimerService(redis)

    # Submit and wait
    result = await client.submit_workflow(workflow)
    await asyncio.sleep(6)

    # Check completion
    status = await client.get_workflow_status(workflow["id"])
    assert status == "completed"
```

## Deployment Options

### Option A: Embedded Timer Checking (Simplest)
Every StreamWorker checks timers periodically:
```bash
# Just start workers - they handle everything!
gleitzeit worker --workers 4
```

**Pros**:
- No extra processes
- Simple deployment
- Automatic load distribution

**Cons**:
- Timer checks compete with event processing
- Possible duplicate processing without coordination

### Option B: Dedicated Timer Worker (Recommended)
One specialized worker for timers, others for events:
```bash
# Start timer worker
gleitzeit worker --type timer --workers 1

# Start regular workers
gleitzeit worker --type stream --workers 4
```

**Pros**:
- Clean separation of concerns
- Predictable timer checking
- No competition for resources

**Cons**:
- Need to manage two worker types

### Option C: Leader Election
Workers elect a leader for timer checking:
```python
# First worker to start becomes timer leader
async def elect_timer_leader(self):
    # Try to acquire lock
    lock = await self.redis.set(
        "timer:leader:lock",
        self.worker_id,
        nx=True,  # Only set if not exists
        ex=10     # Expire after 10 seconds
    )

    if lock:
        self.is_timer_leader = True
        # Renew lock periodically
        asyncio.create_task(self._renew_leader_lock())
```

**Pros**:
- Automatic failover
- Single deployment command
- Efficient resource use

**Cons**:
- More complex coordination
- Need lock renewal logic

## Migration Path

1. **Day 1**: Fix broken imports in providers
2. **Day 2**: Implement timer storage in Redis sorted sets
3. **Day 3**: Add timer checking to StreamWorker
4. **Day 4**: Add signal API endpoints
5. **Day 5**: Testing and documentation
6. **Day 6**: Deploy with existing workers

## Alternative: Celery-Style Approach

If we want to match Celery's behavior more closely:

```python
# Use Celery's ETA (Estimated Time of Arrival) pattern
@task
def do_something():
    # Schedule for later
    do_something.apply_async(eta=datetime.now() + timedelta(seconds=60))

# Our equivalent
async def handle_timer_task(task):
    # Instead of waiting, reschedule the task
    task.scheduled_for = time.time() + task.params["duration"]
    await redis.zadd("scheduled:tasks", {task.id: task.scheduled_for})

    # Mark as scheduled, not waiting
    task.status = TaskStatus.SCHEDULED
    return {"status": "scheduled", "run_at": task.scheduled_for}
```

## Decision Criteria

Choose **Option 1 (Pure Event-Driven)** if:
- Scalability is critical
- You have many long-running waits
- You want consistent architecture

Choose **Option 2 (Hybrid)** if:
- You have mostly short waits
- Simplicity is more important than scalability
- You want quick implementation

Choose **Option 3 (Keyspace Notifications)** if:
- You control Redis configuration
- You want native Redis features
- You can handle occasional missed notifications

## Recommendation

**Implement Option 1 (Pure Event-Driven)** because:
1. Aligns with the Kafka-style stream architecture
2. Fully stateless and horizontally scalable
3. Consistent with the event-driven philosophy
4. No blocking workers = better resource utilization
5. Already have the event infrastructure in place

The timer service can start as a simple polling loop and later be optimized with keyspace notifications or other mechanisms.