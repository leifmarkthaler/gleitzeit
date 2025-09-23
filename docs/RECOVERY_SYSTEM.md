# Gleitzeit 0.0.7 Recovery System Documentation

## Overview

Gleitzeit implements a comprehensive 4-level recovery system that ensures no messages are lost and all failures are automatically recovered. The system is designed to be stateless, self-healing, and requires no manual intervention.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Recovery Levels](#recovery-levels)
3. [Message Flow](#message-flow)
4. [Configuration](#configuration)
5. [Implementation Details](#implementation-details)
6. [Monitoring](#monitoring)
7. [Troubleshooting](#troubleshooting)

## Architecture Overview

### Key Components

- **Redis Streams**: Message queue with consumer groups
- **BaseWorker**: Core worker implementation with recovery capabilities
- **PendingRecoveryMixin**: XCLAIM-based recovery for stuck messages
- **ComponentOrchestrator**: Worker lifecycle management
- **RetryManager**: Exponential backoff retry logic

### Design Principles

1. **Stateless**: No persistent failure tracking in workers
2. **Exactly-once delivery**: Consumer groups prevent duplicate processing
3. **Self-healing**: Automatic recovery at multiple levels
4. **No message loss**: Every failure path is covered

## Recovery Levels

### Level 1: ACK Control (Immediate)

**When**: Message processing fails
**How**: Worker returns `False` from `process_message()`
**Result**: Message stays pending in Redis Stream

```python
async def process_message(self, stream: str, message_id: str, data: Dict) -> bool:
    try:
        # Process message
        result = await self.handle_task(data)
        return True  # Success - ACK the message
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        return False  # Failure - Don't ACK, leave for retry
```

**Benefits**:
- No data loss on failure
- Message remains in stream
- Available for retry

### Level 2: New and Undelivered Message Processing

**When**: Worker starts or restarts
**How**: Workers read with `">"` cursor for new messages
**Result**: Worker processes all undelivered messages (including pre-existing ones)

```python
def get_stream_patterns(self) -> Dict[bytes, bytes]:
    patterns = {}
    for base_stream in self.get_base_streams():
        for shard in self.assigned_shards:
            # Use ">" to read new messages (including those from before group creation)
            # The pending recovery mixin handles stuck messages separately
            patterns[f"{{shard:{shard}}}:{base_stream}".encode()] = b">"
    return patterns
```

**Important Note**: Using `"0"` only reads *pending* messages (previously delivered but not ACKed). This causes a **silent fail** when messages exist in the stream before the consumer group is created - they are neither pending nor new to the group. Using `">"` ensures all undelivered messages are processed.

**Benefits**:
- Handles bootstrap case (messages before group creation)
- No silent message loss
- Works with pending recovery for complete coverage

### Level 3: XCLAIM Recovery (Every 60 seconds)

**When**: Worker dies permanently (messages stuck > 5 minutes)
**How**: Healthy workers claim stuck messages via XCLAIM
**Result**: Orphaned messages are redistributed

```python
class PendingRecoveryMixin:
    CLAIM_IDLE_TIME = 300000  # 5 minutes in milliseconds
    RECOVERY_INTERVAL = 60    # Check every 60 seconds

    async def recover_pending_messages(self):
        # Find messages idle > 5 minutes
        pending = await self.redis.execute_command(
            b"XPENDING", stream_key, group, b"IDLE", b"300000", b"-", b"+", b"100"
        )

        # Claim ownership
        if pending:
            await self.redis.execute_command(
                b"XCLAIM", stream_key, group, worker_id, b"300000", *message_ids
            )
```

**Benefits**:
- Handles permanently dead workers
- Prevents message abandonment
- Automatic redistribution

### Level 4: Exponential Backoff Retry (Configurable)

**When**: Task fails but has retries remaining
**How**: Timer-based scheduling with exponential delays
**Result**: Automatic retry with increasing delays

```python
async def handle_task_failure(self, task_id: str, workflow_id: str, error: str):
    retry_manager = RetryManager(task.retry_config)

    if retry_manager.should_retry(current_attempt, exception):
        delay = retry_manager.calculate_delay(current_attempt)

        # Schedule retry via timer
        await self.redis.zadd(
            "timers:pending",
            {f"{workflow_id}:{task_id}:retry": time.time() + delay}
        )
```

**Retry Configuration**:
```yaml
retry:
  max_attempts: 3
  strategy: exponential  # or 'linear', 'fixed'
  base_delay: 1.0        # seconds
  max_delay: 60.0        # maximum delay
  multiplier: 2.0        # exponential multiplier
  jitter: 0.1            # randomization factor
```

## Understanding Redis Streams Cursors

### Critical Distinction: "0" vs ">"

Redis Streams consumer groups use cursors to determine what messages to read:

- **`"0"`**: Read only **pending** messages (previously delivered to this consumer but not ACKed)
  - Does NOT read messages that existed before the consumer group was created
  - Only useful for recovering messages after a worker crash
  - **Can cause silent message loss** if used as the primary cursor

- **`">"`**: Read **new** messages (not yet delivered to any consumer in the group)
  - Includes messages that existed before the consumer group was created
  - Ensures all undelivered messages are eventually processed
  - **Recommended as the default cursor**

### Why This Matters

When a consumer group is created on an existing stream with existing messages:
1. Those messages are neither "pending" (never delivered) nor "new" (already in stream)
2. Using `"0"` will skip them entirely (silent fail)
3. Using `">"` will correctly process them

## Message Flow

### Success Path
```
New Message → XREADGROUP (">") → Process → Success → XACK → Complete
```

### Failure Paths

#### Transient Failure (Retry)
```
New Message
  → XREADGROUP (becomes pending)
  → Process → Failure
  → Don't ACK (stays pending)
  → Schedule exponential backoff
  → Timer expires
  → Emit to retry stream
  → Process again → Success → XACK
```

#### Worker Crash
```
New Message
  → XREADGROUP (becomes pending for worker-1)
  → Worker-1 crashes
  → ComponentOrchestrator restarts worker-1
  → Worker-1 reads with "0" cursor
  → Gets its pending message
  → Process → Success → XACK
```

#### Permanent Worker Death
```
New Message
  → XREADGROUP (becomes pending for worker-1)
  → Worker-1 dies permanently
  → 5 minutes pass
  → Worker-2's recovery task runs
  → XPENDING finds stuck message
  → XCLAIM transfers to worker-2
  → Worker-2 processes → Success → XACK
```

## Configuration

### Worker Configuration

```python
@dataclass
class WorkerConfig:
    worker_type: str
    worker_id: str
    consumer_group: str
    max_concurrent: int = 10
    batch_size: int = 10
    block_timeout: int = 5000  # milliseconds
    heartbeat_interval: int = 30  # seconds
```

### Recovery Configuration

```python
class PendingRecoveryMixin:
    # When to claim stuck messages
    CLAIM_IDLE_TIME = 300000  # 5 minutes in milliseconds

    # How often to check for stuck messages
    RECOVERY_INTERVAL = 60    # seconds

    # Maximum messages to claim at once
    MAX_CLAIM_BATCH = 100
```

### Retry Configuration

```python
@dataclass
class RetryConfig:
    max_retries: int = 3
    strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    base_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: float = 0.1
```

## Implementation Details

### Consumer Groups

All workers of the same type share a consumer group:

```python
# Multiple TaskExecutionWorkers in same group
TaskExecutionWorker-1 ─┐
TaskExecutionWorker-2 ─┼─→ "task-execution-group"
TaskExecutionWorker-3 ─┘
```

Redis ensures each message goes to exactly one worker in the group.

### Pending Entries List (PEL)

When a worker reads a message with XREADGROUP:
1. Message immediately becomes "pending" for that worker
2. Message stays pending until ACK'd
3. Other workers cannot see this message
4. XCLAIM can transfer ownership after timeout

### Dead Letter Queue

Failed messages are also logged to DLQ for monitoring:

```python
async def _emit_to_dead_letter_queue(self, stream: str, msg_id: str, data: Any, error: str):
    await self.redis.xadd(
        b"dead_letter:tasks",
        {
            b"original_stream": stream.encode(),
            b"message_id": msg_id.encode(),
            b"error": error.encode(),
            b"failed_at": datetime.utcnow().isoformat().encode(),
            b"worker_id": self.config.worker_id.encode()
        }
    )
```

## Monitoring

### Health Checks

ComponentOrchestrator monitors worker health:

```python
async def check_worker_health(self, worker_id: str) -> bool:
    # Check heartbeat timestamp
    last_heartbeat = await self.redis.hget(
        f"worker:metrics:{worker_id}",
        "last_heartbeat"
    )

    if not last_heartbeat:
        return False

    age = datetime.utcnow() - datetime.fromisoformat(last_heartbeat)
    return age.total_seconds() < 60  # Healthy if heartbeat < 60s old
```

### Recovery Metrics

Recovery events are logged to metrics stream:

```python
await self.redis.xadd(
    b"metrics:recovery",
    {
        b"event": b"pending_recovery",
        b"stream": stream_key,
        b"claimed_count": str(claimed_count).encode(),
        b"claimer": worker_id.encode(),
        b"timestamp": datetime.utcnow().isoformat().encode()
    }
)
```

### Monitoring Queries

Check pending messages:
```bash
# Count pending messages per stream
redis-cli XPENDING {shard:0}:task:ready task-execution-group

# Get detailed pending list
redis-cli XPENDING {shard:0}:task:ready task-execution-group IDLE 300000 - + 100
```

Check dead letter queue:
```bash
# Read recent DLQ entries
redis-cli XRANGE dead_letter:tasks - + COUNT 10
```

Check worker metrics:
```bash
# Get worker status
redis-cli HGETALL "worker:metrics:exec-worker-1"
```

## Troubleshooting

### Common Issues

#### Messages Stuck as Pending

**Symptom**: Messages remain pending indefinitely
**Cause**: Worker died without recovery running
**Solution**:
- Ensure PendingRecoveryMixin is enabled
- Check CLAIM_IDLE_TIME setting
- Manually XCLAIM if needed

#### Infinite Retry Loop

**Symptom**: Task keeps retrying forever
**Cause**: Missing max_retries configuration
**Solution**:
- Set max_retries in task configuration
- Check RetryManager.should_retry logic

#### Messages Not Being Processed (Silent Fail)

**Symptom**: Messages exist in stream but workers don't process them
**Cause**: Messages added before consumer group creation with "0" cursor
**Solution**:
- Use ">" cursor in BaseWorker.get_stream_patterns
- This reads all undelivered messages, not just pending ones
- Critical for bootstrap scenarios

**Diagnosis**:
```bash
# Check if consumer group has read messages
redis-cli XINFO GROUPS {shard:0}:workflow:load

# If last-delivered-id is "0-0", group hasn't read any messages
# Even though messages exist in the stream
```

#### Workers Not Processing Their Own Pending

**Symptom**: Worker doesn't recover its own pending messages after restart
**Cause**: No pending recovery mechanism
**Solution**:
- Ensure PendingRecoveryMixin is enabled
- XCLAIM will recover stuck messages after timeout

### Manual Recovery

Force claim stuck messages:
```python
# Emergency manual claim
async def manual_claim(redis, stream, group, new_owner, min_idle=300000):
    pending = await redis.execute_command(
        b"XPENDING", stream, group, b"IDLE", str(min_idle), b"-", b"+", b"1000"
    )

    message_ids = [msg[0] for msg in pending]

    if message_ids:
        await redis.execute_command(
            b"XCLAIM", stream, group, new_owner,
            str(min_idle), *message_ids, b"FORCE"
        )
```

### Debug Logging

Enable detailed recovery logging:
```python
import logging
logging.getLogger("gleitzeit.workers.pending_recovery").setLevel(logging.DEBUG)
logging.getLogger("gleitzeit.workers.base").setLevel(logging.DEBUG)
```

## Best Practices

1. **Set appropriate timeouts**:
   - CLAIM_IDLE_TIME: 5-10 minutes for production
   - RECOVERY_INTERVAL: 30-60 seconds
   - Heartbeat: 30 seconds

2. **Configure retry limits**:
   - Always set max_retries
   - Use exponential backoff for transient failures
   - Set reasonable max_delay

3. **Monitor metrics**:
   - Track pending queue depth
   - Alert on DLQ growth
   - Monitor recovery events

4. **Test failure scenarios**:
   - Kill workers during processing
   - Simulate network partitions
   - Test with high failure rates

## Summary

The Gleitzeit recovery system provides comprehensive failure handling:

- **No message loss**: Every failure path covered, including bootstrap scenarios
- **Automatic recovery**: No manual intervention needed
- **Configurable**: Tune timeouts and retries for your needs
- **Observable**: Metrics and monitoring built-in
- **Battle-tested**: Handles worker crashes, network issues, and permanent failures

**Critical Implementation Note**: Always use `">"` as the XREADGROUP cursor in BaseWorker to avoid silent message loss. The combination of `">"` for reading new messages and PendingRecoveryMixin for claiming stuck messages ensures complete coverage.

The system ensures that every message is eventually processed successfully or explicitly marked as permanently failed after exhausting retries.