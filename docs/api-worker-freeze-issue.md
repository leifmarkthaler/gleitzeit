# API Worker Freeze/Deadlock Issue

**Date:** 2025-10-22
**Status:** OPEN
**Severity:** HIGH - API is unresponsive

## Problem Summary

The API worker process starts successfully but does not respond to HTTP requests. Connections are accepted but hang for ~2 minutes before being reset.

## Symptoms

1. API worker process (PID 28721) is running and listening on port 8000
2. Port 8000 shows as LISTEN in lsof
3. TCP connections are ESTABLISHED
4. HTTP requests hang indefinitely (tested for 120+ seconds)
5. After ~2 minutes, connection is reset with "Connection reset by peer"
6. No logs are written to Redis by the API worker
7. Process state shows as `SNs` (sleeping, low priority, session leader)

## Test Results

```bash
$ lsof -i :8000
COMMAND   PID USER  FD  TYPE  DEVICE  NODE NAME
python    28721 ... 11u IPv4 ...     TCP *:irdmi (LISTEN)

$ curl -v http://localhost:8000/health
* Connected to localhost (127.0.0.1) port 8000
> GET /health HTTP/1.1
> Host: localhost:8000
> User-Agent: curl/8.6.0
> Accept: */*
>
... [waits 120 seconds] ...
* Recv failure: Connection reset by peer
curl: (56) Recv failure: Connection reset by peer
```

## Worker Configuration

- **Worker Type:** api
- **Config Key:** `worker:config:api-async:360930d4`
- **PID:** 28721
- **Command:** `/opt/homebrew/Caskroom/miniconda/base/bin/python -m gleitzeit.workers.runner --config-key worker:config:api-async:360930d4 --redis-url redis://localhost:6379`
- **Started:** 2025-10-22 14:16:38
- **Logs:** Redis only (no file logs)

## Related Context

- All other workers started successfully (ui, task_execution, etc.)
- Redis is healthy and accessible
- This is **unrelated** to the redis_monitor/loki_exporter heartbeat issue that was fixed
- Old API logs from October 13th show the API was working previously

## Possible Causes

1. **Deadlock during initialization** - Worker may be waiting for something that never completes
2. **Async event loop issue** - uvicorn/FastAPI may not be starting properly
3. **Redis connection blocking** - Worker might be stuck waiting on Redis
4. **Port conflict** - Multiple instances competing (unlikely given lsof output)
5. **Configuration issue** - Handler configs or worker setup causing freeze
6. **Missing dependency** - Some required service not available

## Investigation Steps

1. ✅ Confirmed process is running and listening on port 8000
2. ✅ Confirmed connections are accepted but hang for 120s then reset
3. ✅ Checked worker config from Redis - looks normal
4. ✅ Ran API worker manually - fails with "port already in use"
5. ✅ Analyzed code flow - found likely issue

## Root Cause Analysis

The API worker freezes during the **lifespan startup** in FastAPI ([main.py:46-116](../src/gleitzeit/api/main.py#L46-L116)).

Specifically, the issue is at **line 90**:
```python
await broadcaster.start()
```

Which calls EventBroadcaster.start() ([event_broadcaster.py:32-46](../src/gleitzeit/api/services/event_broadcaster.py#L32-L46)):
```python
async def start(self):
    self.pubsub = self.redis.pubsub()
    await self.pubsub.subscribe('gleitzeit:events')  # ← HANGS HERE
    self._running = True
    self._listen_task = asyncio.create_task(self._listen_to_redis())
```

**The `await self.pubsub.subscribe()` call is blocking indefinitely**, preventing the lifespan from completing. This means:
1. ✅ Port 8000 gets bound successfully (by uvicorn)
2. ❌ Lifespan hangs on Redis pubsub subscribe
3. ❌ HTTP server never starts accepting requests
4. ❌ Connections are accepted by OS but never processed

## Why It Hangs

**ROOT CAUSE IDENTIFIED:**

The API worker initialization has a **Redis client type mismatch**:

1. **Worker Infrastructure (api_worker.py):**
   - Inherits from BaseWorker
   - Uses `GleitzeitRedisCluster` (line 109 in base.py)
   - Properly initializes Redis with connection pooling and cluster support

2. **FastAPI Lifespan (main.py line 72):**
   - Uses `aioredis.from_url()` directly
   - Bypasses GleitzeitRedisCluster initialization
   - Creates a raw, uninitialized Redis connection

When EventBroadcaster tries to create a pubsub instance from the raw `aioredis.from_url()` connection:
```python
self.pubsub = self.redis.pubsub()  # Line 37
await self.pubsub.subscribe('gleitzeit:events')  # Line 40 - HANGS HERE
```

The connection hasn't been properly initialized, causing the subscribe call to hang indefinitely waiting for a response that never comes.

**Evidence:**
- There's already 1 subscriber to 'gleitzeit:events' (the frozen worker)
- Curl connections hang for exactly 120 seconds then reset (likely a timeout)
- Port 8000 is listening but no HTTP requests are processed
- The frozen worker (PID 28721) is stuck in `SNs` state (sleeping, session leader)

## Workaround

None currently. The API is completely unresponsive.

## Solution

✅ **FIXED** - See [api-worker-fix-summary.md](./api-worker-fix-summary.md) for complete details.

**Summary of fix:**
The API worker now injects its properly-initialized `GleitzeitRedisCluster` connection (from `BaseWorker`) into the FastAPI app state before starting the server. This ensures the FastAPI app uses the same Redis infrastructure as all other workers, eliminating the client type mismatch.

**Changes made:**
1. **api_worker.py**: Inject `self.redis` into `app.state.redis` during `on_initialize()` (lines 50-54)
2. **main.py**: Check if Redis is already injected before creating a standalone connection (lines 57-107)

This makes the API worker work "just like the other workers" - using the BaseWorker infrastructure.

## Related Files

- [src/gleitzeit/workers/api_worker.py](../src/gleitzeit/workers/api_worker.py)
- [src/gleitzeit/workers/runner.py](../src/gleitzeit/workers/runner.py)
- [src/gleitzeit/core/async_process_manager.py](../src/gleitzeit/core/async_process_manager.py)

## Notes

This issue appeared after consolidating to use only `gleitzeit serve` (AsyncServiceManager). Need to determine if this is:
- A new regression
- An existing issue that was masked before
- Related to the removal of `gleitzeit start` command
