# Stateless LogCollector Design for Gleitzeit 0.0.7

**Date:** 2025-09-30
**Architecture:** Modular, Stateless, Redis Cluster with Sharding

---

## Architecture Audit Summary

### Current Gleitzeit Design Principles

Based on audit of the codebase, Gleitzeit 0.0.7 follows these architectural patterns:

#### 1. **Stateless Service Pattern**
- ✅ **Example**: `StatelessRetryService` (stateless_retry_service.py)
  - All state in Redis
  - Static methods or instance methods that don't hold state
  - Lua scripts for atomic operations
  - No background loops or threads

- ✅ **Example**: `StatelessSignalManager` (stateless_signal_manager.py)
  - Completely stateless
  - All signal state in Redis
  - Processing happens only when invoked

#### 2. **Worker Pattern**
- ✅ **Example**: `BaseWorker` (workers/base.py)
  - Connects to Redis Cluster
  - Processes messages from streams
  - Uses semaphore for concurrency
  - Heartbeat for health monitoring
  - Graceful shutdown support

#### 3. **Sharding Strategy**
- ✅ **ClusterShardingStrategy** (core/sharding.py)
  - 16 logical shards
  - Hash tag routing: `{shard:N}:key:type`
  - Workflow locality (all workflow keys on same shard)
  - Ensures atomic operations work

#### 4. **Configuration-Driven**
- ✅ Handlers configured in `gleitzeit.yaml`
- ✅ Workers configured with handler configs
- ✅ Modular: each handler/worker independently configured
- ✅ Execution modes: native, subprocess, container, remote

---

## LogCollector Design Options

Given the architecture, there are **3 viable approaches** to implement LogCollector:

---

## Option 1: **Stateless Log Service** (Recommended)

Similar to `StatelessRetryService` - a pure service class with no state.

### Implementation

```python
# src/gleitzeit/core/stateless_log_service.py

class StatelessLogService:
    """
    Completely stateless log service using Redis for storage.

    Follows the same pattern as StatelessRetryService and
    StatelessSignalManager.
    """

    # Lua script for atomic log writing with TTL
    WRITE_LOG_SCRIPT = """
    local log_key = KEYS[1]
    local log_data = ARGV[1]
    local ttl = tonumber(ARGV[2])

    -- Write log entry
    redis.call('set', log_key, log_data)

    -- Set TTL
    if ttl > 0 then
        redis.call('expire', log_key, ttl)
    end

    return 1
    """

    @staticmethod
    async def write_log(
        redis,
        level: str,
        message: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        component: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
        ttl: int = 604800  # 7 days default
    ) -> str:
        """
        Write a log entry to Redis.

        Returns:
            Log entry ID
        """
        import json
        import uuid
        from datetime import datetime
        from gleitzeit.core.sharding import default_sharding

        # Generate log ID
        timestamp = int(datetime.utcnow().timestamp() * 1000)
        log_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"

        # Determine shard (use workflow_id if available for locality)
        if workflow_id:
            shard = default_sharding.get_shard(workflow_id)
        else:
            # System logs go to shard 0
            shard = 0

        # Build log entry
        log_entry = {
            "log_id": log_id,
            "timestamp": timestamp,
            "level": level,
            "message": message,
            "component": component,
            "workflow_id": workflow_id or "",
            "task_id": task_id or "",
            "metadata": metadata or {}
        }

        # Store log entry with hash tag for cluster routing
        log_key = f"{{shard:{shard}}}:log:{level.lower()}:{log_id}"

        await redis.set(
            log_key,
            json.dumps(log_entry),
            ex=ttl
        )

        # Add to level-specific index (for querying)
        index_key = f"{{shard:{shard}}}:log:index:{level.lower()}"
        await redis.zadd(
            index_key,
            {log_id: timestamp}
        )
        await redis.expire(index_key, ttl)

        # Add to workflow index if workflow_id provided
        if workflow_id:
            workflow_log_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}"
            await redis.zadd(
                workflow_log_key,
                {log_id: timestamp}
            )
            await redis.expire(workflow_log_key, ttl)

        # Add to task index if task_id provided
        if task_id:
            task_log_key = f"{{shard:{shard}}}:log:task:{task_id}"
            await redis.zadd(
                task_log_key,
                {log_id: timestamp}
            )
            await redis.expire(task_log_key, ttl)

        return log_id

    @staticmethod
    async def query_logs(
        redis,
        level: Optional[str] = None,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Query logs from Redis.

        Uses indexes for efficient querying.
        """
        import json
        from gleitzeit.core.sharding import default_sharding

        # Determine which index to query
        if workflow_id:
            shard = default_sharding.get_shard(workflow_id)
            index_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}"
        elif task_id:
            # Need workflow_id to determine shard for task
            # This is a limitation - could store task→workflow mapping
            raise ValueError("task_id requires workflow_id for sharding")
        elif level:
            # Query all shards for this level (expensive!)
            # Alternative: only query shard 0 for system logs
            shard = 0
            index_key = f"{{shard:{shard}}}:log:index:{level.lower()}"
        else:
            # Default to system logs on shard 0
            shard = 0
            index_key = f"{{shard:{shard}}}:log:index:info"

        # Get log IDs from index (sorted by timestamp)
        min_score = start_time if start_time else "-inf"
        max_score = end_time if end_time else "+inf"

        log_ids = await redis.zrevrangebyscore(
            index_key,
            max_score,
            min_score,
            start=offset,
            num=limit
        )

        # Fetch log entries
        logs = []
        for log_id in log_ids:
            # Reconstruct log key
            log_level = level.lower() if level else "info"
            log_key = f"{{shard:{shard}}}:log:{log_level}:{log_id.decode()}"

            log_data = await redis.get(log_key)
            if log_data:
                logs.append(json.loads(log_data))

        return logs
```

### Integration with LoggingMixin

```python
# Update src/gleitzeit/core/logging_mixin.py

from gleitzeit.core.stateless_log_service import StatelessLogService

# Replace line 16:
# get_log_collector = lambda: None

# With:
get_log_service = StatelessLogService

# Update _log method (line 181):
async def _log(
    self,
    level: LogLevel,
    message: str,
    context: Dict[str, Any]
) -> None:
    """Log via StatelessLogService."""

    # Get Redis connection from context or worker
    redis = context.pop('redis', None) or getattr(self, 'redis', None)

    if redis:
        try:
            await StatelessLogService.write_log(
                redis=redis,
                level=level.name,
                message=message,
                workflow_id=context.get('workflow_id'),
                task_id=context.get('task_id'),
                component=self._component_name,
                metadata=context
            )
        except Exception as e:
            logger.error(f"Failed to write log to Redis: {e}")
            self._fallback_log(level, message, context)
    else:
        # No Redis available, use fallback
        self._fallback_log(level, message, context)
```

### Pros
✅ Follows existing stateless pattern
✅ No new infrastructure needed
✅ Integrates with sharding strategy
✅ Simple to implement and test
✅ Works with existing Redis connections
✅ No coordination between instances

### Cons
❌ Requires passing Redis connection to logging calls
❌ Query performance limited (need to scan shards)
❌ TTL-based retention only (no archival)

---

## Option 2: **Dedicated Log Worker**

Create a worker that consumes log messages from a Redis stream.

### Implementation

```python
# src/gleitzeit/workers/log_collector_worker.py

class LogCollectorWorker(BaseWorker):
    """
    Worker that consumes log messages and stores them in Redis.

    Follows the BaseWorker pattern.
    """

    LOG_STREAM = "logs:stream"

    async def process_message(self, message_id: bytes, message: Dict) -> bool:
        """Process a log message."""

        log_data = json.loads(message[b'data'])

        # Store log using StatelessLogService
        await StatelessLogService.write_log(
            redis=self.redis,
            level=log_data['level'],
            message=log_data['message'],
            workflow_id=log_data.get('workflow_id'),
            task_id=log_data.get('task_id'),
            component=log_data.get('component', 'unknown'),
            metadata=log_data.get('metadata', {})
        )

        return True

    async def _consume_logs(self):
        """Consume logs from all shards."""

        for shard in self.assigned_shards:
            stream_key = f"{{shard:{shard}}}:{self.LOG_STREAM}"

            # Read from stream
            messages = await self.redis.xread(
                {stream_key: ">"},
                count=self.config.batch_size,
                block=self.config.block_timeout
            )

            # Process messages
            for stream, msg_list in messages:
                for message_id, message in msg_list:
                    await self.process_message(message_id, message)
```

### LoggingMixin Integration

```python
async def _log(self, level, message, context):
    """Publish log to stream for worker to consume."""

    redis = getattr(self, 'redis', None)
    if not redis:
        self._fallback_log(level, message, context)
        return

    # Determine shard
    workflow_id = context.get('workflow_id')
    if workflow_id:
        shard = default_sharding.get_shard(workflow_id)
    else:
        shard = 0

    # Publish to stream
    stream_key = f"{{shard:{shard}}}:logs:stream"

    log_data = {
        'level': level.name,
        'message': message,
        'component': self._component_name,
        'workflow_id': workflow_id or '',
        'task_id': context.get('task_id', ''),
        'metadata': json.dumps(context)
    }

    await redis.xadd(stream_key, {'data': json.dumps(log_data)})
```

### Configuration

```yaml
# gleitzeit.yaml
workers:
  - worker_type: log_collector
    worker_class: gleitzeit.workers.log_collector_worker.LogCollectorWorker
    count: 1  # One per instance (or shard)
    max_concurrent: 10
    batch_size: 50
    block_timeout: 1000
```

### Pros
✅ Decouples log writing from business logic
✅ Batching for efficiency
✅ Can add processing logic (filtering, aggregation)
✅ Follows existing worker pattern
✅ Horizontally scalable

### Cons
❌ Additional worker to manage
❌ Slight latency (async via stream)
❌ Stream storage overhead
❌ More complex error handling

---

## Option 3: **Hybrid: Direct Write + Worker for Indexing**

Combine both approaches for best of both worlds.

### Design

1. **LoggingMixin** writes logs directly to Redis (fast, synchronous)
2. **LogIndexerWorker** consumes logs and builds indexes (async, eventual consistency)

```python
# Direct write (sync)
async def _log(self, level, message, context):
    redis = getattr(self, 'redis', None)
    if redis:
        # Write log immediately (no indexing yet)
        log_key = f"{{shard:{shard}}}:log:raw:{timestamp}-{uuid}"
        await redis.set(log_key, json.dumps(log_data), ex=ttl)

        # Publish to indexing stream
        await redis.xadd(
            f"{{shard:{shard}}}:logs:index:stream",
            {'log_key': log_key}
        )

# Worker indexes logs (async)
class LogIndexerWorker(BaseWorker):
    async def process_message(self, message_id, message):
        log_key = message[b'log_key'].decode()

        # Read log
        log_data = json.loads(await self.redis.get(log_key))

        # Build indexes
        await self._index_log(log_data)
```

### Pros
✅ Fast log writes (no indexing delay)
✅ Complex indexing offloaded to worker
✅ Can rebuild indexes without losing logs
✅ Best query performance

### Cons
❌ Most complex to implement
❌ Two components to maintain
❌ Eventual consistency for queries

---

## Recommended Approach: **Option 1 (Stateless Service)**

### Rationale

1. **Simplest** - Follows existing `StatelessRetryService` pattern
2. **No new infrastructure** - Uses existing Redis connections
3. **Immediate consistency** - Logs immediately queryable
4. **Modular** - Can be used from any component
5. **Stateless** - Respects architecture principles

### Implementation Plan

1. Create `src/gleitzeit/core/stateless_log_service.py`
2. Update `logging_mixin.py` to use StatelessLogService
3. Update API endpoints to use StatelessLogService.query_logs()
4. Add configuration for log TTL and retention
5. Add audit log support

---

## Key Design Decisions

### 1. **Sharding Strategy for Logs**

**Workflow Logs** → Same shard as workflow (locality)
```python
shard = default_sharding.get_shard(workflow_id)
key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:{log_id}"
```

**System Logs** → Shard 0 (centralized)
```python
shard = 0
key = f"{{shard:0}}:log:system:{log_id}"
```

**Error Logs** → Per shard with level index
```python
shard = default_sharding.get_shard(workflow_id) if workflow_id else 0
key = f"{{shard:{shard}}}:log:error:{log_id}"
index = f"{{shard:{shard}}}:log:index:error"  # sorted set by timestamp
```

### 2. **Index Structure**

```
# Log entry
{shard:5}:log:error:1234567890-abc123 → {log_data}

# Level index (for queries)
{shard:5}:log:index:error → sorted set {log_id: timestamp}

# Workflow index (for workflow queries)
{shard:5}:log:workflow:wf123 → sorted set {log_id: timestamp}

# Task index (for task queries)
{shard:5}:log:task:task456 → sorted set {log_id: timestamp}
```

### 3. **TTL & Retention**

- **Default TTL**: 7 days (604800 seconds)
- **Configurable** per log level in config
- **Automatic cleanup** via Redis TTL
- **Archival** (future): Export to S3/filesystem before expiry

### 4. **Audit Logs**

Separate pattern for compliance:

```python
# Audit logs stored separately with longer TTL
audit_key = f"{{shard:{shard}}}:audit:{action}:{timestamp}-{uuid}"
audit_index = f"{{shard:{shard}}}:audit:index:{user}"

# 90 day retention for audit
ttl = 7776000
```

---

## Configuration Example

```yaml
# gleitzeit.yaml

logging:
  enabled: true

  # Log levels to store in Redis
  levels:
    - DEBUG
    - INFO
    - WARNING
    - ERROR
    - CRITICAL

  # TTL by level (seconds)
  ttl:
    DEBUG: 86400      # 1 day
    INFO: 604800      # 7 days
    WARNING: 1209600  # 14 days
    ERROR: 2592000    # 30 days
    CRITICAL: 2592000 # 30 days

  # Audit logs
  audit:
    enabled: true
    ttl: 7776000  # 90 days
    actions:
      - workflow_submit
      - workflow_cancel
      - task_retry
      - task_cancel

  # Indexes to maintain
  indexes:
    - workflow  # Index by workflow_id
    - task      # Index by task_id
    - level     # Index by log level
    - component # Index by component name
```

---

## Migration Path

### Phase 1: Basic Implementation
1. ✅ Create StatelessLogService
2. ✅ Update LoggingMixin to use it
3. ✅ Update API endpoints for querying
4. ✅ Test with existing workers

### Phase 2: Enhanced Features
5. ✅ Add audit logging
6. ✅ Add component-based indexes
7. ✅ Add time-range queries
8. ✅ Add log aggregation

### Phase 3: Production Ready
9. ✅ Add archival to S3/filesystem
10. ✅ Add log streaming/export APIs
11. ✅ Add log analytics/metrics
12. ✅ Add alerting on error patterns

---

## Conclusion

The **Stateless Log Service** approach best fits Gleitzeit's modular, stateless architecture:

- ✅ **Stateless** - No service state, all in Redis
- ✅ **Modular** - Independent service, callable from anywhere
- ✅ **Sharded** - Respects workflow locality
- ✅ **Simple** - Minimal new code
- ✅ **Scalable** - Works with Redis Cluster

This design enables full logging capabilities while maintaining architectural consistency with existing services like StatelessRetryService and StatelessSignalManager.
