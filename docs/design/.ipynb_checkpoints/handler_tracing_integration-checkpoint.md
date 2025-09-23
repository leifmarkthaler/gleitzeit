# Handler Tracing Integration with Existing Streams

## Current Stream Architecture

Gleitzeit uses sharded Redis streams for workflow coordination:

```
# Existing workflow streams (sharded)
{shard:N}:workflow:load       # Workflow submission
{shard:N}:workflow:submitted  # Workflow accepted
{shard:N}:workflow:completed  # Workflow finished

# Existing task streams (sharded)
{shard:N}:task:ready          # Tasks ready for execution
{shard:N}:task:completed      # Task completion events
{shard:N}:task:failed         # Task failure events
{shard:N}:task:retry          # Task retry events

# Special streams
{shard:N}:timer:scheduled     # Timer tasks
{shard:N}:signal:waiting      # Signal tasks
```

## Integration Strategy: Augment, Don't Replace

### Option 1: Enrich Existing Streams (RECOMMENDED)

Instead of creating new streams, **add handler tracking data to existing stream messages**:

```python
# Current task:completed message
{
    b"workflow_id": workflow_id,
    b"task_id": task_id,
    b"status": "completed",
    b"result": result_json
}

# Enhanced with handler tracking
{
    b"workflow_id": workflow_id,
    b"task_id": task_id,
    b"status": "completed",
    b"result": result_json,
    # NEW FIELDS
    b"handler_id": handler_id,          # Which handler processed it
    b"worker_id": worker_id,            # Which worker owns the handler
    b"instance_url": instance_url,      # Backend URL (e.g., ollama URL)
    b"duration_ms": duration_ms,        # Execution time
    b"handler_version": handler_version # Handler version for compatibility
}
```

**Advantages:**
- No new streams to manage
- Existing consumers continue working (they ignore unknown fields)
- Complete data in one place
- No synchronization issues

### Option 2: Parallel Audit Stream

Create a **separate, non-sharded audit stream** for handler events only:

```python
# Handler audit stream (global, not sharded)
handler:audit → Stream
  - All handler events across all shards
  - For monitoring/debugging only
  - Not used for workflow coordination

# Structure
{
    b"event_type": "task_executed",
    b"timestamp": timestamp,
    b"handler_id": handler_id,
    b"worker_id": worker_id,
    b"task_id": task_id,
    b"workflow_id": workflow_id,
    b"shard": shard,
    b"duration_ms": duration_ms
}
```

**Advantages:**
- Centralized audit log
- Easy to query all handler activity
- No impact on existing streams

**Disadvantages:**
- Additional stream to maintain
- Potential bottleneck (single stream)
- Data duplication

## Recommended Implementation

### Phase 1: Minimal Integration

```python
class TaskExecutionWorker:
    async def _emit_task_completed(self, task, result):
        """Emit task completion with handler tracking"""

        # Build message with handler info
        message = {
            b"workflow_id": task.workflow_id.encode(),
            b"task_id": task.id.encode(),
            b"status": b"completed",
            b"result": json.dumps(result).encode(),
            # Handler tracking (new)
            b"handler_id": self.handler_id.encode(),
            b"worker_id": self.config.worker_id.encode(),
            b"handler_protocol": task.protocol.encode() if task.protocol else b"",
        }

        # Add instance URL if available
        handler = self.handlers.get(task.protocol)
        if handler and hasattr(handler, 'base_url'):
            message[b"instance_url"] = handler.base_url.encode()

        # Emit to existing stream
        await self.redis.xadd(
            default_sharding.get_stream_key("task:completed", task.workflow_id).encode(),
            message
        )
```

### Phase 2: Handler Metadata Storage

Store handler metadata in **Redis hashes**, not streams:

```python
# Handler registry (not a stream)
handler:registry:{handler_id} → Hash
  - Static metadata about the handler
  - Updated only on startup/shutdown

# Handler metrics (not a stream)
handler:metrics:{handler_id}:daily → Sorted Set
  - Aggregated metrics
  - Time-series data for monitoring
```

### Phase 3: Optional Audit Stream

If detailed audit logging is needed, add a **TTL-limited audit stream**:

```python
# Audit stream with automatic cleanup
handler:audit → Stream (MAXLEN ~ 100000)
  - Recent events only
  - Automatically trimmed
  - For debugging, not operations
```

## Storage Layout

```
# Existing operational streams (unchanged)
{shard:0}:task:ready          → Stream (workflow operations)
{shard:0}:task:completed      → Stream (enhanced with handler_id)

# New metadata storage (not streams)
handler:registry:uuid-1234    → Hash (handler metadata)
handler:metrics:uuid-1234     → Sorted Set (performance metrics)
task:handler:{task_id}        → String (task→handler mapping)

# Optional audit stream (if needed)
handler:audit                 → Stream (MAXLEN, debugging only)
```

## Backward Compatibility

### Existing Workers Continue Working

```python
# Old worker (ignores new fields)
async def process_task_completed(self, message):
    workflow_id = message[b"workflow_id"].decode()
    task_id = message[b"task_id"].decode()
    # Works fine, ignores handler_id, worker_id, etc.

# New worker (uses new fields)
async def process_task_completed(self, message):
    workflow_id = message[b"workflow_id"].decode()
    task_id = message[b"task_id"].decode()
    handler_id = message.get(b"handler_id", b"unknown").decode()
    # Can use handler tracking data
```

## Query Patterns

### Finding Which Handler Processed a Task

```python
# Option 1: From task:completed stream
messages = await redis.xrevrange(f"{shard}:task:completed", "+", "-", count=1000)
for msg_id, data in messages:
    if data[b"task_id"] == task_id.encode():
        handler_id = data.get(b"handler_id", b"unknown").decode()
        break

# Option 2: From direct mapping (faster)
handler_id = await redis.get(f"task:handler:{task_id}")
```

### Handler Performance Analysis

```python
# Get handler metrics (from sorted set, not stream)
metrics = await redis.zrange(
    f"handler:metrics:{handler_id}:hourly",
    start_time,
    end_time,
    byscore=True
)
```

## Benefits of This Approach

1. **No Stream Conflicts**: Existing streams remain compatible
2. **Gradual Adoption**: Can be rolled out incrementally
3. **No Performance Impact**: Handler metadata in separate keys
4. **Backward Compatible**: Old workers continue functioning
5. **Flexible Queries**: Can query from streams or dedicated keys

## Migration Path

### Step 1: Add handler_id to messages
```python
# Just add handler_id to existing messages
message[b"handler_id"] = self.handler_id
```

### Step 2: Store handler metadata
```python
# Store in Redis hash on startup
await redis.hset(f"handler:registry:{handler_id}", metadata)
```

### Step 3: Add task mapping
```python
# Quick lookup for task→handler
await redis.set(f"task:handler:{task_id}", handler_id, ex=86400)
```

### Step 4: Optional audit stream
```python
# Only if detailed audit needed
await redis.xadd("handler:audit", audit_event, maxlen=100000)
```

## Conclusion

By **enriching existing streams** rather than creating new ones, we:
- Avoid conflicts with current architecture
- Maintain backward compatibility
- Keep the system simple
- Enable powerful tracing capabilities

The handler tracking becomes an **enhancement** to the existing system rather than a parallel structure, ensuring smooth integration with Gleitzeit's stream-based architecture.