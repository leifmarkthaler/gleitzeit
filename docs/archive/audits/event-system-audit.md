# Gleitzeit Event System Audit

## Overview

This document audits the Gleitzeit event system, focusing on Redis pub/sub usage, the EventBroadcaster component, and the current API worker freeze issue.

## Event System Architecture

### Pub/Sub Channel: `gleitzeit:events`

**Single centralized channel** for all workflow/task events and logs that need to be broadcast to WebSocket clients.

### Publishers (Who Publishes Events)

#### 1. EventStore ([src/gleitzeit/core/event_store.py:138-154](../src/gleitzeit/core/event_store.py#L138-L154))

Publishes workflow execution events:

```python
class EventStore:
    def __init__(self, redis_client, config: Optional[Dict[str, Any]] = None):
        self.redis = redis_client  # Accepts any Redis client

    async def store_event(self, ...):
        # Store event in Redis stream
        await self.redis.xadd(...)

        # Publish to pub/sub for WebSocket broadcasting
        await self.redis.publish(
            'gleitzeit:events',
            json.dumps({
                'type': 'workflow_event',
                'workflow_id': workflow_id,
                'task_id': task_id,
                'event_type': event_type.value,
                'timestamp': event.timestamp,
                'level': level.value,
                'data': data or {}
            })
        )
```

**Redis Client Type**: Accepts any Redis client passed to constructor. In workers, this is `GleitzeitRedisCluster`.

#### 2. StatelessLogService ([src/gleitzeit/core/stateless_log_service.py:163-180](../src/gleitzeit/core/stateless_log_service.py#L163-L180))

Publishes log events (errors, task completions, validation failures):

```python
# Example from log_error method
await redis.publish(
    'gleitzeit:events',
    json.dumps({
        'type': 'log_event',
        'level': 'ERROR',
        'workflow_id': workflow_id,
        'task_id': task_id,
        'message': message,
        'error': error_details,
        'timestamp': datetime.utcnow().isoformat()
    })
)
```

**Redis Client Type**: Receives `GleitzeitRedisCluster` from workers via static method calls.

### Subscribers (Who Listens to Events)

#### 1. EventBroadcaster ([src/gleitzeit/api/services/event_broadcaster.py:32-46](../src/gleitzeit/api/services/event_broadcaster.py#L32-L46))

**Purpose**: Subscribe to `gleitzeit:events` and broadcast to connected WebSocket clients.

```python
class EventBroadcaster:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.pubsub = None
        self.active_connections: Set[WebSocket] = set()

    async def start(self):
        """Subscribe to Redis pub/sub channel"""
        # Create pubsub instance
        self.pubsub = self.redis.pubsub()  # ← CRITICAL LINE

        # Subscribe to gleitzeit events channel
        await self.pubsub.subscribe('gleitzeit:events')  # ← HANGS HERE

        # Start listening task
        self._running = True
        self._listen_task = asyncio.create_task(self._listen_to_redis())
```

**Initialized in**: [src/gleitzeit/api/main.py:84-90](../src/gleitzeit/api/main.py#L84-L90) during FastAPI lifespan startup:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... other initialization ...

    # Initialize EventBroadcaster for WebSocket support
    from .services.event_broadcaster import EventBroadcaster, set_broadcaster
    broadcaster = EventBroadcaster(app.state.redis)  # ← Uses injected Redis
    await broadcaster.start()  # ← HANGS HERE during API startup
    set_broadcaster(broadcaster)
    app.state.broadcaster = broadcaster
```

**Redis Client Type**: Receives `app.state.redis` which is set to `_worker_redis` (the worker's `GleitzeitRedisCluster` instance).

#### 2. ShutdownCoordinator ([src/gleitzeit/core/shutdown_coordinator.py:61-65](../src/gleitzeit/core/shutdown_coordinator.py#L61-L65))

Subscribes to `gleitzeit:shutdown` channel (different channel, not `gleitzeit:events`):

```python
pubsub = self.redis.pubsub()
await pubsub.subscribe(self.SHUTDOWN_CHANNEL)  # "gleitzeit:shutdown"
```

**Redis Client Type**: Uses `GleitzeitRedisCluster` from workers.

## GleitzeitRedisCluster and Pub/Sub Support

### GleitzeitRedisCluster Implementation ([src/gleitzeit/core/redis_cluster.py](../src/gleitzeit/core/redis_cluster.py))

```python
class GleitzeitRedisCluster:
    def __init__(self, config: RedisConfig = None, redis_url: str = None):
        # ... initialization ...
        self.client: Optional[RedisCluster] = None  # or regular Redis client

    async def initialize(self):
        # Single-node mode (development/testing)
        if len(self.config.cluster_nodes) == 1:
            node = self.config.cluster_nodes[0]
            self.client = await aioredis.from_url(
                f"redis://{node['host']}:{node['port']}",
                decode_responses=self.config.decode_responses,
                socket_keepalive=self.config.socket_keepalive,
                socket_connect_timeout=self.config.socket_connect_timeout,
                max_connections=self.config.max_connections_per_node,
            )
            # ✅ Regular aioredis client supports .pubsub() and .publish()

        # Multi-node mode (production cluster)
        else:
            self.client = RedisCluster(**cluster_args)
            # ✅ RedisCluster also supports .pubsub() and .publish()

    # Proxy all Redis commands to the client
    def __getattr__(self, name):
        """Proxy all other attributes to the underlying cluster client"""
        if not self._initialized:
            raise RuntimeError("Redis client not initialized. Call initialize() first")
        return getattr(self.client, name)  # ← Proxies .pubsub() and .publish()
```

**Key Insight**: `GleitzeitRedisCluster` uses `__getattr__` to proxy **all** method calls to the underlying client (`self.client`), which is either:
1. Regular `aioredis` client (single-node) - **supports pub/sub** ✅
2. `RedisCluster` client (multi-node) - **supports pub/sub** ✅

Therefore, **`GleitzeitRedisCluster` DOES support both `.publish()` and `.pubsub()` methods** through proxying.

## Current Issue: API Worker Freeze

### Symptoms

1. API worker process starts (PID 72335)
2. Port 8000 is listening
3. But API doesn't respond to requests (curl hangs)
4. No logs from uvicorn startup
5. Process appears stuck during initialization

### Root Cause Analysis

The API worker is hanging at line 87 in [main.py](../src/gleitzeit/api/main.py#L87):

```python
await broadcaster.start()  # ← HANGS HERE
```

Which calls EventBroadcaster.start() at line 40:

```python
await self.pubsub.subscribe('gleitzeit:events')  # ← HANGS HERE
```

### Why Is It Hanging?

**Hypothesis 1: GleitzeitRedisCluster not initialized**

The `GleitzeitRedisCluster._initialized` flag might be False, causing `__getattr__` to raise an exception that's being silently swallowed.

**Evidence**:
- BaseWorker calls `await self.redis.initialize()` in BaseWorker.__init__() ([base.py:109](../src/gleitzeit/workers/base.py#L109))
- APIWorker injects `self.redis` into the FastAPI app
- But is the worker's Redis connection **actually initialized** when it's injected?

**Hypothesis 2: Initialization timing issue**

Looking at api_worker.py:

```python
class APIWorker(BaseWorker):
    async def on_initialize(self):
        # Import and inject dependencies
        from ..api.main import app, set_worker_dependencies
        set_worker_dependencies(self.redis, config, self.config.redis_url)

        # Create Uvicorn config
        config = uvicorn.Config(app, ...)
        self.server = uvicorn.Server(config)
```

And BaseWorker initialization:

```python
class BaseWorker:
    def __init__(self, config: WorkerConfig):
        # ... setup ...
        self.redis = GleitzeitRedisCluster(redis_url=self.config.redis_url)
        asyncio.run(self.redis.initialize())  # ← Synchronous initialization in __init__
```

**Issue**: The Redis client IS initialized in BaseWorker.__init__, so that's not the problem.

**Hypothesis 3: Pubsub subscribe blocking/hanging**

The `await self.pubsub.subscribe('gleitzeit:events')` call might be hanging because:
1. The underlying Redis connection pool is exhausted
2. The pubsub connection is trying to connect but timing out
3. There's a deadlock in the async event loop

**Evidence needed**: Check if there are any error logs or if the subscribe call is genuinely hanging vs. raising an exception.

## Testing Needed

### Test 1: Check if GleitzeitRedisCluster is initialized

Add logging before pubsub creation:

```python
async def start(self):
    logger.info(f"EventBroadcaster starting with redis={type(self.redis)}, initialized={getattr(self.redis, '_initialized', 'N/A')}")
    self.pubsub = self.redis.pubsub()
    logger.info(f"Created pubsub instance: {type(self.pubsub)}")
    await self.pubsub.subscribe('gleitzeit:events')
    logger.info("Successfully subscribed to gleitzeit:events")
```

### Test 2: Verify .pubsub() method is accessible

Test if the proxy is working:

```python
# In on_initialize, before uvicorn starts
logger.info(f"Testing Redis pubsub access...")
test_pubsub = self.redis.pubsub()
logger.info(f"✅ Redis pubsub accessible: {type(test_pubsub)}")
await test_pubsub.close()
```

### Test 3: Check background logs for errors

Check Redis streams for any error logs from the API worker during startup.

## Event Flow Summary

```
Workers (EventStore, StatelessLogService)
    ↓
    publish() to "gleitzeit:events" channel
    ↓ (using GleitzeitRedisCluster which proxies to aioredis client)
    ↓
Redis Pub/Sub
    ↓
    ↓ (subscribe via pubsub())
    ↓
EventBroadcaster (in API worker)
    ↓
    broadcast to WebSocket clients
    ↓
Frontend WebSocket connections
```

## Key Findings

1. **Pub/Sub is supported**: `GleitzeitRedisCluster` DOES support `.publish()` and `.pubsub()` via `__getattr__` proxying
2. **Consistent Redis client**: All components use `GleitzeitRedisCluster` (or should use it)
3. **Single channel design**: All events go through `gleitzeit:events` channel
4. **Hang location**: EventBroadcaster hangs at `await self.pubsub.subscribe()` during API lifespan startup
5. **Initialization verified**: BaseWorker initializes Redis in `__init__` synchronously

## Root Cause: Connection Reuse Issue

**Critical Discovery**: The API worker is the ONLY worker experiencing this hang. Other workers use GleitzeitRedisCluster successfully, including for `.publish()` operations.

**The Difference**: EventBroadcaster tries to create a pubsub instance from the **worker's existing GleitzeitRedisCluster connection** during FastAPI lifespan startup:

```python
# main.py:lifespan
broadcaster = EventBroadcaster(app.state.redis)  # ← Reusing worker's connection
await broadcaster.start()  # ← Hangs here
```

**Why This Fails**:
1. The worker's Redis connection (`self.redis`) is already initialized and potentially in-use
2. Creating a pubsub instance from an active connection during lifespan startup creates a deadlock
3. The lifespan context is blocking waiting for pubsub.subscribe() to complete
4. But the connection might be waiting on the same event loop

**The Pattern That Works**: ClientPool creates its **own dedicated Redis connection** using redis_url:

```python
class ClientPool:
    def __init__(self, redis_url: str, ...):
        self.redis_url = redis_url  # ← Stores URL, creates own connections later
```

## Solution

EventBroadcaster should follow the same pattern as ClientPool:

1. Accept `redis_url` instead of a Redis client instance
2. Create its **own dedicated Redis connection** for pubsub operations
3. This avoids connection reuse issues and event loop deadlocks

### Implementation

```python
class EventBroadcaster:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.redis = None  # Will be created in start()
        self.pubsub = None
        # ... rest of init ...

    async def start(self):
        """Subscribe to Redis pub/sub channel"""
        # Create dedicated Redis connection for pubsub
        import redis.asyncio as aioredis
        self.redis = await aioredis.from_url(self.redis_url)

        # Create pubsub instance
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe('gleitzeit:events')
        # ... rest of start ...
```

This ensures EventBroadcaster has its own connection that won't conflict with the worker's connection.
