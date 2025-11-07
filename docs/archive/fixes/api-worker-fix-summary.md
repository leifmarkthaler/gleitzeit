# API Worker Freeze Issue - Fix Summary

## Problem
The API worker was freezing during startup and never becoming responsive. Connections to the API would hang for ~120 seconds before resetting with "Connection reset by peer".

## Root Cause
**Redis Client Type Mismatch:**

The API worker infrastructure had a critical initialization mismatch:

1. **Worker Infrastructure (api_worker.py):**
   - Inherits from `BaseWorker`
   - Uses `GleitzeitRedisCluster` (properly initialized with connection pooling)
   - Redis connection available at `self.redis`

2. **FastAPI Lifespan (main.py):**
   - Was creating its own Redis connection using `aioredis.from_url()`
   - This bypassed the proper `GleitzeitRedisCluster` initialization
   - Created a raw, uninitialized connection

When `EventBroadcaster.start()` tried to subscribe to Redis pubsub using the improperly initialized connection:
```python
self.pubsub = self.redis.pubsub()
await self.pubsub.subscribe('gleitzeit:events')  # ← HUNG HERE
```

The subscribe call would hang indefinitely because the connection wasn't properly initialized.

## Solution
**Made the API worker inject its properly-initialized Redis connection into the FastAPI app:**

### Changes Made

#### 1. api_worker.py (lines 50-54)
```python
# Inject worker's Redis connection into app state
# This ensures FastAPI uses the same properly-initialized GleitzeitRedisCluster
# instead of creating its own connection in the lifespan
app.state.redis = self.redis
self.logger.info("Injected worker Redis connection into FastAPI app state")
```

#### 2. main.py (lines 57-107)
Modified the lifespan function to check if Redis is already injected:
```python
# Initialize Redis connection from config
# NOTE: When running as a worker, the Redis connection is already injected by APIWorker
# Only create a connection if running standalone (e.g., for development/testing)
if not hasattr(app.state, 'redis') or app.state.redis is None:
    logger.info("No Redis connection injected - creating standalone connection")
    # ... create standalone connection ...
else:
    logger.info("Using Redis connection from worker (GleitzeitRedisCluster)")
    # ... still initialize client pool ...
```

## Why This Works

The fix ensures consistency across all workers:

- **All workers** (task_execution, timer, signal, etc.) use `GleitzeitRedisCluster` via `BaseWorker`
- **API worker** now uses the same Redis connection infrastructure
- **No special case** - the API worker works "just like the other workers"

This eliminates the Redis client type mismatch and ensures proper initialization.

## Testing Results

### Before Fix
```bash
$ curl http://localhost:8000/health
# Hung for 120 seconds, then:
curl: (56) Recv failure: Connection reset by peer
```

### After Fix
```bash
$ curl -L http://localhost:8000/health
{"status":"healthy","components":{"api":"healthy","redis":"healthy"}}

$ curl http://localhost:8000/docs
<!DOCTYPE html>
<html>
<head>
<link type="text/css" rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.9.0/swagger-ui.css">
...
```

## Impact

- ✅ API worker starts successfully without hanging
- ✅ All HTTP endpoints respond immediately (no freezing)
- ✅ WebSocket event broadcasting works correctly
- ✅ Consistent Redis connection management across all workers
- ✅ Maintains backward compatibility for standalone API mode (development/testing)

## Related Issues

This fix also resolves:
- EventBroadcaster pubsub subscription hangs
- Port 8000 accepting connections but not responding
- API worker showing as "healthy" in registry but not functioning

## Files Modified

- [src/gleitzeit/workers/api_worker.py](../src/gleitzeit/workers/api_worker.py#L50-L54)
- [src/gleitzeit/api/main.py](../src/gleitzeit/api/main.py#L57-L107)

## Lessons Learned

**Always use the infrastructure that already exists in BaseWorker:**
- The worker base class provides properly-initialized Redis connections
- Don't create separate connections in worker-specific code
- Injection pattern allows for both worker mode and standalone mode
