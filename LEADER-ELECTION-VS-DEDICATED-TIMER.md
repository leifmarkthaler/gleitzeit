# Leader Election vs Dedicated Timer Worker

## Leader Election Approach

Regular workers elect a leader for timer duties:

```python
# Start regular workers - one becomes leader
gleitzeit worker --workers 4
# Worker 1: Elected as timer leader ✓
# Worker 2: Event processing only
# Worker 3: Event processing only
# Worker 4: Event processing only
```

### Architecture
```python
class StreamWorker:
    async def _consume_loop(self):
        while self._running:
            # Leader does BOTH timers and events
            if self.is_timer_leader:
                await self._process_expired_timers()

            # Everyone processes events
            messages = await self.redis.xreadgroup(...)
            await self._process_messages(messages)
```

### Pros
- **Single deployment** - just `gleitzeit worker`
- **Automatic failover** - new leader elected on failure
- **Resource efficient** - no extra process
- **Dynamic adaptation** - workers self-organize

### Cons
- **Leader overload** - one worker does timers + events
- **Complex code** - election logic in main worker
- **Unpredictable leader** - any worker could be leader
- **Mixed responsibilities** - worker does two jobs

## Dedicated Timer Worker

Separate worker type just for timers:

```bash
# Start dedicated timer worker
gleitzeit worker --type timer --workers 1

# Start regular event workers
gleitzeit worker --type stream --workers 4
```

### Architecture
```python
class TimerWorker(StreamWorker):
    """Specialized worker ONLY for timer checking"""

    async def _consume_loop(self):
        while self._running:
            # ONLY check timers
            await self._process_expired_timers()

            # Maybe listen for timer control events
            await self._process_timer_control()
            # But NO regular event processing

class StreamWorker:
    """Regular worker ONLY for events"""

    async def _consume_loop(self):
        while self._running:
            # ONLY process events, no timer logic
            messages = await self.redis.xreadgroup(...)
            await self._process_messages(messages)
```

### Pros
- **Clear separation** - timer worker vs event worker
- **Predictable load** - dedicated resources for timers
- **Simple code** - each worker type does one thing
- **Easy monitoring** - know exactly which process handles timers
- **Independent scaling** - scale timers and events separately

### Cons
- **Extra process** - need to manage timer worker separately
- **Manual failover** - need process manager for restart
- **Two deployments** - must start both worker types
- **Fixed allocation** - timer worker idle if no timers

## Detailed Comparison

| Aspect | Leader Election | Dedicated Timer Worker |
|--------|-----------------|----------------------|
| **Deployment** | `gleitzeit worker` | `gleitzeit worker --type timer` + `gleitzeit worker --type stream` |
| **Process Count** | N workers | N+1 (N stream + 1 timer) |
| **Failover** | Automatic (0-10s) | Depends on process manager |
| **Code Complexity** | Medium (election logic) | Low (separate classes) |
| **Resource Usage** | Shared (leader does both) | Dedicated (timer has own resources) |
| **Monitoring** | "Which worker is leader?" | "Is timer worker running?" |
| **Scaling** | Scale everything together | Scale timers/events independently |
| **Load Distribution** | Uneven (leader has extra work) | Even (dedicated resources) |

## Performance Analysis

### Scenario 1: Low Timer Load (100 timers/sec)
```
Leader Election:
- Leader: 100 timers/sec + 250 events/sec = 350 ops/sec ⚠️
- Others: 250 events/sec each

Dedicated:
- Timer: 100 timers/sec ✓
- Others: 250 events/sec each ✓
```
**Winner**: Either works fine

### Scenario 2: High Timer Load (1000 timers/sec)
```
Leader Election:
- Leader: 1000 timers/sec + 250 events/sec = 1250 ops/sec ⛔
- Others: 250 events/sec each

Dedicated:
- Timer: 1000 timers/sec ✓
- Others: 250 events/sec each ✓
```
**Winner**: Dedicated timer worker

### Scenario 3: Bursty Timer Load
```
Leader Election:
- During burst: Leader overwhelmed, events delayed
- After burst: Returns to normal

Dedicated:
- During burst: Timer worker busy, events unaffected
- After burst: Both normal
```
**Winner**: Dedicated timer worker

## Operational Considerations

### With Kubernetes/Docker

**Leader Election**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-workers
spec:
  replicas: 4
  template:
    spec:
      containers:
      - name: worker
        command: ["gleitzeit", "worker"]
        # One pod automatically becomes leader
```

**Dedicated Timer**:
```yaml
# Timer worker deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-timer
spec:
  replicas: 1  # Only one timer worker
  template:
    spec:
      containers:
      - name: timer
        command: ["gleitzeit", "worker", "--type", "timer"]
---
# Event workers deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-workers
spec:
  replicas: 4
  template:
    spec:
      containers:
      - name: worker
        command: ["gleitzeit", "worker", "--type", "stream"]
```

### With systemd

**Leader Election**:
```ini
[Unit]
Description=Gleitzeit Worker %i

[Service]
ExecStart=/usr/bin/gleitzeit worker
Restart=always

[Install]
WantedBy=multi-user.target
```

**Dedicated Timer**:
```ini
# Timer service
[Unit]
Description=Gleitzeit Timer Worker

[Service]
ExecStart=/usr/bin/gleitzeit worker --type timer
Restart=always

# Event workers
[Unit]
Description=Gleitzeit Event Worker %i

[Service]
ExecStart=/usr/bin/gleitzeit worker --type stream
Restart=always
```

## Hybrid Solution: Best of Both

Start with dedicated, add election as fallback:

```python
class SmartWorkerManager:
    """Manages both dedicated and elected timer workers"""

    def __init__(self):
        self.has_dedicated_timer = False

    async def start(self):
        # Check if dedicated timer worker exists
        self.has_dedicated_timer = await self._check_dedicated_timer()

        if self.has_dedicated_timer:
            # Just be an event worker
            await self._start_as_event_worker()
        else:
            # No dedicated timer, use election
            await self._start_with_election()

    async def _check_dedicated_timer(self):
        """Check if a dedicated timer worker is running"""
        # Look for timer:dedicated:heartbeat key
        return await self.redis.exists("timer:dedicated:heartbeat")
```

## Recommendation by Use Case

### Use **Leader Election** when:
- **Simple deployment** is priority
- **Low timer volume** (<100/sec)
- **Kubernetes/cloud** with auto-restart
- **Small teams** who want less complexity

### Use **Dedicated Timer Worker** when:
- **High timer volume** (>100/sec)
- **Predictable performance** needed
- **Clear separation** desired
- **Production systems** with SLAs
- **Independent scaling** requirements

### Use **Hybrid** when:
- **Migration path** from simple to complex
- **Multi-environment** (dev vs prod)
- **High availability** is critical

## Final Recommendation

**Start with Dedicated Timer Worker** because:

1. **Clarity**: One worker type = one responsibility
2. **Performance**: No competition between timers and events
3. **Monitoring**: Easy to see if timer worker is running
4. **Debugging**: Timer issues isolated to timer worker
5. **Scaling**: Can scale timers independently of events

The extra deployment complexity is worth it for production systems.

## Implementation Quick Start

### Dedicated Timer Worker
```python
# src/gleitzeit/workers/timer_worker.py
class TimerWorker:
    """Dedicated timer processing worker"""

    def __init__(self, system_manager):
        self.redis = system_manager.persistence.redis
        self.check_interval = 1  # seconds

    async def run(self):
        """Main timer checking loop"""
        logger.info("Starting dedicated timer worker")

        while True:
            try:
                # Mark ourselves as the dedicated timer
                await self.redis.setex(
                    "timer:dedicated:heartbeat",
                    10,
                    self.worker_id
                )

                # Process timers
                await self._process_all_expired_timers()

                # Sleep briefly
                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Timer worker error: {e}")
                await asyncio.sleep(1)

    async def _process_all_expired_timers(self):
        """Check and process ALL expired timers"""
        now = time.time()

        # Get all expired timers at once
        expired = await self.redis.zrangebyscore(
            "timers:pending", 0, now
        )

        if not expired:
            return

        logger.info(f"Processing {len(expired)} expired timers")

        # Emit events for expired timers
        for timer_key in expired:
            task_id = timer_key.decode().split(":")[-1]

            # Add to task:ready stream
            await self.redis.xadd(
                "gleitzeit:events:stream:task:ready",
                {
                    "event_type": "task:ready",
                    "task_id": task_id,
                    "reason": "timer_expired"
                }
            )

        # Remove all processed timers
        await self.redis.zrem("timers:pending", *expired)
```

### CLI Integration
```python
# src/gleitzeit/cli/main.py
@cli.command()
@click.option('--type', type=click.Choice(['stream', 'timer', 'auto']),
              default='auto', help='Worker type')
def worker(type: str):
    """Start worker (stream, timer, or auto-detect)"""

    if type == 'timer':
        # Start dedicated timer worker
        worker = TimerWorker(system_manager)
        asyncio.run(worker.run())

    elif type == 'stream':
        # Start event-only worker
        worker = StreamWorker(system_manager, timer_checking=False)
        asyncio.run(worker.start())

    else:  # auto
        # Start smart worker that detects mode
        worker = StreamWorker(system_manager, timer_checking='auto')
        asyncio.run(worker.start())
```

Simple, clear, and production-ready!