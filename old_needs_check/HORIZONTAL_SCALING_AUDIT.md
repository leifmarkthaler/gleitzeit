# Gleitzeit 0.0.7 - Horizontal Scaling Audit Report

**Date**: 2025-10-13
**Version**: 0.0.7
**Auditor**: Claude Code Analysis

## Executive Summary

This audit identifies horizontal scaling issues in Gleitzeit 0.0.7 that would prevent multiple instances of the system from running concurrently without conflicts. The codebase shows a mix of good practices (leader election, distributed locking) and concerning patterns (global singleton, potential log duplication).

**Overall Risk Level**: **MEDIUM**

The system can scale horizontally with proper configuration, but certain components have scaling limitations that need to be documented and potentially addressed.

---

## 1. Critical Issues (Must Fix for Multi-Instance Deployment)

### 1.1 **Loki Exporter Worker - No Coordination**

**Location**: [src/gleitzeit/workers/loki_exporter_worker.py](src/gleitzeit/workers/loki_exporter_worker.py)

**Issue**: The Loki exporter polls Redis logs and exports them to Loki, but has NO coordination mechanism between multiple instances.

**Impact**:
- **HIGH** - Multiple Loki exporters running simultaneously will:
  - Export duplicate logs to Loki (wasting storage)
  - Potentially conflict on `last_exported_timestamp` tracking
  - Create unnecessary load on both Redis and Loki

**Evidence**:
```python
# Line 54: last_exported_timestamp is in-memory only
self.last_exported_timestamp: Dict[str, int] = {}  # Track per level

# Line 209-234: Main loop has no leader election or distributed lock
async def run(self):
    await self.initialize()
    self.running = True

    levels = ["DEBUG", "INFO", "WARNING", "ERROR"]

    while self.running:
        # No coordination - all instances will do this!
        for level in levels:
            await self.export_level(level)
```

**Recommendation**: **CRITICAL - ADD LEADER ELECTION**

Add leader election similar to TimerWorker and SignalWorker:

```python
class LokiExporterWorker:
    def __init__(self, ...):
        # ... existing code ...
        self.leader_election: Optional[LeaderElection] = None
        self.leader_key = "global:loki_exporter:leader"
        self.leader_ttl = 30  # seconds

    async def initialize(self):
        # ... existing code ...
        # Initialize leader election
        self.leader_election = LeaderElection(
            self.redis,
            self.leader_key,
            self.worker_id,
            self.leader_ttl
        )

    async def run(self):
        await self.initialize()
        self.running = True

        # Start leader election loop
        election_task = asyncio.create_task(self._leader_election_loop())

        # Main loop - only export if leader
        while self.running:
            if self.leader_election and self.leader_election.is_leader:
                for level in levels:
                    await self.export_level(level)

            await asyncio.sleep(self.poll_interval)
```

**Alternative**: Make Loki exporter a **singleton service** that's only started once per deployment (not per instance). Document this clearly in deployment guides.

---

### 1.2 **Global Sharding Singleton - Configuration Conflict Risk**

**Location**: [src/gleitzeit/core/sharding.py:259](src/gleitzeit/core/sharding.py#L259)

**Issue**: The `default_sharding` object is a module-level singleton with hardcoded configuration:

```python
# Line 259
default_sharding = ClusterShardingStrategy(num_shards=16)
```

**Impact**:
- **MEDIUM** - If different instances use different `num_shards` configurations, they will route workflows to different shards, causing:
  - Workflows to be split across incompatible shards
  - Stream consumption failures
  - Workflow state corruption

**Evidence**:
- The singleton is instantiated at module import time
- No validation that all instances use the same configuration
- Configuration comes from gleitzeit.yaml but singleton doesn't read from it

**Recommendation**: **HIGH PRIORITY**

Option 1: **Validate configuration consistency** across instances:
```python
async def validate_sharding_config(redis):
    """Ensure all instances use the same sharding configuration"""
    config_key = "global:config:num_shards"

    stored_shards = await redis.get(config_key)
    if stored_shards:
        if int(stored_shards) != default_sharding.num_shards:
            raise ConfigurationError(
                f"Sharding mismatch: this instance uses {default_sharding.num_shards} "
                f"shards but cluster expects {stored_shards}"
            )
    else:
        # First instance - store config
        await redis.set(config_key, str(default_sharding.num_shards))
```

Option 2: **Make sharding configurable** per instance (requires significant refactoring).

---

## 2. Design Patterns Analysis

### 2.1 **✅ GOOD: Timer Worker Leader Election**

**Location**: [src/gleitzeit/workers/timer_worker.py](src/gleitzeit/workers/timer_worker.py)

**Pattern**: Atomic leader election using Lua scripts

```python
# Lines 35-38: Leader election setup
self.leader_election = LeaderElection(
    self.redis,
    self.leader_key,
    self.config.worker_id,
    self.leader_ttl
)

# Lines 107-119: Only leader processes timers
async def _timer_processing_loop(self):
    while self._running:
        if self.leader_election and self.leader_election.is_leader:
            processed, fired_timers = await StatelessTimerManager.process_due_timers(
                self.redis,
                max_timers=100
            )
```

**Analysis**: ✅ **Horizontally scalable** - Multiple timer workers can run, but only the leader will process timers. Automatic failover if leader crashes (TTL expires).

---

### 2.2 **✅ GOOD: Signal Worker Leader Election**

**Location**: [src/gleitzeit/workers/signal_worker.py](src/gleitzeit/workers/signal_worker.py)

**Pattern**: Same atomic leader election pattern as timer worker

```python
# Lines 42-48: Leader election setup
self.leader_election = LeaderElection(
    self.redis,
    self.leader_key,
    self.config.worker_id,
    self.leader_ttl
)

# Lines 113-124: Only leader processes signals
if self.leader_election and self.leader_election.is_leader:
    await self._process_workflow_signals()
    await self._check_signal_timeouts()
```

**Analysis**: ✅ **Horizontally scalable** - Multiple signal workers can run safely.

---

### 2.3 **✅ GOOD: Reconciliation Worker Distributed Locking**

**Location**: [src/gleitzeit/workers/reconciliation_worker.py](src/gleitzeit/workers/reconciliation_worker.py)

**Pattern**: Per-shard distributed locks

```python
# Lines 208-236: Acquire lock for each shard before reconciliation
@asynccontextmanager
async def acquire_shard_lock(self, shard: int):
    lock_key = f"{{shard:{shard}}}:reconciliation:lock"
    lock_value = f"{self.config.worker_id}:{uuid.uuid4()}"

    # Try to acquire lock with Redis SET NX EX
    acquired = await self.redis.set(
        lock_key.encode(),
        lock_value.encode(),
        nx=True,  # Only set if not exists
        ex=self.lock_ttl  # Expire after TTL
    )

    if not acquired:
        raise LockAcquisitionError(f"Could not acquire lock for shard {shard}")
```

**Analysis**: ✅ **Horizontally scalable** - Multiple reconciliation workers can run. Each worker will:
- Try to lock shards assigned to it
- Skip shards locked by other workers
- Process only unlocked shards
- Locks expire automatically (self-healing)

---

### 2.4 **✅ GOOD: Stream-Based Workers (Task Execution, Dependency)**

**Location**:
- [src/gleitzeit/workers/task_execution_worker.py](src/gleitzeit/workers/task_execution_worker.py)
- [src/gleitzeit/workers/dependency_worker.py](src/gleitzeit/workers/dependency_worker.py)

**Pattern**: Redis Streams with consumer groups

**Evidence**:
```python
# Dependency worker processes messages from streams
def get_base_streams(self) -> List[str]:
    return ["task:completed", "task:failed", "workflow:submitted",
            "task:cancelled", "workflow:cancelled"]

# Consumer group ensures each message is processed exactly once
async def consume_messages(self):
    messages = await self.redis.xreadgroup(
        self.config.consumer_group,
        self.config.worker_id,
        {stream_key: b">"},  # Read new messages only
        count=self.config.batch_size,
        block=self.config.block_timeout
    )
```

**Analysis**: ✅ **Horizontally scalable** - Redis Streams with consumer groups provide:
- Exactly-once message delivery semantics
- Automatic load balancing across workers
- No duplicate processing
- Automatic retry for failed messages (PEL - Pending Entry List)

---

## 3. Configuration and State Management Issues

### 3.1 **Reconciliation Worker - In-Memory Metrics Removed** ✅

**Location**: [src/gleitzeit/workers/reconciliation_worker.py:105](src/gleitzeit/workers/reconciliation_worker.py#L105)

**Finding**: Good - Previously had in-memory metrics that would have been scaling issue. Now stateless:

```python
# Bug #19: Removed in-memory metrics - worker is now stateless
# Use structured logging via LoggingMixin for observability
```

**Analysis**: ✅ **No scaling issue** - Worker is stateless, metrics are logged to Redis.

---

### 3.2 **Dependency Worker - LRU Cache Instance**

**Location**: [src/gleitzeit/workers/dependency_worker.py:36-39](src/gleitzeit/workers/dependency_worker.py#L36-L39)

**Issue**: Each worker has its own in-memory LRU cache:

```python
# Line 36-39
cache_size = config.__dict__.get('dependency_cache_size', 500)
cache_ttl = config.__dict__.get('dependency_cache_ttl', 1800)
self.dependency_cache = LRUCache(max_size=cache_size, default_ttl=cache_ttl)
```

**Impact**:
- **LOW** - Caches will be inconsistent across instances
- Each instance will have cache misses that others already cached
- NOT a correctness issue (cache is optimization only)
- Slightly reduced efficiency

**Recommendation**: **LOW PRIORITY**

Document this as expected behavior OR implement Redis-backed shared cache if cache hit rate is critical for performance.

---

## 4. Logging and Observability

### 4.1 **Redis Logging - Shard-Based (Good)**

**Location**: [src/gleitzeit/core/stateless_log_service.py](src/gleitzeit/core/stateless_log_service.py)

**Pattern**: Logs are sharded by workflow_id

**Analysis**: ✅ **No scaling issue** - Logs are written to Redis, sharded properly. Multiple instances can write logs without conflict.

---

### 4.2 **Loki Exporter - Duplicate Export Risk** ⚠️

**Already covered in Critical Issue 1.1 above**

---

## 5. Process Management and Deployment

### 5.1 **AsyncProcessManager - Process Launching**

**Location**: [src/gleitzeit/core/async_process_manager.py](src/gleitzeit/core/async_process_manager.py)

**Issue**: Each Gleitzeit instance will try to start its own copies of:
- API server (port conflict!)
- UI server (port conflict!)
- Loki exporter (duplicate exports!)
- Workers (OK - coordinated via streams/leader election)

**Impact**:
- **HIGH** - Cannot run multiple Gleitzeit instances on same host
- Port conflicts for API/UI
- Duplicate Loki exporters

**Recommendation**: **ARCHITECTURAL DECISION NEEDED**

Option 1: **Deployment Model Clarification**
- Document that Gleitzeit is designed for **ONE instance per host**
- Multiple hosts should be used for redundancy, not multiple instances per host
- Use container orchestration (Kubernetes) to manage multiple instances across hosts

Option 2: **Split Services from Workers**
- Services (API, UI, Loki exporter) run as **singleton deployments**
- Workers run as **scalable deployments**
- Configure which components start via gleitzeit.yaml:
  ```yaml
  serve:
    api:
      enabled: true  # Only in service deployment
    ui:
      enabled: true  # Only in service deployment
    workers:
      enabled: false  # Disable in service deployment
    loki_exporter:
      enabled: true  # Only in service deployment
  ```

---

## 6. Remediation Plan

### Phase 1: Critical Fixes (Blocking Multi-Instance)

1. **Add leader election to Loki Exporter** ⚠️ **CRITICAL**
   - Estimated effort: 2-4 hours
   - Follow pattern from TimerWorker/SignalWorker
   - Test with 2+ instances running simultaneously

2. **Add sharding configuration validation** ⚠️ **HIGH**
   - Estimated effort: 1-2 hours
   - Prevent instances with mismatched configurations from starting
   - Store configuration in Redis on first start

3. **Document deployment model** ⚠️ **MEDIUM**
   - Estimated effort: 2-3 hours
   - Create DEPLOYMENT.md with:
     - Single-host vs multi-host deployment patterns
     - Port configuration for multiple instances
     - Service vs worker separation strategies
     - Container orchestration examples (Docker Compose, Kubernetes)

### Phase 2: Enhancements (Improve Scalability)

4. **Add health checks for coordination mechanisms**
   - Check leader election status
   - Check distributed lock health
   - Expose metrics for Prometheus

5. **Optimize reconciliation worker sharding**
   - Currently uses assigned_shards from BaseWorker
   - Could implement dynamic shard assignment based on load

6. **Shared cache implementation** (Optional)
   - Redis-backed shared cache for dependency resolution
   - Only if profiling shows cache hit rate is important

---

## 7. Testing Recommendations

### Test Scenario 1: Dual Instance Test
```bash
# Terminal 1
PORT=8000 gleitzeit serve

# Terminal 2
PORT=8001 gleitzeit serve

# Expected: Both should start without conflicts
# Expected: Logs should show leader election results
# Expected: Only one timer worker should be active
# Expected: Only one signal worker should be active
# Expected: NO duplicate Loki exports
```

### Test Scenario 2: Leader Failover Test
```bash
# Start two instances
# Identify which is leader for timers (check logs)
# Kill the leader instance
# Expected: Follower should become leader within TTL period (10-30s)
# Expected: No timer processing gaps > TTL
```

### Test Scenario 3: Stream Worker Scaling
```bash
# Start 1 instance, submit 100 workflows
# Measure processing time
# Start 2 instances, submit 100 workflows
# Expected: ~2x throughput improvement
# Expected: No duplicate workflow executions
```

---

## 8. Summary of Findings

| Component | Horizontal Scaling Status | Risk Level | Action Required |
|-----------|--------------------------|------------|-----------------|
| **TaskExecutionWorker** | ✅ Safe (Stream-based) | LOW | None |
| **DependencyWorker** | ✅ Safe (Stream-based) | LOW | Document cache behavior |
| **TimerWorker** | ✅ Safe (Leader election) | LOW | None |
| **SignalWorker** | ✅ Safe (Leader election) | LOW | None |
| **ReconciliationWorker** | ✅ Safe (Distributed locks) | LOW | None |
| **LokiExporterWorker** | ⚠️ **UNSAFE** (No coordination) | **HIGH** | **Add leader election** |
| **Sharding Config** | ⚠️ **RISKY** (No validation) | MEDIUM | Add validation |
| **Process Management** | ⚠️ **PORT CONFLICTS** | HIGH | Document deployment model |

---

## 9. Conclusion

Gleitzeit 0.0.7 has a **solid foundation** for horizontal scaling:
- Stream-based workers use Redis consumer groups correctly
- Leader election is properly implemented for timer/signal workers
- Distributed locking protects reconciliation operations
- Workflow sharding provides natural partitioning

**However**, two critical issues prevent immediate multi-instance deployment:
1. Loki exporter lacks coordination (will duplicate exports)
2. Process management assumes single instance per host (port conflicts)

**Recommendation**:
- Fix Loki exporter leader election (**CRITICAL** - 2-4 hours)
- Document deployment model (**HIGH** - 2-3 hours)
- Add configuration validation (**MEDIUM** - 1-2 hours)

Total estimated effort to make production-ready for horizontal scaling: **1-2 days**

---

**End of Audit Report**
