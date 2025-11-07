# Heartbeat and Monitoring Re-Audit - Stateless Architecture

**Date**: 2025-09-30
**Focus**: Stateless, Redis-backed, distributed architecture

## Critical Understanding: Gleitzeit IS Already Stateless

After re-auditing the codebase, I now understand that **Gleitzeit is fundamentally a stateless, Redis-backed, distributed system**. My original centralized design was **WRONG** and would break this architecture.

## Key Architectural Principles

### 1. Redis is the Source of Truth

**Everything is in Redis, nothing in memory**:
- Worker registrations: `{shard:0}:worker:registry:{type}:{id}` (TTL: 60s)
- Worker metrics: `{shard:0}:worker:metrics:{worker_id}`
- Service registrations: `service:registry:{name}` (TTL: 60s)
- Handler registrations: `handler:registry:{handler_id}` (TTL: 24h)
- All task state, workflow state, signals, timers - **everything in Redis**

### 2. Components Self-Manage Their Heartbeats

**Workers** (`base.py:306-325`):
```python
async def _heartbeat_loop(self):
    """Send periodic heartbeats"""
    while self._running:
        try:
            await self._register_worker()  # Refresh registration with TTL
            # Update metrics
            await asyncio.sleep(self.config.heartbeat_interval)
```

**Services** (`async_process_manager.py:795-868`):
```python
async def _service_heartbeat_loop(self):
    """Periodically refresh service registrations to prevent expiry"""
    while True:
        # Re-register each service to refresh TTL
        await self.smart_manager.register_service(name, info)
        await asyncio.sleep(30)
```

**Handlers** (`task_execution_worker.py:149-176`):
```python
async def _register_handlers(self):
    """Register handler metadata in Redis"""
    for protocol, handler in self.handlers.items():
        handler_key = f"handler:registry:{handler.handler_id}"
        await self.redis.hset(handler_key.encode(), ...)
        await self.redis.expire(handler_key.encode(), 86400)  # 24h TTL
```

### 3. Discovery is Stateless

**All discovery queries Redis directly**:
- Health endpoints scan `service:registry:*` and `{shard:*}:worker:registry:*`
- Component Orchestrator checks worker heartbeats in Redis
- No local caches or in-memory state

### 4. TTL-Based Health Detection

Components are considered **dead** when their Redis keys expire:
- Worker registration TTL: 60 seconds
- Service registration TTL: 60 seconds
- Handler registration TTL: 24 hours

If a worker crashes, its registration **automatically disappears** after 60s.

## What Actually Needs to Be Fixed

### Problem #1: Redis Failure Handling - Per-Instance (CORRECT)

**This IS per-instance and local** - each process needs to know if *it* has lost Redis:

**Current State**: No Redis failure handling
**What Happens**: Workers/services retry forever when Redis fails
**What Should Happen**: After extended Redis outage (e.g., 5 minutes), gracefully shut down

**This is NOT distributed** - it's about each instance detecting its own Redis connection failure.

### Problem #2: Service Heartbeat Loop Terminates (CRITICAL BUG)

**Location**: `async_process_manager.py:795-868`

**Bug**: Loop exits after 100 total failures, services become permanently undiscoverable

```python
if total_failures >= max_total_failures:
    logger.critical("Stopping heartbeat loop - services will no longer be discoverable!")
    break  # ← EXITS PERMANENTLY
```

**Fix**: Replace with circuit breaker pattern - never exit, just backoff longer

### Problem #3: Inconsistent Hardcoded Configuration

**Issue**: Heartbeat intervals hardcoded everywhere:
- Workers: 30s (hardcoded in `base.py:34`)
- Services: 30s (hardcoded in `async_process_manager.py:804`)
- Config file: 10s (ignored!)

**Fix**: Load from `gleitzeit.yaml` and use consistently

### Problem #4: No Enhanced Health Metrics

**Current**: Workers only send processed/failed counts
**Missing**: Memory usage, CPU usage, error rates, processing time

**Fix**: Add system metrics to worker heartbeat

## Correct Stateless Design

### What Should Be Per-Instance (Local State)

1. **Redis Connection Monitor** - Each instance monitors its own connection
2. **Heartbeat Sender** - Each component sends its own heartbeat
3. **Shutdown Decision** - Each instance decides when to shut itself down

### What Should Be in Redis (Shared State)

1. **Component Registrations** - Already correct (`service:registry:*`, `worker:registry:*`)
2. **Health Metrics** - Already correct (`worker:metrics:*`)
3. **Handler Registry** - Already correct (`handler:registry:*`)
4. **Global Cluster Health** - NEW: Aggregate view for monitoring

## Revised Implementation Plan

### Phase 1: Add Per-Instance Redis Health Monitor (✅ Correct)

**Purpose**: Each instance monitors its own Redis connection

```python
# src/gleitzeit/core/redis_health_monitor.py

class RedisHealthState(Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    SHUTDOWN = "shutdown"

class RedisHealthMonitor:
    """
    Per-instance Redis health monitoring with graceful degradation.

    Each process runs its own monitor to detect Redis failures
    and trigger graceful shutdown.
    """

    def __init__(self, redis_client, config: dict):
        self.redis = redis_client
        self.config = config
        self.state = RedisHealthState.HEALTHY
        self.consecutive_failures = 0
        self.first_failure_time = None

    async def start_monitoring(self):
        """Monitor Redis health, trigger shutdown on extended failure"""
        while True:
            try:
                await self.redis.ping()

                # Success - reset to healthy
                if self.state != RedisHealthState.HEALTHY:
                    logger.info("Redis connection recovered")
                    self.state = RedisHealthState.HEALTHY
                    self.consecutive_failures = 0
                    self.first_failure_time = None

            except Exception as e:
                await self._handle_failure(e)

            await asyncio.sleep(self.config['check_interval'])

    async def _handle_failure(self, error):
        """Handle Redis failure with state escalation"""
        self.consecutive_failures += 1

        if self.first_failure_time is None:
            self.first_failure_time = datetime.utcnow()

        time_down = (datetime.utcnow() - self.first_failure_time).total_seconds()

        # State transitions based on downtime
        if time_down >= self.config['shutdown_timeout']:
            if self.state != RedisHealthState.SHUTDOWN:
                logger.critical(f"Redis down for {time_down}s, initiating shutdown")
                self.state = RedisHealthState.SHUTDOWN
                # Trigger graceful shutdown callback
                await self._trigger_shutdown()

        elif time_down >= self.config['critical_timeout']:
            if self.state != RedisHealthState.CRITICAL:
                logger.error(f"Redis down for {time_down}s, entering CRITICAL state")
                self.state = RedisHealthState.CRITICAL

        elif self.consecutive_failures >= self.config['warning_threshold']:
            if self.state != RedisHealthState.WARNING:
                logger.warning(f"Redis failures: {self.consecutive_failures}, entering WARNING")
                self.state = RedisHealthState.WARNING
```

**Integration**: Add to `BaseWorker` and `AsyncServiceManager`

```python
# In BaseWorker.__init__
self.redis_monitor = RedisHealthMonitor(self.redis, {
    'check_interval': 10,
    'warning_threshold': 3,
    'critical_timeout': 120,
    'shutdown_timeout': 300
})

# In BaseWorker.run()
self._tasks['redis_monitor'] = asyncio.create_task(
    self.redis_monitor.start_monitoring()
)
```

### Phase 2: Fix Service Heartbeat Loop (✅ Critical Bug Fix)

**Replace permanent termination with circuit breaker**:

```python
# In async_process_manager.py

from ..core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

async def _service_heartbeat_loop(self):
    """Periodically refresh service registrations"""

    # Create circuit breaker instead of hard limits
    circuit_breaker = CircuitBreaker(
        "service_heartbeat",
        CircuitBreakerConfig(
            failure_threshold=10,
            success_threshold=2,
            reset_timeout=300  # 5 minutes
        )
    )

    while True:  # ← NEVER EXIT
        try:
            # Use circuit breaker to control execution
            await circuit_breaker.call(self._refresh_service_registrations)
            await asyncio.sleep(30)

        except CircuitOpenError:
            # Circuit is open, back off longer
            logger.warning("Service heartbeat circuit is OPEN, backing off")
            await asyncio.sleep(300)  # Wait 5 minutes before retry

        except Exception as e:
            logger.error(f"Service heartbeat error: {e}")
            await asyncio.sleep(30)

async def _refresh_service_registrations(self):
    """Refresh all service registrations"""
    for name, info in self.process_manager.processes.items():
        if name in ["api", "ui"] and (info.process or info.pid):
            service_data = await self.smart_manager.redis.hgetall(...)
            await self.smart_manager.register_service(name, decoded_data)
```

### Phase 3: Centralize Configuration (✅ Correct)

**Add to `gleitzeit.yaml`**:

```yaml
# Redis health monitoring (per-instance)
redis:
  health:
    enabled: true
    check_interval: 10
    warning_threshold: 3
    critical_timeout: 120
    shutdown_timeout: 300
  shutdown:
    mode: graceful
    grace_period: 30
    force_after: 60

# Monitoring configuration
monitoring:
  worker:
    heartbeat_interval: 30
    heartbeat_timeout: 60
    max_health_failures: 3
    include_system_stats: true

  service:
    heartbeat_interval: 30
    registration_ttl: 90
    circuit_breaker:
      failure_threshold: 10
      reset_timeout: 300

  component:
    health_check_interval: 10
```

**Add to `ConfigurationManager`**:

```python
def get_redis_health_config(self) -> dict:
    """Get Redis health monitoring config"""
    return self.config.get('redis', {}).get('health', {
        'enabled': True,
        'check_interval': 10,
        'warning_threshold': 3,
        'critical_timeout': 120,
        'shutdown_timeout': 300
    })

def get_worker_monitoring_config(self) -> dict:
    """Get worker monitoring config"""
    return self.config.get('monitoring', {}).get('worker', {
        'heartbeat_interval': 30,
        'heartbeat_timeout': 60,
        'include_system_stats': True
    })

def get_service_monitoring_config(self) -> dict:
    """Get service monitoring config"""
    return self.config.get('monitoring', {}).get('service', {
        'heartbeat_interval': 30,
        'registration_ttl': 90
    })
```

**Update `WorkerConfig` to use config**:

```python
@dataclass
class WorkerConfig:
    # ... existing fields ...

    @classmethod
    def from_dict(cls, config_dict: dict, config_manager=None):
        """Create WorkerConfig from dict with config defaults"""

        # Load monitoring config if available
        if config_manager:
            worker_config = config_manager.get_worker_monitoring_config()
            config_dict.setdefault('heartbeat_interval', worker_config.get('heartbeat_interval', 30))

        return cls(**config_dict)
```

### Phase 4: Enhanced Worker Metrics (✅ Correct)

**Add system metrics to worker heartbeat**:

```python
# In BaseWorker._heartbeat_loop()

import psutil

async def _heartbeat_loop(self):
    """Send periodic heartbeats with enhanced metrics"""
    while self._running:
        try:
            await self._register_worker()

            # Collect system metrics
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            cpu_percent = process.cpu_percent(interval=0.1)

            # Calculate rates
            uptime = (datetime.utcnow() - self.started_at).total_seconds()
            processing_rate = self.messages_processed / uptime if uptime > 0 else 0
            error_rate = self.messages_failed / self.messages_processed if self.messages_processed > 0 else 0

            # Update metrics with enhanced data
            metrics_key = f"{{shard:0}}:worker:metrics:{self.config.worker_id}"
            await self.redis.hset(metrics_key.encode(), mapping={
                b"processed": str(self.messages_processed).encode(),
                b"failed": str(self.messages_failed).encode(),
                b"uptime": str(uptime).encode(),
                b"last_heartbeat": datetime.utcnow().isoformat().encode(),
                # NEW METRICS:
                b"memory_mb": str(memory_mb).encode(),
                b"cpu_percent": str(cpu_percent).encode(),
                b"processing_rate": str(processing_rate).encode(),
                b"error_rate": str(error_rate).encode()
            })

            await asyncio.sleep(self.config.heartbeat_interval)
```

### Phase 5: Optional - Global Cluster Health Aggregation (✅ Stateless)

**Purpose**: Aggregate cluster health in Redis for monitoring dashboards

**This IS stateless** - one instance aggregates, all instances can read:

```python
# NEW: src/gleitzeit/core/cluster_health_aggregator.py

class ClusterHealthAggregator:
    """
    Stateless cluster health aggregator using Redis for coordination.

    Uses leader election to ensure only one instance aggregates.
    All instances can read the aggregated health from Redis.
    """

    def __init__(self, redis_client, instance_id: str):
        self.redis = redis_client
        self.instance_id = instance_id
        self.is_leader = False

    async def start_aggregation(self):
        """Start aggregation loop (leader only)"""
        while True:
            try:
                # Attempt leader election
                await self._attempt_leader_election()

                # If leader, aggregate and store in Redis
                if self.is_leader:
                    await self._aggregate_cluster_health()

                await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"Cluster health aggregation error: {e}")
                await asyncio.sleep(30)

    async def _attempt_leader_election(self):
        """Simple leader election using Redis lock"""
        lock_key = "cluster:health:leader_lock"

        # Try to acquire lock
        result = await self.redis.set(
            lock_key.encode(),
            self.instance_id.encode(),
            ex=60,  # Lock expires after 60s
            nx=True  # Only set if not exists
        )

        if result:
            self.is_leader = True
        else:
            # Check if we still hold the lock
            current_leader = await self.redis.get(lock_key.encode())
            self.is_leader = (current_leader and current_leader.decode() == self.instance_id)

    async def _aggregate_cluster_health(self):
        """Aggregate health from all components and store in Redis"""

        # Scan for all workers
        workers = {}
        async for key in self.redis.scan_iter(match=b"{shard:0}:worker:registry:*"):
            worker_data = await self.redis.hgetall(key)
            if worker_data:
                worker_id = key.decode().split(":")[-1]
                workers[worker_id] = {k.decode(): v.decode() for k, v in worker_data.items()}

        # Scan for all services
        services = {}
        async for key in self.redis.scan_iter(match=b"service:registry:*"):
            service_data = await self.redis.hgetall(key)
            if service_data:
                service_name = key.decode().split(":")[-1]
                services[service_name] = {k.decode(): v.decode() for k, v in service_data.items()}

        # Calculate overall health
        total_components = len(workers) + len(services)
        healthy_components = total_components  # All registered components are healthy (TTL-based)

        status = "healthy" if total_components > 0 else "no_components"

        # Store aggregated health in Redis
        cluster_health = {
            "status": status,
            "total_workers": len(workers),
            "total_services": len(services),
            "total_components": total_components,
            "healthy_components": healthy_components,
            "updated_at": datetime.utcnow().isoformat(),
            "updated_by": self.instance_id
        }

        await self.redis.hset(
            b"cluster:health:global",
            mapping={k.encode(): str(v).encode() for k, v in cluster_health.items()}
        )

        # Set TTL so stale health disappears
        await self.redis.expire(b"cluster:health:global", 120)
```

**Usage**: Optional, run in one of the service managers or as standalone monitor

## What NOT to Do

### ❌ DON'T: Create Centralized HeartbeatCoordinator with Local State

```python
# WRONG - this breaks stateless architecture
class HeartbeatCoordinator:
    def __init__(self):
        self.registered_workers = {}  # ← BAD: Local state
        self.registered_services = {}  # ← BAD: Local state
```

### ❌ DON'T: Create Managers that Cache Redis Data

```python
# WRONG - creates stale local cache
class WorkerHeartbeatManager:
    def __init__(self):
        self.workers = {}  # ← BAD: Cached data
```

### ❌ DON'T: Centralize Heartbeat Sending

```python
# WRONG - workers should send their own heartbeats
coordinator.send_heartbeat_for(worker_id)  # ← BAD: Centralized control
```

## What TO Do

### ✅ DO: Keep Components Self-Managing

```python
# CORRECT - each worker manages itself
class BaseWorker:
    async def _heartbeat_loop(self):
        """Each worker sends its own heartbeat to Redis"""
        while self._running:
            await self._register_worker()  # Directly to Redis
            await asyncio.sleep(self.config.heartbeat_interval)
```

### ✅ DO: Query Redis Directly for Discovery

```python
# CORRECT - stateless discovery
async def get_all_workers():
    workers = []
    async for key in redis.scan_iter(match=b"{shard:0}:worker:registry:*"):
        worker_data = await redis.hgetall(key)
        workers.append(worker_data)
    return workers
```

### ✅ DO: Use TTL for Health Detection

```python
# CORRECT - Redis automatically removes dead components
await redis.hset(key, mapping=data)
await redis.expire(key, 60)  # Component must refresh within 60s
```

## Summary of Changes

| Component | Change | Type | Priority |
|-----------|--------|------|----------|
| RedisHealthMonitor | Add per-instance Redis failure detection | New, Per-Instance | P0 |
| Service Heartbeat Loop | Replace termination with circuit breaker | Bug Fix | P0 |
| Configuration | Centralize all intervals in gleitzeit.yaml | Enhancement | P1 |
| Worker Metrics | Add system metrics to heartbeat | Enhancement | P1 |
| Cluster Health | Add optional aggregation in Redis | New, Stateless | P2 |

## Testing Strategy

### Unit Tests

1. **RedisHealthMonitor state transitions**
2. **Circuit breaker in service heartbeat loop**
3. **Configuration loading**

### Integration Tests

1. **Redis failure scenarios** - simulate Redis down for 5 minutes
2. **Service heartbeat recovery** - verify loop never exits
3. **Worker metrics collection** - verify system stats collected
4. **Cluster health aggregation** - verify leader election works

## Conclusion

**Key Insight**: Gleitzeit is already correctly designed as a stateless, Redis-backed system. The fixes needed are:

1. **Per-instance Redis failure handling** - Each process monitors its own connection
2. **Fix service heartbeat bug** - Never exit the loop
3. **Centralize configuration** - Load intervals from YAML
4. **Enhance metrics** - Add system stats to heartbeats

The original "centralized" design was fundamentally wrong because it tried to add local state to a stateless system. The correct approach is to **enhance the existing stateless patterns**, not replace them.