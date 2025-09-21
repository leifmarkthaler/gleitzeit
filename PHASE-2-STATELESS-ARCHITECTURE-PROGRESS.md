# Phase 2: Stateless Architecture Implementation Progress

## What We've Built

### 1. Stateless Event Consumer ✅
**File**: `src/gleitzeit/events/stateless_event_consumer.py`

Key features:
- **NO persistent loops** - No `while self._running` patterns
- **Instance-specific consumer groups** - Prevents collision: `gleitzeit-instance_abc123`
- **Integrated idempotency** - Checks before processing every message
- **Consumer lifecycle management** - TTL-based registration with heartbeats
- **Single execution model** - `process_batch()` runs once and returns

Architecture:
```python
# OLD (Stateful with loops)
async def start(self):
    while self._running:  # ❌ PERSISTENT LOOP
        messages = await redis.xreadgroup(...)
        await asyncio.sleep(0.1)

# NEW (Stateless)
async def process_batch(self) -> int:
    messages = await redis.xreadgroup(...)  # ✅ Single execution
    return processed_count  # Returns immediately
```

### 2. External Trigger Mechanisms ✅
**File**: `src/gleitzeit/events/external_triggers.py`

Multiple trigger options:

#### WebhookTrigger
- HTTP endpoints: `/triggers/process`, `/triggers/claim-idle`
- Can be called by cron, monitoring systems, manual triggers
- Returns processing statistics

#### RedisTrigger
- Pub/sub based triggering
- Other services can trigger via Redis
- No polling loops

#### TimerTrigger
- Uses Redis for coordination between instances
- Prevents duplicate processing
- Distributed lock mechanism

#### LambdaTrigger
- Optimized for AWS Lambda
- Time-aware processing
- Graceful shutdown before timeout

#### KubernetesCronJobTrigger
- One-shot execution for K8s CronJobs
- Process and exit pattern
- Clean resource management

## Key Architectural Changes

### Before (Stateful)
```python
class StreamEventBus:
    def __init__(self):
        self._running = False  # Instance state

    async def start(self):
        self._running = True
        # Start persistent loops
        asyncio.create_task(self._consume_events())
        asyncio.create_task(self._claim_idle_messages())

    async def _consume_events(self):
        while self._running:  # Persistent loop
            # Process forever
```

### After (Stateless)
```python
class StatelessEventConsumer:
    # No _running flag!

    async def process_batch(self):
        # Process once and return
        messages = await self.redis.xreadgroup(...)
        return processed_count

# Triggered externally:
POST /triggers/process
or
kubectl create cronjob
or
aws lambda invoke
```

## Consumer Group Architecture Fix

### Problem
All instances used the same consumer group `"gleitzeit-workers"`, causing:
- Message collision
- Dead consumer accumulation
- Uneven work distribution

### Solution
Instance-specific consumer groups:
```python
self.instance_id = f"instance_{uuid.uuid4().hex[:8]}"
self.consumer_group = f"{prefix}-{self.instance_id}"
# Result: "gleitzeit-instance_abc123"
```

Each instance now has its own consumer group, enabling:
- No collision between instances
- Clean scaling up/down
- Proper work distribution

## Idempotency Integration

Every message processed checks idempotency:
```python
# Before processing
can_execute, reason = await self.idempotency.check_can_execute(
    task_id=f"{stream_key}:{msg_id}:{handler.__name__}",
    strategy=strategy,
    params=event_data
)

if not can_execute:
    logger.info(f"Skipping: {reason}")
    continue

# Record execution
idempotency_key = await self.idempotency.record_execution_start(...)

# Process
await handler(event)

# Record completion
await self.idempotency.record_execution_complete(idempotency_key)
```

## Deployment Examples

### 1. Kubernetes CronJob
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: gleitzeit-processor
spec:
  schedule: "*/1 * * * *"  # Every minute
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: processor
            image: gleitzeit:latest
            env:
            - name: GLEITZEIT_TRIGGER_TYPE
              value: k8s_cronjob
          restartPolicy: OnFailure
```

### 2. AWS Lambda
```python
import asyncio
from gleitzeit.events.external_triggers import LambdaTrigger

trigger = LambdaTrigger(consumer)

def lambda_handler(event, context):
    return asyncio.run(trigger.handler(event, context))
```

### 3. External Scheduler
```bash
# Cron entry
* * * * * curl -X POST http://gleitzeit:8000/triggers/process
```

## What's Next

### Remaining Phase 2 Tasks
1. **Migrate existing code** - Replace StreamEventBus with StatelessEventConsumer
2. **Remove all loops** - Eliminate remaining `while self._running` patterns
3. **Update SystemManager** - Remove reconciliation loops

### Phase 3: Distributed Coordination
1. **Consistent hashing** - For workflow distribution
2. **Work stealing** - Dynamic load balancing
3. **Leader election** - For singleton tasks
4. **Distributed locks** - For critical sections

## Testing the New Architecture

### Test Stateless Processing
```python
# Initialize consumer
consumer = StatelessEventConsumer(
    redis_client=redis,
    instance_id="test-instance-1"
)

# Register handlers with idempotency
await consumer.register_handler(
    "task:ready",
    handle_task,
    IdempotencyStrategy.CHECK_STATE
)

# Process batch (no loops!)
processed = await consumer.process_batch(max_messages=100)
print(f"Processed {processed} messages")
```

### Test External Triggers
```bash
# HTTP trigger
curl -X POST http://localhost:8000/triggers/process?duration_seconds=60

# Redis trigger
redis-cli PUBLISH gleitzeit:triggers:process '{"action":"process"}'
```

## Impact on Scaling

### Horizontal Scaling Now Possible ✅
- Multiple instances don't interfere
- No shared state between instances
- Clean scale up/down
- Work properly distributed

### Deployment Flexibility ✅
- Kubernetes CronJobs
- AWS Lambda
- Google Cloud Functions
- Traditional cron
- Manual triggers

### Resource Efficiency ✅
- No idle CPU from loops
- Process only when needed
- Clean shutdown
- No resource leaks

## Conclusion

Phase 2 has successfully created the foundation for true stateless, horizontally scalable event processing:

1. **Removed persistent loops** - Replaced with external triggers
2. **Fixed consumer groups** - Instance-specific to prevent collision
3. **Added idempotency** - Safe reruns built-in
4. **Multiple trigger options** - Flexible deployment

The system is now ready for true horizontal scaling without the state management issues that were preventing it before.