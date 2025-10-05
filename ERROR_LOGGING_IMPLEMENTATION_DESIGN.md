# Error Logging Implementation with Global Index

**Date:** 2025-09-30
**Scope:** Implement error logging to fix `/system/logs/errors` endpoint
**Approach:** Stateless Log Service with Global Index

---

## Objective

Implement Redis-based error logging so the `/system/logs/errors` API endpoint returns actual error data instead of empty arrays.

---

## Current State

### What Exists
- ✅ API endpoint: `/system/logs/errors` (system.py:291-318)
- ✅ LoggingMixin infrastructure (logging_mixin.py)
- ✅ Workers logging errors via `logger.error()` (51 calls across 15 files)
- ✅ Sharding system (ClusterShardingStrategy)

### What's Missing
- ❌ Errors only written to log files, not Redis
- ❌ LogCollector returns None (line 16: `get_log_collector = lambda: None`)
- ❌ API endpoint searches for `*:error:*` pattern → 0 results

---

## Design: Global Index Architecture

### Key Principle
**Write to workflow shard (locality) + Write to global index (queryability)**

This provides:
1. ✅ Fast workflow-specific queries (use workflow shard)
2. ✅ Fast system-wide queries (use global index)
3. ✅ No shard scanning needed
4. ✅ Maintains stateless architecture

---

## Architecture

### Data Model

#### 1. Error Log Entry (Workflow Shard)
```
Key Pattern: {shard:N}:log:error:{timestamp}-{uuid}
Value: JSON
TTL: 30 days

{
  "log_id": "1696089600000-abc123",
  "timestamp": 1696089600000,
  "level": "ERROR",
  "message": "Task execution failed: Connection timeout",
  "component": "TaskExecutionWorker",
  "workflow_id": "wf_12345",
  "task_id": "task_456",
  "error_type": "ConnectionTimeout",
  "stack_trace": "...",
  "metadata": {
    "retry_count": 2,
    "handler_type": "python"
  }
}
```

#### 2. Global Error Index (Shard 0)
```
Key Pattern: {shard:0}:log:global:error
Type: Sorted Set (sorted by timestamp)
TTL: 30 days

Members: log_id → timestamp
{
  "1696089600000-abc123": 1696089600000,
  "1696089601000-def456": 1696089601000,
  ...
}
```

#### 3. Workflow Error Index (Workflow Shard)
```
Key Pattern: {shard:N}:log:workflow:{workflow_id}:errors
Type: Sorted Set (sorted by timestamp)
TTL: 30 days

Members: log_id → timestamp
```

#### 4. Error Metadata Mapping (Shard 0)
```
Key Pattern: {shard:0}:log:meta:{log_id}
Value: Hash
TTL: 30 days

{
  "shard": "5",              # Which shard has the full log
  "workflow_id": "wf_12345", # For workflow queries
  "error_type": "ConnectionTimeout",
  "level": "ERROR"
}
```

---

## Implementation

### 1. StatelessLogService

```python
# src/gleitzeit/core/stateless_log_service.py

import json
import uuid
import hashlib
from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class StatelessLogService:
    """
    Stateless log service with global index for efficient querying.

    Design:
    - Logs stored on workflow shard (locality)
    - Global index on shard 0 (queryability)
    - Metadata on shard 0 (for fetching from correct shard)
    """

    # Default TTLs by level (seconds)
    DEFAULT_TTL = {
        "DEBUG": 86400,      # 1 day
        "INFO": 604800,      # 7 days
        "WARNING": 1209600,  # 14 days
        "ERROR": 2592000,    # 30 days
        "CRITICAL": 2592000, # 30 days
    }

    @staticmethod
    def _get_shard(workflow_id: str) -> int:
        """Get shard number for workflow_id."""
        from gleitzeit.core.sharding import default_sharding
        return default_sharding.get_shard(workflow_id)

    @staticmethod
    async def log_error(
        redis,
        message: str,
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
        component: str = "system",
        error_type: Optional[str] = None,
        stack_trace: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None
    ) -> str:
        """
        Log an error to Redis with global index.

        Args:
            redis: Redis connection
            message: Error message
            workflow_id: Optional workflow ID
            task_id: Optional task ID
            component: Component that logged the error
            error_type: Type of error (e.g., "ConnectionTimeout")
            stack_trace: Stack trace if available
            metadata: Additional metadata
            ttl: Time to live (defaults to 30 days for errors)

        Returns:
            Log ID
        """
        # Generate log ID with timestamp
        timestamp = int(datetime.utcnow().timestamp() * 1000)
        log_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"

        # Determine shard
        if workflow_id:
            shard = StatelessLogService._get_shard(workflow_id)
        else:
            shard = 0  # System errors on shard 0

        # Use default TTL if not specified
        if ttl is None:
            ttl = StatelessLogService.DEFAULT_TTL["ERROR"]

        # Build error log entry
        log_entry = {
            "log_id": log_id,
            "timestamp": timestamp,
            "level": "ERROR",
            "message": message,
            "component": component,
            "workflow_id": workflow_id or "",
            "task_id": task_id or "",
            "error_type": error_type or "UnknownError",
            "stack_trace": stack_trace or "",
            "metadata": metadata or {}
        }

        # 1. Store full log entry on workflow shard
        log_key = f"{{shard:{shard}}}:log:error:{log_id}"
        await redis.set(
            log_key,
            json.dumps(log_entry),
            ex=ttl
        )

        # 2. Add to global error index (shard 0)
        global_index_key = f"{{shard:0}}:log:global:error"
        await redis.zadd(
            global_index_key,
            {log_id: timestamp}
        )
        await redis.expire(global_index_key, ttl)

        # 3. Store metadata for fetching (shard 0)
        meta_key = f"{{shard:0}}:log:meta:{log_id}"
        await redis.hset(
            meta_key,
            mapping={
                "shard": str(shard),
                "workflow_id": workflow_id or "",
                "error_type": error_type or "UnknownError",
                "level": "ERROR",
                "timestamp": str(timestamp)
            }
        )
        await redis.expire(meta_key, ttl)

        # 4. If workflow_id exists, add to workflow error index
        if workflow_id:
            workflow_error_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:errors"
            await redis.zadd(
                workflow_error_key,
                {log_id: timestamp}
            )
            await redis.expire(workflow_error_key, ttl)

        return log_id

    @staticmethod
    async def query_errors(
        redis,
        workflow_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Query error logs.

        Args:
            redis: Redis connection
            workflow_id: Optional workflow ID to filter by
            limit: Maximum number of results
            offset: Offset for pagination
            start_time: Start timestamp (milliseconds)
            end_time: End timestamp (milliseconds)

        Returns:
            List of error log entries
        """
        # Determine which index to query
        if workflow_id:
            # Query workflow-specific errors
            shard = StatelessLogService._get_shard(workflow_id)
            index_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:errors"
        else:
            # Query global error index
            index_key = f"{{shard:0}}:log:global:error"

        # Time range
        min_score = start_time if start_time else "-inf"
        max_score = end_time if end_time else "+inf"

        # Get log IDs from index (newest first)
        log_ids = await redis.zrevrangebyscore(
            index_key,
            max_score,
            min_score,
            start=offset,
            num=limit
        )

        # Fetch error logs
        errors = []
        for log_id in log_ids:
            log_id_str = log_id.decode() if isinstance(log_id, bytes) else log_id

            if workflow_id:
                # We know the shard from workflow_id
                log_key = f"{{shard:{shard}}}:log:error:{log_id_str}"
                log_data = await redis.get(log_key)
            else:
                # Fetch metadata to find which shard
                meta_key = f"{{shard:0}}:log:meta:{log_id_str}"
                meta = await redis.hgetall(meta_key)

                if not meta:
                    continue

                # Get log from correct shard
                log_shard = int(meta[b'shard'].decode())
                log_key = f"{{shard:{log_shard}}}:log:error:{log_id_str}"
                log_data = await redis.get(log_key)

            if log_data:
                errors.append(json.loads(log_data))

        return errors

    @staticmethod
    async def get_error_count(
        redis,
        workflow_id: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> int:
        """
        Get count of errors.

        Args:
            redis: Redis connection
            workflow_id: Optional workflow ID
            start_time: Start timestamp (milliseconds)
            end_time: End timestamp (milliseconds)

        Returns:
            Count of errors
        """
        if workflow_id:
            shard = StatelessLogService._get_shard(workflow_id)
            index_key = f"{{shard:{shard}}}:log:workflow:{workflow_id}:errors"
        else:
            index_key = f"{{shard:0}}:log:global:error"

        min_score = start_time if start_time else "-inf"
        max_score = end_time if end_time else "+inf"

        return await redis.zcount(index_key, min_score, max_score)
```

---

### 2. Update LoggingMixin

```python
# src/gleitzeit/core/logging_mixin.py

# Replace line 16:
# get_log_collector = lambda: None

# With:
from gleitzeit.core.stateless_log_service import StatelessLogService

# Update log_error method (around line 111):
async def log_error(
    self,
    operation: str,
    error: Exception,
    **context
) -> None:
    """
    Log an error with full context.

    Now writes to Redis via StatelessLogService.
    """
    message = f"{self._component_name}.{operation} failed: {str(error)}"

    # Extract context
    workflow_id = context.get('workflow_id')
    task_id = context.get('task_id')

    # Error details
    error_type = type(error).__name__

    # Get stack trace
    import traceback
    stack_trace = ''.join(traceback.format_exception(
        type(error), error, error.__traceback__
    ))

    # Build metadata
    error_metadata = {
        "operation": operation,
        "error_message": str(error),
        **context
    }

    # Add error code if available
    if hasattr(error, 'code'):
        error_metadata["error_code"] = (
            error.code.value if hasattr(error.code, 'value') else error.code
        )

    # Get Redis connection
    redis = context.pop('redis', None) or getattr(self, 'redis', None)

    if redis:
        try:
            # Write to Redis
            await StatelessLogService.log_error(
                redis=redis,
                message=message,
                workflow_id=workflow_id,
                task_id=task_id,
                component=self._component_name,
                error_type=error_type,
                stack_trace=stack_trace,
                metadata=error_metadata
            )
        except Exception as e:
            # Fallback to file logging
            logger.error(f"Failed to write error to Redis: {e}")
            self._fallback_log(LogLevel.ERROR, message, error_metadata)
    else:
        # No Redis, use fallback
        self._fallback_log(LogLevel.ERROR, message, error_metadata)
```

---

### 3. Update API Endpoint

```python
# src/gleitzeit/api/routes/system.py

# Replace lines 291-318 with:

@router.get("/logs/errors")
async def get_error_logs(
    limit: int = 100,
    offset: int = 0,
    level: str = "ERROR",
    workflow_id: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    redis: aioredis.Redis = Depends(get_redis)
):
    """Get error logs from Redis using StatelessLogService"""

    from gleitzeit.core.stateless_log_service import StatelessLogService

    # Query errors
    errors = await StatelessLogService.query_errors(
        redis=redis,
        workflow_id=workflow_id,
        limit=limit,
        offset=offset,
        start_time=start_time,
        end_time=end_time
    )

    # Get total count
    total = await StatelessLogService.get_error_count(
        redis=redis,
        workflow_id=workflow_id,
        start_time=start_time,
        end_time=end_time
    )

    return {
        "errors": errors,
        "total": total,
        "limit": limit,
        "offset": offset
    }
```

---

### 4. Worker Integration Example

```python
# Example: How workers use error logging

# In src/gleitzeit/workers/task_execution_worker.py

class TaskExecutionWorker(BaseWorker):

    async def process_message(self, message_id, message):
        try:
            # Execute task
            result = await self._execute_task(task_data)

        except Exception as e:
            # Log error via LoggingMixin
            await self.log_error(
                operation="task_execution",
                error=e,
                workflow_id=workflow_id,
                task_id=task_id,
                redis=self.redis,  # Pass Redis connection
                handler_type=handler_type,
                retry_count=retry_count
            )

            # Re-raise or handle
            raise
```

---

## Data Flow

### Writing Errors

```
1. Worker catches exception
   ↓
2. Calls LoggingMixin.log_error()
   ↓
3. StatelessLogService.log_error() writes:

   a) Full log → {shard:N}:log:error:{log_id}
   b) Global index → {shard:0}:log:global:error (zadd)
   c) Metadata → {shard:0}:log:meta:{log_id} (hset)
   d) Workflow index → {shard:N}:log:workflow:{wf_id}:errors (zadd)

All operations use TTL for automatic cleanup
```

### Querying Errors

#### Query by Workflow ID
```
1. Client: GET /system/logs/errors?workflow_id=wf_12345
   ↓
2. StatelessLogService.query_errors(workflow_id="wf_12345")
   ↓
3. Determine shard: shard = hash(wf_12345) % 16 = 5
   ↓
4. Query workflow index: {shard:5}:log:workflow:wf_12345:errors
   ↓
5. Get log IDs: ["1696089600000-abc", "1696089601000-def"]
   ↓
6. Fetch logs from same shard: {shard:5}:log:error:{log_id}
   ↓
7. Return errors
```

#### Query All Errors
```
1. Client: GET /system/logs/errors
   ↓
2. StatelessLogService.query_errors(workflow_id=None)
   ↓
3. Query global index: {shard:0}:log:global:error
   ↓
4. Get log IDs: ["1696089600000-abc", "1696089601000-def"]
   ↓
5. For each log_id:
   a) Fetch metadata: {shard:0}:log:meta:{log_id}
   b) Get shard from metadata: shard=5
   c) Fetch log: {shard:5}:log:error:{log_id}
   ↓
6. Return errors
```

---

## Performance Analysis

### Writes (per error)
- 4 Redis operations:
  1. SET (full log)
  2. ZADD (global index)
  3. HSET (metadata)
  4. ZADD (workflow index, if workflow_id)

**Impact**: ~1-2ms total (all on same connection)

### Reads

#### Workflow-specific Query
- 2 operations:
  1. ZREVRANGEBYSCORE (get log IDs) - O(log N + M)
  2. GET × M (fetch logs) - O(M)

**Impact**: ~1-5ms for 100 errors

#### System-wide Query
- 2 + N operations:
  1. ZREVRANGEBYSCORE (global index) - O(log N + M)
  2. HGETALL × M (get metadata) - O(M)
  3. GET × M (fetch logs) - O(M)

**Impact**: ~2-10ms for 100 errors

### Comparison

**Current (scan all shards)**:
- 16 × SCAN operations
- ~50-200ms for 100 errors

**Global Index Approach**:
- 3-4 operations total
- ~2-10ms for 100 errors

**10-20x faster** ✅

---

## Storage Requirements

### Per Error Log
- Full log entry: ~500-1000 bytes
- Global index entry: ~50 bytes (log_id + timestamp)
- Metadata entry: ~100 bytes
- Workflow index entry: ~50 bytes

**Total per error**: ~700-1200 bytes

### At Scale
- 1000 errors/day = ~1 MB/day
- 30 day retention = ~30 MB total
- Negligible storage impact ✅

---

## Testing Plan

### 1. Unit Tests
```python
# tests/test_stateless_log_service.py

async def test_log_error():
    """Test error logging to Redis"""

    log_id = await StatelessLogService.log_error(
        redis=redis,
        message="Test error",
        workflow_id="wf_test",
        error_type="TestError"
    )

    assert log_id

    # Verify full log stored
    log_key = f"{{shard:5}}:log:error:{log_id}"
    log_data = await redis.get(log_key)
    assert log_data

    # Verify global index
    global_index = await redis.zrange("{shard:0}:log:global:error", 0, -1)
    assert log_id.encode() in global_index

    # Verify metadata
    meta = await redis.hgetall(f"{{shard:0}}:log:meta:{log_id}")
    assert meta[b'shard'] == b'5'

async def test_query_errors():
    """Test querying errors"""

    # Log some errors
    await StatelessLogService.log_error(redis, "Error 1", workflow_id="wf_1")
    await StatelessLogService.log_error(redis, "Error 2", workflow_id="wf_1")
    await StatelessLogService.log_error(redis, "Error 3", workflow_id="wf_2")

    # Query workflow errors
    errors = await StatelessLogService.query_errors(
        redis,
        workflow_id="wf_1"
    )
    assert len(errors) == 2

    # Query all errors
    all_errors = await StatelessLogService.query_errors(redis)
    assert len(all_errors) == 3
```

### 2. Integration Tests
```python
# Test with real worker
async def test_worker_error_logging():
    """Test that worker errors are logged to Redis"""

    # Submit task that will fail
    response = await client.submit_workflow({
        "tasks": [{
            "id": "failing_task",
            "protocol": "python/v1",
            "params": {"code": "raise ValueError('Test error')"}
        }]
    })

    # Wait for failure
    await asyncio.sleep(2)

    # Query error logs
    errors = await client.get_error_logs(
        workflow_id=response["workflow_id"]
    )

    assert len(errors) > 0
    assert "ValueError" in errors[0]["error_type"]
```

### 3. API Tests
```python
# Test API endpoint
async def test_error_logs_api():
    """Test /system/logs/errors endpoint"""

    # Should now return actual errors
    response = await client.get("/system/logs/errors?limit=10")

    assert response.status_code == 200
    assert "errors" in response.json()
    # May be empty if no errors yet, but structure is correct
```

---

## Implementation Checklist

### Phase 1: Core Service ✅
- [ ] Create `src/gleitzeit/core/stateless_log_service.py`
- [ ] Implement `log_error()` method
- [ ] Implement `query_errors()` method
- [ ] Implement `get_error_count()` method
- [ ] Add unit tests

### Phase 2: Integration ✅
- [ ] Update `logging_mixin.py` to use StatelessLogService
- [ ] Pass Redis connection in context
- [ ] Update API endpoint `/system/logs/errors`
- [ ] Test with existing workers

### Phase 3: Validation ✅
- [ ] Run integration tests
- [ ] Submit failing workflow
- [ ] Verify errors appear in API
- [ ] Check Redis keys are created correctly
- [ ] Verify TTL cleanup works

---

## Success Criteria

1. ✅ `/system/logs/errors` returns actual error data
2. ✅ Errors from all workers are captured
3. ✅ Query by workflow_id works
4. ✅ System-wide error queries work
5. ✅ Performance < 10ms for typical queries
6. ✅ TTL-based cleanup prevents unbounded growth
7. ✅ All 37/37 client tests still pass

---

## Future Enhancements

### Phase 4: Audit Logging
- Implement similar pattern for audit logs
- Track user actions (submit, cancel, retry)
- 90-day retention

### Phase 5: Advanced Features
- Error aggregation by type
- Error rate metrics
- Alerting on error patterns
- Export to external systems (S3, Elasticsearch)

---

## Conclusion

The **Global Index** approach provides:

1. ✅ **Fast writes** - 4 operations per error (~1-2ms)
2. ✅ **Fast queries** - No shard scanning (2-10ms vs 50-200ms)
3. ✅ **Stateless** - No service state, all in Redis
4. ✅ **Scalable** - Works with Redis Cluster
5. ✅ **Simple** - Reuses existing patterns
6. ✅ **Complete** - Fixes empty error logs issue

This implementation will make error logging fully functional while respecting Gleitzeit's modular, stateless architecture.
