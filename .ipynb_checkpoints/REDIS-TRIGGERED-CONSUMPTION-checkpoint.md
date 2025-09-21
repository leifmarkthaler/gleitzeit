# Redis-Triggered Consumption Pattern

## Executive Summary

This document describes the Redis-triggered consumption pattern implemented in Gleitzeit, which eliminates internal polling loops and creates a truly stateless, event-driven architecture where Redis itself orchestrates all event consumption.

## Architecture Overview

### Traditional Pattern (WITH Loops)
```
┌─────────────────────────────────────┐
│   Python Process (SystemManager)     │
│                                      │
│  while running:  ◄──── LOOP!        │
│    messages = xreadgroup()          │
│    process(messages)                │
│                                      │
└─────────────────────────────────────┘
```

### Redis-Triggered Pattern (NO Loops)
```
┌─────────────────────────────────────┐
│   Redis Streams                      │
│                                      │
│  trigger:stream ──► Consumer        │
│                     (blocks)        │
│                     (processes)     │
│                     (exits)         │
│                                      │
└─────────────────────────────────────┘
```

## Components

### 1. TriggeredStreamConsumer
Location: `src/gleitzeit/events/triggered_stream_consumer.py`

**Key Features:**
- No internal loops
- Waits for triggers via Redis XREADGROUP
- Processes messages only when triggered
- Truly stateless operation

**Trigger Stream:** `gleitzeit:consumer:triggers`

**API:**
```python
# Wait for a trigger
trigger = await consumer.wait_for_trigger(timeout_ms=5000)

# Process messages once (no loop)
processed = await consumer.consume_once(max_messages=100)

# Send a trigger
await consumer.trigger_consumption("consume", {"reason": "scheduled"})
```

### 2. StreamTriggerMixin
Location: `src/gleitzeit/system/mixins/stream_trigger.py`

**Integration Points:**
- Replaces loop-based stream consumption
- Manages trigger processing
- Enables auto-triggering based on stream activity

## Trigger Types

### 1. Manual Triggers
Sent explicitly by services or administrators:
```python
await redis.xadd("gleitzeit:consumer:triggers", {
    "action": "consume",
    "source": "manual",
    "reason": "admin_request"
})
```

### 2. Event-Based Triggers
Automatically sent when events are emitted:
```python
# When an event is emitted, trigger consumption
await emit_and_trigger(event)
```

### 3. Scheduled Triggers
Sent by external schedulers (cron, Kubernetes CronJob, etc.):
```python
await redis.xadd("gleitzeit:consumer:triggers", {
    "action": "consume",
    "source": "scheduler",
    "reason": "periodic_check"
})
```

### 4. Activity-Based Triggers
Triggered when streams have pending messages:
```python
has_messages = await consumer.auto_trigger_on_stream_activity()
if has_messages:
    await consumer.trigger_consumption("consume")
```

## Trigger Actions

| Action | Description | Response |
|--------|-------------|----------|
| `consume` | Process available messages | Consume once from all streams |
| `discover` | Rediscover event streams | Update stream list |
| `shutdown` | Graceful shutdown | Stop processing and exit |
| `cleanup` | Clean up old messages | Process idle/stuck messages |

## Implementation Examples

### 1. Kubernetes Job
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: gleitzeit-trigger
spec:
  schedule: "*/1 * * * *"  # Every minute
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: trigger
            image: redis:latest
            command:
            - redis-cli
            - XADD
            - gleitzeit:consumer:triggers
            - action
            - consume
            - source
            - k8s-cronjob
```

### 2. AWS Lambda Trigger
```python
import redis

def lambda_handler(event, context):
    r = redis.Redis(host='redis-cluster.aws.com')
    r.xadd('gleitzeit:consumer:triggers', {
        'action': 'consume',
        'source': 'lambda',
        'reason': 'sqs_messages_available'
    })
```

### 3. Systemd Timer
```ini
[Unit]
Description=Trigger Gleitzeit Consumption

[Timer]
OnCalendar=*:0/5  # Every 5 minutes
Persistent=true

[Service]
Type=oneshot
ExecStart=/usr/bin/redis-cli XADD gleitzeit:consumer:triggers action consume source systemd
```

## Migration Path

### Phase 1: Parallel Operation
- Keep existing MultiplexedStreamConsumer
- Add TriggeredStreamConsumer in parallel
- Test trigger-based consumption

### Phase 2: Gradual Migration
- Route specific event types to triggered consumer
- Monitor performance and reliability
- Adjust trigger frequency as needed

### Phase 3: Full Migration
- Replace all loop-based consumers
- Remove MultiplexedStreamConsumer
- Operate fully on triggers

## Benefits

### 1. True Statelessness
- No internal state management
- No running processes required
- Can run in serverless environments

### 2. Resource Efficiency
- Processes only run when needed
- No idle CPU consumption
- Perfect for container orchestration

### 3. Scalability
- Unlimited horizontal scaling
- No coordination between consumers
- Redis handles all orchestration

### 4. Operational Flexibility
- Can be triggered from anywhere
- Easy integration with existing infrastructure
- Works with any scheduler or orchestrator

## Configuration

### Environment Variables
```bash
# Trigger stream configuration
GLEITZEIT_TRIGGER_STREAM=gleitzeit:consumer:triggers
GLEITZEIT_TRIGGER_GROUP=consumer-triggers
GLEITZEIT_TRIGGER_TIMEOUT_MS=5000

# Auto-trigger configuration
GLEITZEIT_AUTO_TRIGGER_ENABLED=true
GLEITZEIT_AUTO_TRIGGER_INTERVAL=1000
```

### Redis Streams Configuration
```python
# Max trigger stream length (circular buffer)
TRIGGER_STREAM_MAXLEN = 1000

# Consumer group settings
CONSUMER_GROUP = "gleitzeit-processors"
CONSUMER_BLOCK_MS = 0  # Block indefinitely
```

## Monitoring

### Key Metrics
1. **Trigger Lag**: Pending triggers in stream
2. **Processing Time**: Duration of consume_once()
3. **Messages Per Trigger**: Efficiency metric
4. **Trigger Frequency**: How often triggers arrive

### Health Checks
```python
async def check_trigger_health():
    # Check trigger stream exists
    exists = await redis.exists("gleitzeit:consumer:triggers")

    # Check for pending triggers
    info = await redis.xinfo_stream("gleitzeit:consumer:triggers")
    pending = info.get('length', 0)

    # Check consumer group lag
    groups = await redis.xinfo_groups("gleitzeit:consumer:triggers")

    return {
        "healthy": exists and pending < 100,
        "pending_triggers": pending,
        "consumer_groups": len(groups)
    }
```

## Troubleshooting

### No Consumption Occurring
1. Check trigger stream exists
2. Verify consumer groups are created
3. Ensure triggers are being sent
4. Check Redis connectivity

### Delayed Processing
1. Increase trigger frequency
2. Check for blocking operations
3. Verify Redis performance
4. Monitor network latency

### Duplicate Processing
1. Ensure proper message acknowledgment
2. Check consumer group configuration
3. Verify idempotency mechanisms
4. Monitor for consumer failures

## Future Enhancements

1. **Smart Triggering**: ML-based trigger prediction
2. **Priority Triggers**: High-priority event processing
3. **Batch Triggering**: Process multiple streams per trigger
4. **Trigger Analytics**: Performance optimization based on patterns