# Migration Guide: From Stateful to Stateless Event Processing

## Overview

This guide shows how to migrate from the current stateful `StreamEventBus` to the new stateless architecture.

## Current Problems with StreamEventBus

```python
# src/gleitzeit/events/stream_event_bus.py
class StreamEventBus:
    def __init__(self):
        self._running = False  # ❌ STATEFUL
        self.consumer_group = "gleitzeit-workers"  # ❌ SHARED ACROSS ALL INSTANCES

    async def start(self):
        self._running = True
        # ❌ PERSISTENT LOOPS
        asyncio.create_task(self._consume_events())
        asyncio.create_task(self._claim_idle_messages())

    async def _consume_events(self):
        while self._running:  # ❌ LOOP FOREVER
            # No idempotency checks ❌
            await handler(event)
```

## New Stateless Architecture

```python
# src/gleitzeit/events/stateless_event_consumer.py
class StatelessEventConsumer:
    def __init__(self):
        # ✅ Instance-specific consumer group
        self.consumer_group = f"gleitzeit-{instance_id}"
        # ✅ No _running flag!

    async def process_batch(self):
        # ✅ Process once and return
        # ✅ Idempotency checks built-in
        can_execute = await idempotency.check_can_execute()
        if can_execute:
            await handler(event)
        return processed_count
```

## Migration Steps

### Step 1: Replace Event Bus Creation

**Before:**
```python
# In system_manager.py or elsewhere
from gleitzeit.events.stream_event_bus import StreamEventBus

event_bus = StreamEventBus(redis_client)
await event_bus.start()  # Starts loops
```

**After:**
```python
from gleitzeit.events.stateless_event_consumer import StatelessEventConsumer
from gleitzeit.events.external_triggers import WebhookTrigger

# Create stateless consumer
consumer = StatelessEventConsumer(
    redis_client=redis_client,
    instance_id=instance_id  # Unique per instance
)

# Initialize lifecycle management
await consumer.initialize()

# Option 1: Add webhook endpoints for triggering
trigger = WebhookTrigger(consumer)
app.include_router(trigger.router)

# Option 2: Use timer-based triggering
timer = TimerTrigger(consumer, redis_client)
# Call timer.check_and_trigger() periodically
```

### Step 2: Update Handler Registration

**Before:**
```python
# No idempotency strategy
event_bus.register(EventType.TASK_READY, handle_task)
```

**After:**
```python
from gleitzeit.core.idempotency import IdempotencyStrategy

# With idempotency strategy
await consumer.register_handler(
    "task:ready",
    handle_task,
    IdempotencyStrategy.CHECK_STATE  # Specify strategy
)
```

### Step 3: Replace Start/Stop Logic

**Before:**
```python
class MyService:
    async def start(self):
        await self.event_bus.start()  # Starts persistent loops

    async def stop(self):
        await self.event_bus.stop()  # Stops loops
```

**After:**
```python
class MyService:
    async def start(self):
        await self.consumer.initialize()  # Just registers with TTL
        # No loops started!

    async def stop(self):
        await self.consumer.shutdown()  # Clean shutdown

    async def process_events(self):
        # Called by external trigger
        return await self.consumer.process_batch()
```

### Step 4: Add External Triggering

Choose your trigger mechanism:

#### Option A: HTTP Webhook
```python
# Add to FastAPI app
from gleitzeit.events.external_triggers import WebhookTrigger

trigger = WebhookTrigger(consumer)
app.include_router(trigger.router)

# Now can trigger via:
# POST /triggers/process
# POST /triggers/claim-idle
```

#### Option B: Kubernetes CronJob
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: gleitzeit-event-processor
spec:
  schedule: "*/1 * * * *"  # Every minute
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: processor
            image: gleitzeit:latest
            command: ["python", "-m", "gleitzeit.trigger"]
            env:
            - name: GLEITZEIT_TRIGGER_TYPE
              value: "k8s_cronjob"
          restartPolicy: OnFailure
```

#### Option C: AWS Lambda
```python
# lambda_function.py
from gleitzeit.events.external_triggers import LambdaTrigger

def lambda_handler(event, context):
    trigger = LambdaTrigger(consumer)
    return asyncio.run(trigger.handler(event, context))
```

#### Option D: Simple Cron
```bash
# crontab -e
* * * * * curl -X POST http://localhost:8000/triggers/process
```

### Step 5: Update SystemManager

**Remove reconciliation loops:**

```python
# BEFORE: src/gleitzeit/system/system_manager.py
class SystemManager:
    async def start_system(self):
        self._running = True
        asyncio.create_task(self._periodic_reconciliation_loop())  # ❌

    async def _periodic_reconciliation_loop(self):
        while self._running:  # ❌
            await self._reconcile_system()
            await asyncio.sleep(30)
```

**Replace with triggered reconciliation:**

```python
# AFTER: Stateless reconciliation
class SystemManager:
    async def start_system(self):
        # No loops! Just register components
        await self._register_components()

    async def reconcile_once(self):
        """Called by external trigger"""
        await self._reconcile_system()
        return {"reconciled": True}

# Add endpoint for triggering
@app.post("/system/reconcile")
async def trigger_reconciliation():
    return await system_manager.reconcile_once()
```

## Complete Example: Migrating a Service

### Original Service (Stateful)
```python
# services/task_processor.py
class TaskProcessor:
    def __init__(self):
        self.event_bus = StreamEventBus(redis)
        self._running = False

    async def start(self):
        self._running = True
        self.event_bus.register(EventType.TASK_READY, self.process_task)
        await self.event_bus.start()  # Starts loops

        # Start monitoring loop
        asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        while self._running:
            # Do monitoring
            await asyncio.sleep(60)

    async def process_task(self, event):
        # No idempotency check!
        task = await get_task(event.data['task_id'])
        result = await execute_task(task)
        await save_result(result)
```

### Migrated Service (Stateless)
```python
# services/task_processor_stateless.py
from gleitzeit.events.stateless_event_consumer import StatelessEventConsumer
from gleitzeit.core.idempotency import IdempotencyStrategy

class StatelessTaskProcessor:
    def __init__(self):
        self.consumer = StatelessEventConsumer(
            redis_client=redis,
            instance_id=f"processor-{uuid.uuid4().hex[:8]}"
        )
        # No _running flag!

    async def initialize(self):
        # Register handler with idempotency
        await self.consumer.register_handler(
            "task:ready",
            self.process_task,
            IdempotencyStrategy.CHECK_STATE
        )
        await self.consumer.initialize()

    async def process_task(self, event):
        # Idempotency already checked by consumer!
        task = await get_task(event.data['task_id'])
        result = await execute_task(task)
        await save_result(result)

    async def trigger_processing(self):
        """Called by external trigger"""
        stats = await self.consumer.process_batch()

        # Do monitoring (stateless)
        if stats['processed'] > 0:
            await self.record_metrics(stats)

        return stats

    async def shutdown(self):
        await self.consumer.shutdown()

# Add HTTP endpoint
@app.post("/tasks/process")
async def process_tasks():
    processor = StatelessTaskProcessor()
    await processor.initialize()
    try:
        return await processor.trigger_processing()
    finally:
        await processor.shutdown()
```

## Testing the Migration

### 1. Test Single Instance
```python
# test_stateless_processing.py
async def test_single_instance():
    consumer = StatelessEventConsumer(redis, "test-1")
    await consumer.initialize()

    # Register handler
    await consumer.register_handler(
        "test:event",
        handle_test,
        IdempotencyStrategy.CHECK_STATE
    )

    # Process once (no loops!)
    processed = await consumer.process_batch()
    assert processed >= 0

    await consumer.shutdown()
```

### 2. Test Multiple Instances
```python
async def test_multiple_instances():
    # Create multiple consumers with different IDs
    consumers = [
        StatelessEventConsumer(redis, f"instance-{i}")
        for i in range(3)
    ]

    # Initialize all
    for c in consumers:
        await c.initialize()

    # Each has its own consumer group - no collision!
    groups = [c.consumer_group for c in consumers]
    assert len(set(groups)) == 3  # All unique

    # Process in parallel
    results = await asyncio.gather(*[
        c.process_batch() for c in consumers
    ])

    # No message collision
    total = sum(results)

    # Cleanup
    for c in consumers:
        await c.shutdown()
```

### 3. Test Idempotency
```python
async def test_idempotency():
    consumer = StatelessEventConsumer(redis, "test-idempotent")

    processed_tasks = []

    async def track_task(event):
        processed_tasks.append(event.data['task_id'])

    await consumer.register_handler(
        "task:ready",
        track_task,
        IdempotencyStrategy.NEVER_SAFE  # Can't rerun
    )

    # First process
    await consumer.process_batch()
    count1 = len(processed_tasks)

    # Try again - should skip due to idempotency
    await consumer.process_batch()
    count2 = len(processed_tasks)

    assert count2 == count1  # No duplicates!
```

## Rollback Plan

If issues arise, you can run both systems in parallel:

```python
class HybridProcessor:
    def __init__(self):
        # Old system
        self.event_bus = StreamEventBus(redis)

        # New system
        self.consumer = StatelessEventConsumer(redis)

    async def start(self):
        # Start old system
        if ENABLE_OLD_SYSTEM:
            await self.event_bus.start()

        # Initialize new system
        if ENABLE_NEW_SYSTEM:
            await self.consumer.initialize()

    async def process(self):
        """Can be called by trigger or loop"""
        if ENABLE_NEW_SYSTEM:
            return await self.consumer.process_batch()
```

## Performance Comparison

### Old System (Loops)
- **CPU**: Constant usage from loops
- **Memory**: Grows over time (state accumulation)
- **Scaling**: Limited by shared consumer groups
- **Recovery**: Manual intervention needed

### New System (Stateless)
- **CPU**: Only when processing
- **Memory**: Constant (no state)
- **Scaling**: Linear with instances
- **Recovery**: Automatic via TTL and idempotency

## Checklist for Migration

- [ ] Replace StreamEventBus with StatelessEventConsumer
- [ ] Add idempotency strategies to all handlers
- [ ] Remove all `while self._running` loops
- [ ] Add external trigger mechanism
- [ ] Update deployment to include triggers
- [ ] Test with multiple instances
- [ ] Monitor for dead consumer accumulation
- [ ] Verify idempotency is working
- [ ] Remove old code after validation

## Common Issues and Solutions

### Issue: "How do I process continuously?"
**Solution**: Use frequent triggers (every second if needed) rather than loops.

### Issue: "Messages are being processed multiple times"
**Solution**: Check idempotency strategy. Use `NEVER_SAFE` for non-idempotent operations.

### Issue: "Dead consumers still accumulating"
**Solution**: Ensure all instances call `consumer.initialize()` to register with TTL.

### Issue: "Performance seems slower"
**Solution**: Adjust trigger frequency and batch size. Process more messages per trigger.

## Conclusion

The migration from stateful to stateless event processing enables:
- True horizontal scaling
- Deployment flexibility
- Resource efficiency
- Automatic recovery

Follow this guide to systematically migrate each component, testing thoroughly at each step.