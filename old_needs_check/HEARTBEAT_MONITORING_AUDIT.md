# Heartbeat and System Monitoring Audit Report

**Date**: 2025-09-30
**Version**: 0.0.7
**Auditor**: Claude Code

## Executive Summary

The Gleitzeit system implements comprehensive heartbeat and monitoring infrastructure for workers and services. However, a **critical gap exists**: the Redis failure handling system (HeartbeatMonitor) is fully designed but not implemented. This creates a high-risk scenario where Redis outages cause indefinite degraded operation without graceful shutdown.

**Key Findings**:
- ✅ Worker heartbeat system: **IMPLEMENTED**
- ✅ Service heartbeat system: **IMPLEMENTED**
- ✅ Health check endpoints: **IMPLEMENTED**
- ✅ Component orchestrator monitoring: **IMPLEMENTED**
- ❌ Redis failure handling (HeartbeatMonitor): **NOT IMPLEMENTED**
- ⚠️ Heartbeat configuration: **INCONSISTENT**
- ⚠️ Service heartbeat loop: **TERMINATES PERMANENTLY**

---

## Detailed Findings

### 1. Worker Heartbeat System ✅ **IMPLEMENTED**

**Location**: `src/gleitzeit/workers/base.py:306-325`

**Implementation Details**:
```python
async def _heartbeat_loop(self):
    """Send periodic heartbeats"""
    while self._running:
        try:
            await self._register_worker()  # Refresh registration

            # Update metrics (also on shard 0)
            metrics_key = f"{{shard:0}}:worker:metrics:{self.config.worker_id}"
            await self.redis.hset(metrics_key.encode(), mapping={
                b"processed": str(self.messages_processed).encode(),
                b"failed": str(self.messages_failed).encode(),
                b"uptime": str((datetime.utcnow() - self.started_at).total_seconds()).encode(),
                b"last_heartbeat": datetime.utcnow().isoformat().encode()
            })

            await asyncio.sleep(self.config.heartbeat_interval)
```

**Features**:
- Periodic heartbeat loop running every 30 seconds (configurable via `WorkerConfig.heartbeat_interval`)
- Re-registers worker in Redis with fresh metadata
- Updates worker metrics: processed count, failed count, uptime, last_heartbeat timestamp
- All metrics stored in shard 0 for consistency
- Runs as background task throughout worker lifecycle
- Handles errors gracefully with 5-second retry backoff

**Configuration**:
- Default interval: 30 seconds (hardcoded in `WorkerConfig` dataclass at `base.py:34`)
- Can be overridden per worker instance

**Redis Keys Used**:
- `{shard:0}:worker:registry:{worker_type}:{worker_id}` - Worker registration (TTL: 60s)
- `{shard:0}:worker:metrics:{worker_id}` - Worker metrics

**Assessment**: ✅ Well-implemented, robust error handling, proper async patterns

---

### 2. Service Heartbeat System ✅ **IMPLEMENTED**

**Location**: `src/gleitzeit/core/async_process_manager.py:795-868`

**Implementation Details**:
```python
async def _service_heartbeat_loop(self):
    """Periodically refresh service registrations to prevent expiry"""
    consecutive_failures = 0
    max_consecutive_failures = 10
    total_failures = 0
    max_total_failures = 100

    while True:
        try:
            await asyncio.sleep(30)  # Heartbeat every 30 seconds

            if self.smart_manager:
                for name, info in self.process_manager.processes.items():
                    if info.process is not None or info.pid:
                        if name == "api" or name == "ui":
                            service_data = await self.smart_manager.redis.hgetall(...)
                            await self.smart_manager.register_service(name, decoded_data)

            consecutive_failures = 0  # Reset on success

        except Exception as e:
            consecutive_failures += 1
            total_failures += 1
            # ... logging and backoff logic ...

            if total_failures >= max_total_failures:
                logger.critical("Stopping heartbeat loop - services will no longer be discoverable!")
                break
```

**Features**:
- Refreshes service registrations (API, UI) every 30 seconds
- Re-registers services with updated TTL to prevent expiry
- Tracks consecutive failures (max 10) and total failures (max 100)
- Implements exponential backoff on errors (5s retry, 30s after many failures)
- Critical logging after threshold breaches
- **Terminates loop after max failures** to prevent infinite error loops

**Configuration**:
- Interval: 30 seconds (hardcoded at line 804)
- Max consecutive failures: 10 (hardcoded)
- Max total failures: 100 (hardcoded)

**Redis Keys Used**:
- `service:registry:{service_name}` - Service registration (TTL managed by SmartProcessManager)

**Assessment**: ✅ Implemented, but **⚠️ CRITICAL ISSUE**: Loop terminates permanently after 100 failures, leaving services undiscoverable with no recovery mechanism.

---

### 3. Health Check Endpoints ✅ **IMPLEMENTED**

**Location**: `src/gleitzeit/api/routes/health.py`

**Endpoints Implemented**:

#### `/health/` - Basic Health Check
```python
@router.get("/")
async def health_check(redis: aioredis.Redis = Depends(get_redis)):
    try:
        await redis.ping()
        redis_status = "healthy"
    except:
        redis_status = "unhealthy"

    return {
        "status": "healthy" if redis_status == "healthy" else "degraded",
        "components": {"api": "healthy", "redis": redis_status}
    }
```

#### `/health/ready` - Kubernetes Readiness Probe
```python
@router.get("/ready")
async def readiness_check(redis: aioredis.Redis = Depends(get_redis)):
    try:
        await redis.ping()
        return {"ready": True}
    except:
        return {"ready": False}, 503
```

#### `/health/live` - Kubernetes Liveness Probe
```python
@router.get("/live")
async def liveness_check():
    return {"alive": True}
```

#### `/health/detailed` - Detailed System Information
- Redis connection status and info
- Worker count (scans `{shard:*}:worker:registry:*`)
- Active workflow count (scans `{shard:*}:workflow:state:*`)
- Redis version, uptime, connected clients

#### `/health/cluster` - Stateless Cluster Health Discovery
**Location**: `health.py:100-218`

**Features**:
- Discovers all registered services via `service:registry:*` pattern
- Decodes service information (host, port, mode, started_at)
- Determines health based on registration age (<5 minutes = healthy)
- Counts workers by type
- Lists API and UI instances across deployment modes
- Returns overall cluster status: `healthy`, `degraded`, `unhealthy`, `no_services`

**Response Schema**:
```json
{
  "status": "healthy|degraded|unhealthy|no_services",
  "redis_connected": true,
  "cluster_info": {
    "total_services": 10,
    "healthy_services": 9,
    "api_instances": 2,
    "ui_instances": 2,
    "worker_types": {"task_execution": 3, "dependency": 2}
  },
  "services": {
    "api": [...],
    "ui": [...],
    "workers": {...}
  },
  "deployment_modes": ["native", "docker"],
  "timestamp": "2025-09-30T14:30:00"
}
```

**Assessment**: ✅ Comprehensive health endpoints covering basic, detailed, and cluster-wide health checks. Kubernetes-ready.

---

### 4. Component Orchestrator Monitoring ✅ **IMPLEMENTED**

**Location**: `src/gleitzeit/orchestrator/component_orchestrator.py:428-458`

**Implementation Details**:
```python
async def health_monitor(self):
    """Monitor health of all components"""
    while self._running:
        try:
            # Check worker health
            for worker_id, worker in self.managed_workers.items():
                if worker.state == WorkerState.RUNNING:
                    is_healthy = await self.check_worker_health(worker_id)

                    if not is_healthy:
                        worker.health_check_failures += 1

                        if worker.health_check_failures > 3:
                            logger.warning(f"Worker {worker_id} unhealthy, restarting")
                            await self.restart_worker(worker_id)
                    else:
                        worker.health_check_failures = 0

            # Check Redis health
            try:
                await self.redis.ping()
                self.health_status['redis'] = True
            except:
                self.health_status['redis'] = False
                logger.error("Redis connection unhealthy")

            await asyncio.sleep(10)  # Check every 10 seconds
```

**Worker Health Check Logic** (`check_worker_health`, lines 460-490):
1. Verify process exists and is running
2. Check process returncode is None
3. Retrieve worker heartbeat from Redis: `{shard:0}:worker:metrics:{worker_id}`
4. Parse `last_heartbeat` timestamp
5. Calculate age: `datetime.utcnow() - last_heartbeat`
6. Return False if age > 60 seconds

**Features**:
- Health monitoring loop checking every 10 seconds
- Checks worker process state and Redis heartbeats
- Detects stale heartbeats (>60 seconds old)
- Tracks consecutive health check failures per worker
- Auto-restarts unhealthy workers after 3 consecutive failures
- Monitors Redis connectivity via ping

**Configuration**:
- Check interval: 10 seconds (hardcoded)
- Heartbeat staleness threshold: 60 seconds (hardcoded)
- Max failures before restart: 3 (hardcoded)

**Assessment**: ✅ Functional monitoring with auto-restart capability. ⚠️ Limited health checks (only process + heartbeat).

---

### 5. Auto-Scaler with Queue Metrics ✅ **IMPLEMENTED**

**Location**: `src/gleitzeit/orchestrator/component_orchestrator.py:492-556`

**Implementation Details**:
```python
async def auto_scaler(self):
    """Auto-scale workers based on queue depth"""
    while self._running:
        try:
            for worker_type, spec in self.worker_specs.items():
                if not spec.auto_scale:
                    continue

                # Get queue metrics
                metrics = await self.get_queue_metrics(worker_type)
                current_count = sum(
                    1 for w in self.managed_workers.values()
                    if w.worker_type == worker_type and w.state == WorkerState.RUNNING
                )

                avg_queue_depth = metrics['total_pending'] / current_count

                # Scale up
                if avg_queue_depth > spec.scale_threshold_high:
                    if current_count < spec.max_replicas:
                        scale_to = min(current_count + 5, spec.max_replicas)
                        await self.scale_workers(worker_type, scale_to)

                # Scale down
                elif avg_queue_depth < spec.scale_threshold_low:
                    if current_count > spec.min_replicas:
                        scale_to = max(current_count - 1, spec.min_replicas)
                        await self.scale_workers(worker_type, scale_to)

            await asyncio.sleep(30)  # Check every 30 seconds
```

**Queue Metrics Collection** (`get_queue_metrics`, lines 532-556):
- Maps worker types to stream patterns:
  - `task_execution`: `['task:ready', 'task:retry']`
  - `dependency`: `['task:completed', 'workflow:submitted']`
  - `workflow_loader`: `['workflow:load', 'workflow:reload']`
- Calculates total pending messages across all shards
- Returns `{total_pending, by_shard}` metrics

**Features**:
- Monitors queue depth across all 16 shards per worker type
- Calculates average queue depth per worker
- Scales workers up when avg depth > `scale_threshold_high` (default: 100)
- Scales workers down when avg depth < `scale_threshold_low` (default: 10)
- Respects min/max replica limits from `WorkerSpec`
- Scale up increment: +5 workers per cycle
- Scale down decrement: -1 worker per cycle
- Check interval: 30 seconds

**Configuration** (via `WorkerSpec`):
```python
auto_scale: bool = False
min_replicas: int = 1
max_replicas: int = 10
scale_threshold_high: int = 100  # Queue depth per worker to scale up
scale_threshold_low: int = 10    # Queue depth per worker to scale down
```

**Assessment**: ✅ Intelligent auto-scaling based on queue metrics. Good for handling traffic spikes.

---

### 6. Metrics Collection ✅ **IMPLEMENTED**

**Location**: `src/gleitzeit/orchestrator/component_orchestrator.py:685-732`

**Implementation Details**:
```python
async def metrics_collector(self):
    """Collect and aggregate metrics from all components"""
    while self._running:
        try:
            metrics = {
                'timestamp': datetime.utcnow().isoformat(),
                'workers': {},
                'queues': {},
                'system': {}
            }

            # Collect worker metrics
            for worker_id, worker in self.managed_workers.items():
                if worker.state != WorkerState.RUNNING:
                    continue

                worker_metrics = await self.redis.hgetall(
                    f"{{shard:0}}:worker:metrics:{worker_id}".encode()
                )

                if worker_metrics:
                    metrics['workers'][worker_id] = {
                        k.decode(): v.decode() for k, v in worker_metrics.items()
                    }

            # Collect queue metrics
            for worker_type in self.worker_specs.keys():
                metrics['queues'][worker_type] = await self.get_queue_metrics(worker_type)

            # System metrics
            metrics['system'] = {
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'redis_healthy': self.health_status.get('redis', False)
            }

            # Store aggregated metrics
            await self.redis.hset(
                b"orchestrator:metrics",
                b"latest",
                json.dumps(metrics).encode()
            )

            await asyncio.sleep(60)  # Collect every minute
```

**Metrics Collected**:
- **Worker Metrics** (per worker):
  - Messages processed
  - Messages failed
  - Uptime
  - Last heartbeat timestamp
- **Queue Metrics** (per worker type):
  - Total pending messages
  - Pending messages by shard
- **System Metrics**:
  - CPU usage percent
  - Memory usage percent
  - Redis health status

**Storage**:
- Redis key: `orchestrator:metrics`
- Field: `latest`
- Format: JSON-encoded metrics dictionary
- Update frequency: Every 60 seconds

**Assessment**: ✅ Comprehensive metrics collection covering workers, queues, and system resources.

---

## ⚠️ CRITICAL GAPS IDENTIFIED

### 1. Redis Failure Handling - HeartbeatMonitor NOT IMPLEMENTED ❌

**Severity**: **CRITICAL**
**Risk Level**: **HIGH**

**Design Document**: `HEARTBEAT_SHUTDOWN_DESIGN.md` (471 lines, fully specified)

**Status**: **Design only, no implementation exists in codebase**

**What's Missing**:

#### Missing Class: `HeartbeatMonitor`
**Expected Location**: `src/gleitzeit/core/heartbeat_monitor.py` (does not exist)

**Expected Features** (from design):
1. **State Machine**: HEALTHY → WARNING → CRITICAL → SHUTDOWN
2. **Redis Connectivity Monitoring**:
   - Continuous ping checks
   - Exponential backoff on failures
   - State transitions based on failure duration
3. **Graceful Shutdown Logic**:
   - Stop accepting new work
   - Wait for in-flight tasks (configurable grace period)
   - Force shutdown after timeout
4. **Configuration Support**:
   - `redis.heartbeat.enabled` (default: true)
   - `redis.heartbeat.interval` (default: 30s)
   - `redis.heartbeat.warning_threshold` (default: 3 failures)
   - `redis.heartbeat.critical_timeout` (default: 120s)
   - `redis.heartbeat.shutdown_timeout` (default: 300s)
   - `redis.shutdown.mode` (graceful/immediate)
   - `redis.shutdown.grace_period` (default: 30s)
   - `redis.shutdown.force_after` (default: 60s)

**Current Behavior Without HeartbeatMonitor**:
- Services and workers **retry indefinitely** when Redis fails
- No escalation path from transient errors to system shutdown
- Services run in degraded state without coordination
- No graceful shutdown after extended Redis outage
- Unpredictable system behavior when Redis is down >5 minutes

**Impact**:
- **High availability risk**: Services can't detect when to give up
- **Resource waste**: Processes continue running without coordination
- **Data inconsistency**: Workflows may execute without proper state tracking
- **Operational blindness**: No clear signal that system is unhealthy

**Example Scenario**:
```
t=0s:    Redis goes down
t=0-120s: Workers/services retry with backoff, log warnings
t=120s:   SHOULD enter CRITICAL state, prepare for shutdown
t=300s:   SHOULD initiate graceful shutdown
t=330s:   SHOULD complete graceful shutdown (30s grace period)
t=360s:   SHOULD force shutdown if tasks incomplete

ACTUAL:   Services retry forever, no shutdown occurs
```

**Files Expected But Missing**:
- `src/gleitzeit/core/heartbeat_monitor.py`
- Configuration integration in `src/gleitzeit/core/config_manager.py`
- Integration in `src/gleitzeit/core/async_process_manager.py`

---

### 2. Inconsistent Heartbeat Configuration ⚠️

**Severity**: **MEDIUM**
**Risk Level**: **MEDIUM**

**Problem**: Heartbeat intervals are hardcoded throughout codebase with inconsistent values.

**Inconsistencies Found**:

| Component | Location | Interval | Configuration Source |
|-----------|----------|----------|---------------------|
| Workers | `base.py:34` | 30s | Hardcoded in `WorkerConfig` dataclass |
| Services | `async_process_manager.py:804` | 30s | Hardcoded in method |
| Config File | `gleitzeit.yaml:176` | 10s | `monitoring.heartbeat_interval` |
| Orchestrator Health | `component_orchestrator.py:454` | 10s | Hardcoded (health check interval) |
| Orchestrator Auto-scale | `component_orchestrator.py:526` | 30s | Hardcoded (scale check interval) |
| Metrics Collection | `component_orchestrator.py:728` | 60s | Hardcoded |

**Issues**:
1. Configuration file value (`monitoring.heartbeat_interval: 10`) is **not used anywhere**
2. Workers and services use 30s, config says 10s
3. No central configuration management
4. Cannot tune heartbeat intervals without code changes
5. Different components use different intervals (health=10s, heartbeat=30s, metrics=60s)

**Impact**:
- Configuration file is misleading (values don't apply)
- Hard to tune system behavior for different environments
- Inconsistent monitoring granularity across components

**Recommendation**:
- Centralize all intervals in `gleitzeit.yaml`
- Add configuration loading in `ConfigurationManager`
- Pass intervals to components via config
- Remove all hardcoded intervals

---

### 3. Service Heartbeat Loop Termination ⚠️

**Severity**: **HIGH**
**Risk Level**: **HIGH**

**Location**: `src/gleitzeit/core/async_process_manager.py:795-868`

**Problem**: Service heartbeat loop **terminates permanently** after 100 total failures.

**Code Analysis**:
```python
async def _service_heartbeat_loop(self):
    consecutive_failures = 0
    max_consecutive_failures = 10
    total_failures = 0
    max_total_failures = 100  # HARD LIMIT

    while True:  # Infinite loop
        try:
            # ... heartbeat logic ...
            consecutive_failures = 0  # Reset on success
        except Exception as e:
            consecutive_failures += 1
            total_failures += 1

            # Check if we should stop trying
            if total_failures >= max_total_failures:
                logger.critical(
                    f"Service heartbeat has failed {total_failures} times total. "
                    "Stopping heartbeat loop - services will no longer be discoverable!"
                )
                break  # EXIT LOOP PERMANENTLY

    logger.critical("Service heartbeat loop has terminated - services are no longer being refreshed!")
```

**Consequences**:
1. After 100 failures (can occur over 8-13 minutes with backoff), loop **exits**
2. Services (API, UI) are **no longer refreshed** in Redis
3. Service registrations **expire** (TTL runs out)
4. Services become **permanently undiscoverable** to other components
5. **No recovery mechanism** - even if Redis comes back, heartbeat never resumes
6. **Silent degradation** - no notification to orchestrator or health endpoints

**Failure Scenarios**:
- **Redis flapping**: If Redis goes up/down repeatedly, failures accumulate
- **Network issues**: Transient network problems can trigger 100 failures
- **Redis maintenance**: Extended maintenance windows exceed failure threshold

**Impact**:
- **Service mesh breaks**: Other services can't find API/UI
- **Health checks fail**: `/health/cluster` shows no services
- **Manual intervention required**: Services must be restarted to restore heartbeat
- **Production outage**: Subtle failure mode that's hard to detect

**Current Mitigation**: None

**Recommendation**: Replace hard termination with circuit breaker pattern or infinite retry with longer backoff.

---

### 4. Worker Health Check Limitations ⚠️

**Severity**: **MEDIUM**
**Risk Level**: **MEDIUM**

**Location**: `src/gleitzeit/orchestrator/component_orchestrator.py:460-490`

**Current Health Check Logic**:
```python
async def check_worker_health(self, worker_id: str) -> bool:
    # 1. Check process exists
    if not worker or not worker.process:
        return False

    # 2. Check process hasn't exited
    if worker.process.returncode is not None:
        return False

    # 3. Check heartbeat recency
    heartbeat = await self.redis.hget(
        f"{{shard:0}}:worker:metrics:{worker_id}".encode(),
        b"last_heartbeat"
    )

    if heartbeat:
        last_heartbeat = datetime.fromisoformat(heartbeat.decode())
        age = datetime.utcnow() - last_heartbeat

        if age > timedelta(seconds=60):
            return False  # Stale heartbeat
    else:
        return False  # No heartbeat

    return True
```

**What's Checked**: ✅
- Process existence
- Process exit status
- Heartbeat recency (<60 seconds)

**What's NOT Checked**: ❌
1. **Queue depth per worker**: Is worker keeping up with its workload?
2. **Stuck processing**: Is worker processing but never completing?
3. **Memory usage**: Is worker leaking memory?
4. **CPU usage**: Is worker in infinite loop?
5. **Message processing rate**: Has throughput dropped?
6. **Error rate**: Is worker failing most messages?
7. **Circuit breaker state**: Are downstream handlers failing?
8. **Redis connection health**: Can worker actually access Redis?

**Problems**:
- **False positives**: Worker appears healthy but is actually stuck/slow
- **Late detection**: Problems only detected after worker stops heartbeating
- **No performance monitoring**: Can't detect degraded workers
- **Coarse granularity**: Only binary healthy/unhealthy state

**Example Scenarios Not Detected**:
1. Worker processes messages but takes 10x longer than normal
2. Worker memory grows to 90% but still heartbeats
3. Worker's Redis commands timeout but process is alive
4. Worker is stuck in retry loop for a single message

**Impact**:
- Delayed problem detection
- Reduced system throughput (slow workers not detected)
- Potential cascading failures (memory exhaustion)

**Recommendation**: Add enhanced health checks with metrics-based thresholds.

---

### 5. No Distributed Health Coordination ⚠️

**Severity**: **MEDIUM**
**Risk Level**: **MEDIUM**

**Problem**: In multi-instance deployments, each instance only monitors its own processes.

**Current Behavior**:
- Each `AsyncServiceManager` monitors only processes it started
- Each `ComponentOrchestrator` monitors only workers it spawned
- `/health/cluster` endpoint discovers services but doesn't coordinate health state
- No global health aggregation

**Missing Capabilities**:
1. **Global Health State**: No shared view of overall system health
2. **Cross-Instance Failure Detection**: Instance A can't detect when Instance B's workers fail
3. **Coordinated Shutdown**: Instances don't coordinate when entering degraded state
4. **Split-Brain Detection**: Can't detect when instances have divergent views
5. **Cluster Consensus**: No agreement on whether system is healthy

**Example Scenario**:
```
Instance A: Healthy (2 workers, API, UI)
Instance B: Degraded (0 workers, Redis timeouts)
Instance C: Healthy (3 workers, API)

Problem: No instance knows overall cluster is degraded
Solution: Need global health state in Redis
```

**Impact**:
- **Operational blindness**: Can't see full cluster health
- **Load balancer issues**: May route to unhealthy instances
- **Cascading failures**: Degraded instances not detected early
- **Manual intervention**: Need to check each instance separately

**Current Workaround**: Use `/health/cluster` endpoint, but it only shows service discovery, not actual health validation.

**Recommendation**: Implement distributed health coordination with Redis as source of truth.

---

### 6. Missing Health Probes for Workers ⚠️

**Severity**: **LOW**
**Risk Level**: **LOW**

**Problem**: Workers don't expose health endpoints for external monitoring.

**Current State**:
- Workers only send heartbeats to Redis
- No HTTP endpoints on workers
- Can't probe worker health from outside cluster
- External monitoring tools (Prometheus, Datadog) can't scrape workers

**Missing Capabilities**:
1. **HTTP Health Endpoints**: `/health`, `/ready`, `/live` for workers
2. **Metrics Endpoints**: `/metrics` for Prometheus scraping
3. **Deep Health Checks**: Application-level health beyond just heartbeat
4. **Circuit Breaker Status**: Expose handler circuit breaker states
5. **Queue Status**: Expose pending message counts per worker

**Comparison with Services**:
- API/UI: Have full health endpoints via FastAPI
- Workers: No HTTP interface at all

**Workarounds**:
- Check Redis heartbeat keys manually
- Monitor orchestrator metrics
- Use `/health/detailed` API endpoint

**Impact**:
- **Limited observability**: Can't integrate with standard monitoring tools
- **No deep health checks**: Can't distinguish between "alive" and "working correctly"
- **External monitoring gaps**: Prometheus/Grafana can't scrape workers
- **Debug difficulty**: Can't query worker state directly

**Recommendation**: Add lightweight HTTP server to workers (optional, configurable).

---

## Configuration Audit

### Current Configuration (`gleitzeit.yaml`)

**Monitoring Section** (lines 173-177):
```yaml
monitoring:
  health_check_interval: 30
  heartbeat_interval: 10
  scale_check_interval: 60
```

**Usage Analysis**:
- ❌ `health_check_interval: 30` - **NOT USED** (orchestrator uses hardcoded 10s)
- ❌ `heartbeat_interval: 10` - **NOT USED** (workers/services use hardcoded 30s)
- ❌ `scale_check_interval: 60` - **NOT USED** (orchestrator uses hardcoded 30s)

**Assessment**: Configuration values are **ignored** by all components.

---

### Missing Configuration (Per Design Document)

**Expected in `gleitzeit.yaml`**:
```yaml
redis:
  mode: single
  single_node:
    host: localhost
    port: 6379

  # MISSING: Heartbeat configuration
  heartbeat:
    enabled: true                    # Enable heartbeat monitoring
    interval: 30                     # Heartbeat interval in seconds
    warning_threshold: 3             # Consecutive failures before WARNING state
    critical_timeout: 120            # Seconds before CRITICAL state
    shutdown_timeout: 300            # Seconds before SHUTDOWN

  # MISSING: Shutdown behavior configuration
  shutdown:
    mode: "graceful"                 # "graceful" or "immediate"
    grace_period: 30                 # Seconds to wait for task completion
    force_after: 60                  # Force shutdown after this many seconds
```

**Expected in `ConfigurationManager`**:
```python
def get_redis_heartbeat_config(self) -> dict:
    """Get Redis heartbeat configuration from gleitzeit.yaml"""
    return self.config.get('redis', {}).get('heartbeat', {})

def get_redis_shutdown_config(self) -> dict:
    """Get Redis shutdown configuration from gleitzeit.yaml"""
    return self.config.get('redis', {}).get('shutdown', {})

def get_redis_heartbeat_enabled(self) -> bool:
    """Check if heartbeat monitoring is enabled"""
    return self.get_redis_heartbeat_config().get('enabled', True)
```

**Status**: None of these methods exist in `ConfigurationManager`.

---

## Recommendations

### Priority: P0 - Critical (Implement Immediately)

#### 1. Implement HeartbeatMonitor from Design Document
**Effort**: 2-3 days
**Impact**: Critical for production resilience

**Tasks**:
1. Create `src/gleitzeit/core/heartbeat_monitor.py` with `HeartbeatMonitor` class
2. Implement state machine: HEALTHY → WARNING → CRITICAL → SHUTDOWN
3. Add Redis failure detection and escalation logic
4. Implement graceful shutdown with task completion wait
5. Add configuration methods to `ConfigurationManager`:
   - `get_redis_heartbeat_config()`
   - `get_redis_shutdown_config()`
   - `get_redis_heartbeat_enabled()`
6. Integrate with `AsyncServiceManager` (lines 420-427 per design)
7. Add `redis.heartbeat` and `redis.shutdown` sections to `gleitzeit.yaml`
8. Write unit tests for state transitions
9. Write integration tests for Redis failure scenarios

**Acceptance Criteria**:
- [ ] HeartbeatMonitor class exists and implements full state machine
- [ ] Configuration is loaded from `gleitzeit.yaml`
- [ ] Graceful shutdown is triggered after configured timeout
- [ ] Services wait for in-flight tasks during shutdown
- [ ] Force shutdown occurs after grace period expires
- [ ] Automatic recovery when Redis comes back online
- [ ] Comprehensive logging at each state transition

---

#### 2. Fix Service Heartbeat Loop Termination
**Effort**: 4-8 hours
**Impact**: High - Prevents silent service degradation

**Tasks**:
1. Remove hard termination after 100 failures in `async_process_manager.py:853-858`
2. Implement circuit breaker pattern:
   - Open state: Long backoff (5 minutes)
   - Half-open state: Test single heartbeat
   - Closed state: Normal operation
3. Add exponential backoff with maximum (e.g., cap at 5 minutes)
4. Notify orchestrator when entering circuit breaker open state
5. Add configuration for circuit breaker thresholds
6. Add recovery detection and notification
7. Update monitoring to track circuit breaker state

**Proposed Implementation**:
```python
async def _service_heartbeat_loop(self):
    circuit_breaker = CircuitBreaker(
        failure_threshold=10,
        timeout=300,  # 5 minutes
        expected_exception=Exception
    )

    while True:
        try:
            if circuit_breaker.state == CircuitBreakerState.OPEN:
                # Long backoff when circuit is open
                await asyncio.sleep(300)
                # Try to close circuit
                circuit_breaker.half_open()

            # Attempt heartbeat
            await self._refresh_service_registrations()
            circuit_breaker.record_success()

            await asyncio.sleep(30)

        except Exception as e:
            circuit_breaker.record_failure()

            if circuit_breaker.state == CircuitBreakerState.OPEN:
                logger.error("Service heartbeat circuit breaker is OPEN")
                # Notify orchestrator of degraded state
                await self._notify_degraded_state()

            # Exponential backoff
            await asyncio.sleep(circuit_breaker.get_backoff_delay())
```

**Acceptance Criteria**:
- [ ] Heartbeat loop never terminates
- [ ] Circuit breaker pattern implemented
- [ ] Long backoff in open state (5 minutes)
- [ ] Automatic recovery testing in half-open state
- [ ] Orchestrator notified of circuit breaker state
- [ ] Logging shows circuit breaker state transitions

---

### Priority: P1 - High (Implement Soon)

#### 3. Centralize Heartbeat Configuration
**Effort**: 1-2 days
**Impact**: Medium - Improves maintainability and consistency

**Tasks**:
1. Update `gleitzeit.yaml` monitoring section:
   ```yaml
   monitoring:
     worker:
       heartbeat_interval: 30
       heartbeat_timeout: 60
       max_health_failures: 3
     service:
       heartbeat_interval: 30
       registration_ttl: 90
     orchestrator:
       health_check_interval: 10
       metrics_collection_interval: 60
       auto_scale_check_interval: 30
   ```

2. Update `ConfigurationManager` to load monitoring config:
   ```python
   def get_worker_monitoring_config(self) -> dict:
       return self.config.get('monitoring', {}).get('worker', {})

   def get_service_monitoring_config(self) -> dict:
       return self.config.get('monitoring', {}).get('service', {})

   def get_orchestrator_monitoring_config(self) -> dict:
       return self.config.get('monitoring', {}).get('orchestrator', {})
   ```

3. Update `WorkerConfig` to use config values:
   ```python
   @dataclass
   class WorkerConfig:
       # ... existing fields ...
       heartbeat_interval: int = 30  # Default, can be overridden by config
   ```

4. Update `BaseWorker` to load interval from config
5. Update `AsyncServiceManager._service_heartbeat_loop()` to use config interval
6. Update `ComponentOrchestrator` to use config intervals for:
   - Health check interval
   - Auto-scale check interval
   - Metrics collection interval
7. Remove all hardcoded intervals
8. Add validation for config values (e.g., intervals > 0)
9. Update documentation to reflect configurable intervals

**Acceptance Criteria**:
- [ ] All intervals configurable via `gleitzeit.yaml`
- [ ] No hardcoded intervals remain
- [ ] Config values are validated on load
- [ ] Default values provided if config missing
- [ ] Documentation updated with configuration options

---

#### 4. Enhance Worker Health Checks
**Effort**: 2-3 days
**Impact**: Medium-High - Improves problem detection

**Tasks**:
1. Extend worker metrics to include:
   ```python
   {
       "processed": count,
       "failed": count,
       "uptime": seconds,
       "last_heartbeat": timestamp,
       # NEW METRICS:
       "memory_mb": current_memory,
       "cpu_percent": current_cpu,
       "processing_rate": messages_per_minute,
       "avg_processing_time_ms": average_time,
       "pending_count": messages_in_queue,
       "error_rate": errors_per_minute,
       "circuit_breaker_state": "closed|open|half_open"
   }
   ```

2. Update `BaseWorker._heartbeat_loop()` to collect system metrics:
   ```python
   import psutil

   process = psutil.Process()
   memory_mb = process.memory_info().rss / 1024 / 1024
   cpu_percent = process.cpu_percent()
   ```

3. Update `ComponentOrchestrator.check_worker_health()` with enhanced checks:
   ```python
   async def check_worker_health(self, worker_id: str) -> tuple[bool, str]:
       # Existing checks...

       # NEW: Check memory usage
       if memory_mb > 1024:  # > 1GB
           return False, "memory_limit_exceeded"

       # NEW: Check processing rate
       if processing_rate < 0.1:  # < 6 messages/min
           return False, "low_throughput"

       # NEW: Check error rate
       if error_rate > 0.5:  # > 50% errors
           return False, "high_error_rate"

       # NEW: Check circuit breaker
       if circuit_breaker_state == "open":
           return False, "circuit_breaker_open"

       return True, "healthy"
   ```

4. Add configurable thresholds to `WorkerSpec`:
   ```python
   @dataclass
   class WorkerSpec:
       # ... existing fields ...
       health_thresholds: Dict[str, Any] = field(default_factory=lambda: {
           'max_memory_mb': 1024,
           'min_processing_rate': 0.1,
           'max_error_rate': 0.5,
           'max_avg_processing_time_ms': 30000
       })
   ```

5. Update health check logging to include failure reason
6. Add metrics to orchestrator status endpoint
7. Update `/health/detailed` to include worker performance metrics

**Acceptance Criteria**:
- [ ] Worker metrics include system resource usage
- [ ] Health checks detect stuck/slow workers
- [ ] Health checks detect high error rates
- [ ] Health checks detect circuit breaker failures
- [ ] Thresholds are configurable per worker type
- [ ] Health check failures include diagnostic reason
- [ ] Metrics exposed via health endpoints

---

### Priority: P2 - Medium (Plan for Future)

#### 5. Distributed Health Coordination
**Effort**: 3-5 days
**Impact**: Medium - Improves multi-instance deployments

**Approach**: Implement global health state in Redis with instance coordination.

**Design Overview**:
```yaml
# Redis key: cluster:health:state
{
  "status": "healthy|degraded|critical|unhealthy",
  "updated_at": "2025-09-30T14:30:00Z",
  "updated_by": "instance-A",
  "instances": {
    "instance-A": {
      "status": "healthy",
      "workers": 5,
      "services": 3,
      "last_heartbeat": "2025-09-30T14:30:00Z"
    },
    "instance-B": {
      "status": "degraded",
      "workers": 2,
      "services": 1,
      "last_heartbeat": "2025-09-30T14:29:45Z"
    }
  },
  "aggregate_metrics": {
    "total_workers": 7,
    "total_services": 4,
    "healthy_instances": 1,
    "degraded_instances": 1
  }
}
```

**Tasks**:
1. Create `DistributedHealthCoordinator` class
2. Each instance reports its health to `cluster:health:instances:{instance_id}`
3. Leader instance aggregates global health state
4. Implement leader election via Redis locks
5. Add health state synchronization on startup
6. Update `/health/cluster` to use global health state
7. Add cross-instance failure detection
8. Implement coordinated shutdown signals

**Acceptance Criteria**:
- [ ] Global health state maintained in Redis
- [ ] All instances report local health
- [ ] Leader aggregates cluster health
- [ ] Leader election works correctly
- [ ] Health state visible via API endpoints
- [ ] Cross-instance failures detected

---

#### 6. Worker Health Endpoints (Optional)
**Effort**: 2-3 days
**Impact**: Low-Medium - Improves observability

**Approach**: Add lightweight HTTP server to workers for health/metrics endpoints.

**Design**:
```python
# In BaseWorker
async def start_health_server(self, port: int = None):
    """Start lightweight HTTP server for health checks"""
    from aiohttp import web

    async def health_handler(request):
        return web.json_response({
            "status": "healthy" if self._running else "stopped",
            "worker_id": self.config.worker_id,
            "worker_type": self.config.worker_type,
            "uptime": (datetime.utcnow() - self.started_at).total_seconds(),
            "processed": self.messages_processed,
            "failed": self.messages_failed
        })

    async def metrics_handler(request):
        # Prometheus format
        return web.Response(text=f"""
        worker_messages_processed{{worker_id="{self.config.worker_id}"}} {self.messages_processed}
        worker_messages_failed{{worker_id="{self.config.worker_id}"}} {self.messages_failed}
        worker_uptime_seconds{{worker_id="{self.config.worker_id}"}} {(datetime.utcnow() - self.started_at).total_seconds()}
        """)

    app = web.Application()
    app.router.add_get('/health', health_handler)
    app.router.add_get('/metrics', metrics_handler)

    # Run on dynamic port or configured port
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port or 0)
    await site.start()
```

**Configuration**:
```yaml
workers:
  - worker_type: task_execution
    health_endpoint:
      enabled: true
      port: 0  # Dynamic port
```

**Acceptance Criteria**:
- [ ] Workers expose `/health` endpoint
- [ ] Workers expose `/metrics` endpoint (Prometheus format)
- [ ] Health server is optional and configurable
- [ ] Health server doesn't interfere with worker processing
- [ ] Metrics are accurate and up-to-date

---

## Risk Assessment

### Critical Risks
1. **Redis Failure Handling**: System runs indefinitely in degraded state - **HIGH RISK**
2. **Service Heartbeat Termination**: Services become undiscoverable - **HIGH RISK**

### High Risks
3. **Inconsistent Configuration**: Hardcoded values prevent tuning - **MEDIUM RISK**
4. **Limited Health Checks**: Late detection of worker problems - **MEDIUM RISK**

### Medium Risks
5. **No Distributed Coordination**: Multi-instance deployments lack global view - **MEDIUM RISK**

### Low Risks
6. **No Worker Endpoints**: Limited external monitoring integration - **LOW RISK**

---

## Testing Recommendations

### Unit Tests Needed
1. `HeartbeatMonitor` state transitions
2. Configuration loading for all intervals
3. Enhanced health check logic
4. Circuit breaker behavior

### Integration Tests Needed
1. Redis failure scenarios (temporary, extended, permanent)
2. Service heartbeat recovery after failures
3. Worker health check with degraded performance
4. Multi-instance health coordination

### Load Tests Needed
1. Heartbeat performance under high load
2. Health check scalability with 50+ workers
3. Metrics collection overhead

---

## Conclusion

Gleitzeit has a **solid foundation** for heartbeat and monitoring, with comprehensive implementations for workers, services, health checks, and orchestration. However, **critical gaps exist**:

1. **HeartbeatMonitor** (Redis failure handling) is designed but not implemented - **MUST FIX**
2. Service heartbeat loop terminates permanently - **MUST FIX**
3. Configuration is inconsistent and largely ignored - **SHOULD FIX**
4. Health checks are basic and miss performance degradation - **SHOULD ENHANCE**

**Immediate Action Required**: Implement P0 items (HeartbeatMonitor, fix service heartbeat termination) to achieve production readiness.

**Next Steps**: Centralize configuration (P1) to improve maintainability and enable operational tuning.

**Future Enhancements**: Add distributed coordination and worker endpoints (P2) for advanced observability in large deployments.