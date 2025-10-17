# Horizontal Scaling Phase 2: Design Document

**Status**: Design Phase
**Version**: 0.0.7
**Date**: 2025-10-15
**Author**: Architecture Team

---

## Executive Summary

This document outlines Phase 2 enhancements for Gleitzeit's horizontal scaling capabilities. Phase 1 successfully implemented critical fixes (leader election for Loki exporter and sharding configuration validation). Phase 2 focuses on operational reliability, performance optimization, and observability improvements for multi-instance deployments.

### Goals
1. **Health Checks** - Detect and alert on coordination mechanism failures
2. **Reconciliation Optimization** - Improve reconciliation worker efficiency through better sharding
3. **Dependency Cache** - Reduce Redis load through shared caching (optional)

### Success Criteria
- Zero false-positive coordination failures detected
- 50%+ reduction in reconciliation worker Redis operations
- 30%+ reduction in dependency worker Redis reads (with cache)
- All enhancements work in both single-instance and multi-instance modes

---

## 1. Health Checks for Coordination Mechanisms

### 1.1 Overview

**Problem**: Currently, coordination mechanism failures (leader election, sharding, service registry) fail silently or only log errors. Operators have no visibility into coordination health.

**Solution**: Implement periodic health checks that validate coordination mechanisms and expose metrics/alerts.

### 1.2 Coordination Mechanisms to Monitor

| Mechanism | Location | Failure Mode | Impact |
|-----------|----------|--------------|--------|
| **Leader Election** | TimerWorker, SignalWorker, LokiExporter | Lost leadership, split brain | Duplicate processing, data corruption |
| **Sharding Config** | startup validation | Config mismatch between instances | Workflow corruption |
| **Service Registry** | SmartProcessManager | Stale registrations, missing heartbeats | Failed service discovery |
| **Redis Streams** | All workers | Consumer group desync, lag buildup | Processing delays |

### 1.3 Proposed Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Health Check System                    │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────────┐      ┌──────────────────┐        │
│  │  Health Monitor  │◄────►│  Redis Metrics   │        │
│  │   (New Worker)   │      │   Collector      │        │
│  └────────┬─────────┘      └──────────────────┘        │
│           │                                              │
│           ├──► Leader Election Health                   │
│           ├──► Service Registry Health                  │
│           ├──► Stream Consumer Health                   │
│           └──► Coordination Config Health               │
│                                                           │
│  Output:                                                 │
│    • Prometheus Metrics                                  │
│    • Health API Endpoint (/health/coordination)         │
│    • Alerting (optional webhook)                        │
└─────────────────────────────────────────────────────────┘
```

### 1.4 Implementation Details

#### 1.4.1 Health Check Worker

**File**: `src/gleitzeit/workers/health_monitor_worker.py`

```python
class HealthMonitorWorker:
    """Monitors coordination mechanism health across instances"""

    def __init__(self, redis_url: str, check_interval: int = 30):
        self.redis_url = redis_url
        self.check_interval = check_interval
        self.checks = [
            LeaderElectionHealthCheck(),
            ServiceRegistryHealthCheck(),
            StreamConsumerHealthCheck(),
            ShardingConfigHealthCheck()
        ]

    async def run(self):
        """Main health check loop"""
        while True:
            for check in self.checks:
                result = await check.execute(self.redis)
                await self.record_metric(check.name, result)

                if not result.healthy:
                    await self.handle_unhealthy(check.name, result)

            await asyncio.sleep(self.check_interval)
```

#### 1.4.2 Leader Election Health Check

**Check Logic**:
```python
class LeaderElectionHealthCheck:
    """Validates leader election mechanism health"""

    async def execute(self, redis) -> HealthResult:
        issues = []

        # Check 1: Ensure leaders exist for all leader-elected services
        for service in ['timer', 'signal', 'loki_exporter']:
            leader_key = f"leader:{service}"
            leader = await redis.get(leader_key)

            if not leader:
                issues.append(f"No leader for {service}")
            else:
                # Check 2: Validate leader instance is still registered
                instance_key = f"instance:{leader}"
                if not await redis.exists(instance_key):
                    issues.append(f"Leader {leader} for {service} not registered")

        # Check 3: Detect split brain (multiple leaders due to Redis partition)
        for service in ['timer', 'signal', 'loki_exporter']:
            active_count = await self._count_active_leaders(redis, service)
            if active_count > 1:
                issues.append(f"Split brain detected: {active_count} leaders for {service}")

        return HealthResult(
            healthy=len(issues) == 0,
            issues=issues,
            metadata={'timestamp': time.time()}
        )
```

#### 1.4.3 Service Registry Health Check

**Check Logic**:
```python
class ServiceRegistryHealthCheck:
    """Validates service registry health"""

    async def execute(self, redis) -> HealthResult:
        issues = []

        # Check 1: Find services with expired heartbeats
        services = await redis.hgetall("global:service:registry")
        current_time = time.time()

        for service_name, service_data in services.items():
            data = json.loads(service_data)
            last_heartbeat = data.get('last_heartbeat', 0)

            if current_time - last_heartbeat > 90:  # 90s = 1.5x TTL
                issues.append(f"Stale heartbeat for {service_name}")

        # Check 2: Validate registered PIDs exist
        for service_name, service_data in services.items():
            data = json.loads(service_data)
            pid = data.get('pid')

            if pid and not psutil.pid_exists(pid):
                issues.append(f"Service {service_name} PID {pid} not found")

        # Check 3: Detect duplicate service registrations (same service, different instances)
        service_counts = {}
        for service_name in services.keys():
            base_name = service_name.split('-')[0]  # Remove instance suffix
            service_counts[base_name] = service_counts.get(base_name, 0) + 1

        for service, count in service_counts.items():
            if count > 1 and service in ['api', 'ui']:  # Non-sharded services
                issues.append(f"Duplicate registration for {service}: {count} instances")

        return HealthResult(
            healthy=len(issues) == 0,
            issues=issues,
            metadata={'service_count': len(services)}
        )
```

#### 1.4.4 Stream Consumer Health Check

**Check Logic**:
```python
class StreamConsumerHealthCheck:
    """Validates Redis stream consumer health"""

    async def execute(self, redis) -> HealthResult:
        issues = []

        # Get all workflow streams (16 shards)
        for shard in range(16):
            stream_name = f"workflow:shard:{shard}"

            # Check 1: Measure consumer lag
            info = await redis.xinfo_groups(stream_name)
            for group_info in info:
                group_name = group_info['name']
                lag = group_info.get('lag', 0)

                if lag > 1000:  # Threshold: 1000 pending messages
                    issues.append(f"High lag on {stream_name}/{group_name}: {lag}")

            # Check 2: Detect idle consumers
            consumers = await redis.xinfo_consumers(stream_name, "task_execution")
            current_time = time.time()

            for consumer in consumers:
                idle_ms = consumer.get('idle', 0)
                if idle_ms > 300000:  # 5 minutes idle
                    issues.append(f"Idle consumer {consumer['name']} on {stream_name}")

        # Check 3: Check for pending messages stuck in PEL (Pending Entry List)
        for shard in range(16):
            stream_name = f"workflow:shard:{shard}"
            pending = await redis.xpending(stream_name, "task_execution")

            if pending and pending['pending'] > 100:
                issues.append(f"High pending count on {stream_name}: {pending['pending']}")

        return HealthResult(
            healthy=len(issues) == 0,
            issues=issues,
            metadata={'total_shards': 16}
        )
```

#### 1.4.5 Sharding Config Health Check

**Check Logic**:
```python
class ShardingConfigHealthCheck:
    """Validates sharding configuration consistency"""

    async def execute(self, redis) -> HealthResult:
        issues = []

        # Check 1: Validate stored config exists
        stored_shards = await redis.get("global:config:num_shards")
        if not stored_shards:
            issues.append("No sharding configuration stored in Redis")
            return HealthResult(healthy=False, issues=issues)

        # Check 2: Compare against local configuration
        from gleitzeit.core.sharding import default_sharding
        local_shards = default_sharding.num_shards

        if int(stored_shards) != local_shards:
            issues.append(
                f"Config mismatch: Redis={stored_shards}, Local={local_shards}"
            )

        # Check 3: Validate all 16 shards have active consumers
        for shard in range(int(stored_shards)):
            stream_name = f"workflow:shard:{shard}"
            groups = await redis.xinfo_groups(stream_name)

            if not groups:
                issues.append(f"No consumer groups on {stream_name}")

        return HealthResult(
            healthy=len(issues) == 0,
            issues=issues,
            metadata={'num_shards': stored_shards}
        )
```

#### 1.4.6 Health API Endpoint

**File**: `src/gleitzeit/api/routes/health.py`

```python
@router.get("/health/coordination")
async def get_coordination_health(redis: Redis = Depends(get_redis)):
    """Get coordination mechanism health status"""

    # Retrieve health metrics from Redis
    health_data = await redis.hgetall("global:health:coordination")

    if not health_data:
        return {
            "status": "unknown",
            "message": "Health monitor not running",
            "checks": {}
        }

    all_healthy = True
    checks = {}

    for check_name, check_data in health_data.items():
        data = json.loads(check_data)
        checks[check_name] = data

        if not data.get('healthy', True):
            all_healthy = False

    return {
        "status": "healthy" if all_healthy else "unhealthy",
        "checks": checks,
        "timestamp": time.time()
    }
```

### 1.5 Metrics & Alerting

#### Prometheus Metrics

```python
# Health check metrics
coordination_health = Gauge(
    'gleitzeit_coordination_health',
    'Coordination mechanism health (1=healthy, 0=unhealthy)',
    ['mechanism']
)

leader_election_leaders = Gauge(
    'gleitzeit_leader_election_leaders',
    'Number of active leaders per service',
    ['service']
)

service_registry_services = Gauge(
    'gleitzeit_service_registry_services',
    'Number of registered services'
)

stream_consumer_lag = Gauge(
    'gleitzeit_stream_consumer_lag',
    'Consumer lag per shard',
    ['shard', 'consumer_group']
)
```

#### Alert Rules (Prometheus AlertManager)

```yaml
groups:
- name: gleitzeit_coordination
  rules:
  - alert: LeaderElectionSplitBrain
    expr: gleitzeit_leader_election_leaders > 1
    for: 1m
    annotations:
      summary: "Split brain detected in leader election"

  - alert: ServiceRegistryStale
    expr: gleitzeit_coordination_health{mechanism="service_registry"} == 0
    for: 5m
    annotations:
      summary: "Stale services in registry"

  - alert: StreamConsumerLagHigh
    expr: gleitzeit_stream_consumer_lag > 1000
    for: 10m
    annotations:
      summary: "High consumer lag on workflow stream"
```

### 1.6 Configuration

**gleitzeit.yaml additions**:
```yaml
health_monitoring:
  enabled: true
  check_interval: 30  # seconds
  endpoints:
    coordination: true

  thresholds:
    stream_lag_warning: 500
    stream_lag_critical: 1000
    heartbeat_stale_seconds: 90
    consumer_idle_seconds: 300

  alerting:
    enabled: false  # Optional webhook alerting
    webhook_url: "https://hooks.slack.com/..."
```

### 1.7 Testing Strategy

1. **Unit Tests**: Mock Redis responses for each health check
2. **Integration Tests**:
   - Start 2 instances, kill leader, verify detection
   - Introduce stream lag, verify threshold alerts
   - Corrupt service registry, verify detection
3. **Chaos Testing**:
   - Network partition simulation
   - Redis connection failures
   - Process crashes

### 1.8 Implementation Effort

- **Estimated Time**: 4-6 hours
- **Priority**: HIGH (improves operational confidence)
- **Dependencies**: None (uses existing infrastructure)

---

## 2. Optimize Reconciliation Worker Sharding

### 2.1 Overview

**Problem**: The reconciliation worker currently processes all workflows across all 16 shards, leading to redundant work and high Redis load when multiple instances run.

**Current Behavior**:
```
Instance A: Reconciles shards 0-15 (all workflows)
Instance B: Reconciles shards 0-15 (all workflows) ← DUPLICATE WORK
```

**Solution**: Shard the reconciliation worker so each instance handles a subset of workflow shards.

### 2.2 Current Implementation Analysis

**File**: `src/gleitzeit/workers/reconciliation_worker.py`

```python
async def reconcile_all_workflows(self):
    """Current: Processes ALL workflows regardless of shard"""
    workflows = await self.redis.keys("workflow:*:state")

    for workflow_key in workflows:
        workflow_id = workflow_key.split(":")[1]
        await self.reconcile_workflow(workflow_id)
```

**Problem**:
- No coordination between instances
- Each instance scans all 16 shards
- Duplicate reconciliation attempts (prevented by locks but wasteful)

### 2.3 Proposed Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Reconciliation Worker Sharding              │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  Instance A (assigned shards 0-7)                        │
│  ┌──────────────────────────────────────────┐           │
│  │  Reconciliation Worker                   │           │
│  │  • Scans shards 0-7 only                 │           │
│  │  • Claims ownership via Redis key        │           │
│  └──────────────────────────────────────────┘           │
│                                                           │
│  Instance B (assigned shards 8-15)                       │
│  ┌──────────────────────────────────────────┐           │
│  │  Reconciliation Worker                   │           │
│  │  • Scans shards 8-15 only                │           │
│  │  • Claims ownership via Redis key        │           │
│  └──────────────────────────────────────────┘           │
│                                                           │
│  Shard Assignment Strategy:                              │
│    • Consistent hashing based on instance ID            │
│    • Automatic rebalancing on instance add/remove      │
│    • Overlap period during transitions (safety)        │
└─────────────────────────────────────────────────────────┘
```

### 2.4 Implementation Details

#### 2.4.1 Shard Assignment Algorithm

**File**: `src/gleitzeit/core/reconciliation_sharding.py`

```python
class ReconciliationShardAssignment:
    """Manages shard assignment for reconciliation workers"""

    def __init__(self, redis, total_shards: int = 16):
        self.redis = redis
        self.total_shards = total_shards
        self.instance_id = get_current_instance().instance_id
        self.assignment_key = "global:reconciliation:shard_assignment"
        self.heartbeat_interval = 30  # seconds

    async def get_assigned_shards(self) -> List[int]:
        """Get shards assigned to this instance"""

        # Step 1: Register this instance
        await self._register_instance()

        # Step 2: Get all active instances
        active_instances = await self._get_active_instances()

        # Step 3: Calculate shard distribution
        shards_per_instance = self.total_shards // len(active_instances)
        remainder = self.total_shards % len(active_instances)

        # Step 4: Sort instances for consistent ordering
        sorted_instances = sorted(active_instances)
        instance_index = sorted_instances.index(self.instance_id)

        # Step 5: Assign shards
        start_shard = instance_index * shards_per_instance
        end_shard = start_shard + shards_per_instance

        # Distribute remainder shards to first N instances
        if instance_index < remainder:
            start_shard += instance_index
            end_shard += instance_index + 1
        else:
            start_shard += remainder
            end_shard += remainder

        assigned_shards = list(range(start_shard, end_shard))

        logger.info(f"Reconciliation worker assigned shards: {assigned_shards}")
        return assigned_shards

    async def _register_instance(self):
        """Register this instance as active reconciliation worker"""
        key = f"{self.assignment_key}:{self.instance_id}"
        await self.redis.setex(
            key,
            self.heartbeat_interval * 2,  # 2x heartbeat for safety
            json.dumps({
                'instance_id': self.instance_id,
                'timestamp': time.time()
            })
        )

    async def _get_active_instances(self) -> List[str]:
        """Get all active reconciliation worker instances"""
        pattern = f"{self.assignment_key}:*"
        keys = await self.redis.keys(pattern)

        instances = []
        for key in keys:
            instance_id = key.split(":")[-1]
            instances.append(instance_id)

        return instances

    async def start_heartbeat(self):
        """Maintain instance registration via periodic heartbeat"""
        while True:
            await self._register_instance()
            await asyncio.sleep(self.heartbeat_interval)
```

#### 2.4.2 Modified Reconciliation Worker

**File**: `src/gleitzeit/workers/reconciliation_worker.py`

```python
class ReconciliationWorker:
    def __init__(self, redis_url: str, interval: int = 60):
        self.redis_url = redis_url
        self.interval = interval
        self.shard_manager = ReconciliationShardAssignment(redis)
        self.assigned_shards = []

    async def initialize(self):
        """Initialize worker and get shard assignment"""
        self.redis = await aioredis.from_url(self.redis_url)

        # Start heartbeat task
        asyncio.create_task(self.shard_manager.start_heartbeat())

        # Get initial shard assignment
        self.assigned_shards = await self.shard_manager.get_assigned_shards()

    async def reconcile_all_workflows(self):
        """Reconcile workflows only in assigned shards"""

        # Refresh shard assignment periodically
        self.assigned_shards = await self.shard_manager.get_assigned_shards()

        # Scan only assigned shards
        for shard in self.assigned_shards:
            await self._reconcile_shard(shard)

    async def _reconcile_shard(self, shard: int):
        """Reconcile all workflows in a specific shard"""

        # Pattern: workflow:{workflow_id}:state
        # Extract workflows belonging to this shard
        all_workflows = await self.redis.keys("workflow:*:state")

        for workflow_key in all_workflows:
            workflow_id = workflow_key.decode().split(":")[1]

            # Check if workflow belongs to this shard
            from gleitzeit.core.sharding import default_sharding
            workflow_shard = default_sharding.get_shard(workflow_id)

            if workflow_shard == shard:
                await self.reconcile_workflow(workflow_id)
```

### 2.5 Rebalancing Strategy

When instances are added/removed, shards must be reassigned:

```python
class ReconciliationShardAssignment:
    async def detect_rebalance(self) -> bool:
        """Detect if rebalancing is needed"""
        current_instances = await self._get_active_instances()

        if len(current_instances) != len(self._last_known_instances):
            logger.info(f"Instance count changed: {len(self._last_known_instances)} → {len(current_instances)}")
            return True

        return False

    async def rebalance(self):
        """Handle shard rebalancing during instance changes"""

        # Step 1: Get new assignment
        new_shards = await self.get_assigned_shards()

        # Step 2: Identify shards to hand off
        removed_shards = set(self.assigned_shards) - set(new_shards)
        added_shards = set(new_shards) - set(self.assigned_shards)

        logger.info(f"Rebalancing: removed={removed_shards}, added={added_shards}")

        # Step 3: Complete in-flight reconciliations on removed shards
        for shard in removed_shards:
            await self._wait_for_shard_completion(shard)

        # Step 4: Update assignment
        self.assigned_shards = new_shards
```

### 2.6 Graceful Degradation

**Overlap Period**: During rebalancing, both old and new owners may process a shard briefly:

```python
async def _reconcile_shard(self, shard: int):
    """Reconcile shard with ownership check"""

    # Acquire lightweight lock before processing
    lock_key = f"reconciliation:shard:{shard}:lock"
    lock = await self.redis.set(
        lock_key,
        self.instance_id,
        nx=True,  # Only set if not exists
        ex=self.interval + 10  # Expiry slightly longer than interval
    )

    if not lock:
        # Another instance is handling this shard
        return

    try:
        # Process workflows in shard
        await self._process_shard_workflows(shard)
    finally:
        # Release lock only if we still own it
        current_owner = await self.redis.get(lock_key)
        if current_owner == self.instance_id:
            await self.redis.delete(lock_key)
```

### 2.7 Metrics & Observability

```python
# Metrics
reconciliation_assigned_shards = Gauge(
    'gleitzeit_reconciliation_assigned_shards',
    'Number of shards assigned to this instance'
)

reconciliation_workflows_processed = Counter(
    'gleitzeit_reconciliation_workflows_processed',
    'Workflows reconciled by shard',
    ['shard']
)

reconciliation_rebalance_count = Counter(
    'gleitzeit_reconciliation_rebalances',
    'Number of shard rebalancing events'
)
```

### 2.8 Expected Performance Improvement

**Current State** (2 instances, 1000 workflows):
- Instance A: Scans 1000 workflows, reconciles ~500 (locks prevent duplicates)
- Instance B: Scans 1000 workflows, reconciles ~500 (locks prevent duplicates)
- **Total Redis operations**: 2000 scans + 1000 reconciliations = 3000 ops

**With Sharding** (2 instances, 1000 workflows):
- Instance A: Scans 500 workflows (shards 0-7), reconciles 500
- Instance B: Scans 500 workflows (shards 8-15), reconciles 500
- **Total Redis operations**: 1000 scans + 1000 reconciliations = 2000 ops

**Reduction**: 33% fewer Redis operations

### 2.9 Configuration

**gleitzeit.yaml additions**:
```yaml
reconciliation:
  sharding:
    enabled: true
    rebalance_delay: 10  # seconds to wait before rebalancing
    overlap_period: 30  # seconds both instances process during transition
```

### 2.10 Testing Strategy

1. **Unit Tests**: Shard assignment algorithm with various instance counts
2. **Integration Tests**:
   - Start 1 instance, verify all 16 shards assigned
   - Start 2 instances, verify 8 shards each
   - Start 3 instances, verify balanced distribution
   - Kill 1 instance, verify rebalancing
3. **Load Testing**: 10,000 workflows across 4 instances

### 2.11 Implementation Effort

- **Estimated Time**: 3-5 hours
- **Priority**: MEDIUM (performance optimization)
- **Dependencies**: Phase 1 complete

---

## 3. Implement Shared Cache for Dependency Worker (Optional)

### 3.1 Overview

**Problem**: The dependency worker makes frequent Redis reads to check dependency states. With multiple instances, these reads are duplicated across workers.

**Current Behavior**:
```
Instance A: Reads dep_1, dep_2, dep_3 from Redis
Instance B: Reads dep_1, dep_2, dep_3 from Redis  ← DUPLICATE READS
```

**Solution**: Implement an in-memory cache with Redis pub/sub for invalidation.

### 3.2 Current Implementation Analysis

**File**: `src/gleitzeit/workers/dependency_worker.py`

```python
async def check_dependencies(self, task_id: str):
    """Current: Reads dependency state directly from Redis"""
    deps = await self.redis.smembers(f"task:{task_id}:dependencies")

    for dep_id in deps:
        dep_state = await self.redis.hget(f"task:{dep_id}", "state")
        # ... process dependency
```

**Problem**:
- Every dependency check hits Redis
- No caching across requests
- High read load on Redis

### 3.3 Proposed Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Dependency Worker with Cache                │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌────────────────────────────────────────────────┐     │
│  │  Dependency Worker                             │     │
│  │                                                 │     │
│  │  ┌──────────────────────┐                      │     │
│  │  │  In-Memory Cache     │                      │     │
│  │  │  (LRU, TTL-based)    │◄────┐                │     │
│  │  └──────────────────────┘     │                │     │
│  │                                │                │     │
│  │  ┌──────────────────────┐     │                │     │
│  │  │  Cache Invalidator   │◄────┘                │     │
│  │  │  (Redis Pub/Sub)     │                      │     │
│  │  └──────────────────────┘                      │     │
│  └────────────────────────────────────────────────┘     │
│           ▲                          ▲                   │
│           │ Read miss                │ Invalidation      │
│           ▼                          │                   │
│  ┌──────────────────┐     ┌──────────────────┐          │
│  │      Redis       │────►│  Pub/Sub Channel │          │
│  │   (Source of     │     │  "cache:invalid" │          │
│  │    Truth)        │     └──────────────────┘          │
│  └──────────────────┘                                    │
└─────────────────────────────────────────────────────────┘
```

### 3.4 Implementation Details

#### 3.4.1 Cache Layer

**File**: `src/gleitzeit/core/dependency_cache.py`

```python
from cachetools import TTLCache, LRUCache
import asyncio
from typing import Optional, Dict, Any

class DependencyCache:
    """In-memory cache for dependency states with Redis pub/sub invalidation"""

    def __init__(
        self,
        redis,
        max_size: int = 10000,
        ttl: int = 300,  # 5 minutes
        enable_invalidation: bool = True
    ):
        self.redis = redis

        # Dual-layer cache: TTL for freshness + LRU for size limit
        self.cache = TTLCache(maxsize=max_size, ttl=ttl)
        self.enable_invalidation = enable_invalidation

        # Metrics
        self.hits = 0
        self.misses = 0
        self.invalidations = 0

        # Start invalidation listener
        if self.enable_invalidation:
            asyncio.create_task(self._listen_for_invalidations())

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache or fetch from Redis"""

        # Check cache first
        if key in self.cache:
            self.hits += 1
            return self.cache[key]

        # Cache miss - fetch from Redis
        self.misses += 1
        value = await self._fetch_from_redis(key)

        if value is not None:
            self.cache[key] = value

        return value

    async def _fetch_from_redis(self, key: str) -> Optional[Any]:
        """Fetch value from Redis"""

        # Handle different key patterns
        if key.startswith("task:"):
            # Full task state
            return await self.redis.hgetall(key)
        else:
            # Single value
            return await self.redis.get(key)

    async def invalidate(self, key: str):
        """Invalidate cache entry locally"""
        if key in self.cache:
            del self.cache[key]
            self.invalidations += 1

    async def publish_invalidation(self, key: str):
        """Publish invalidation to all instances"""
        await self.redis.publish(
            "cache:invalidation:dependency",
            json.dumps({'key': key, 'timestamp': time.time()})
        )

    async def _listen_for_invalidations(self):
        """Listen for invalidation messages from other instances"""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("cache:invalidation:dependency")

        async for message in pubsub.listen():
            if message['type'] == 'message':
                data = json.loads(message['data'])
                await self.invalidate(data['key'])

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0

        return {
            'size': len(self.cache),
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': f"{hit_rate:.2f}%",
            'invalidations': self.invalidations
        }
```

#### 3.4.2 Modified Dependency Worker

**File**: `src/gleitzeit/workers/dependency_worker.py`

```python
class DependencyWorker:
    def __init__(self, redis_url: str, cache_enabled: bool = True):
        self.redis_url = redis_url
        self.cache_enabled = cache_enabled
        self.cache = None

    async def initialize(self):
        """Initialize worker with cache"""
        self.redis = await aioredis.from_url(self.redis_url)

        if self.cache_enabled:
            self.cache = DependencyCache(
                self.redis,
                max_size=10000,
                ttl=300,  # 5 minutes
                enable_invalidation=True
            )
            logger.info("Dependency cache enabled")

    async def check_dependencies(self, task_id: str):
        """Check dependencies with caching"""
        deps = await self.redis.smembers(f"task:{task_id}:dependencies")

        all_complete = True
        for dep_id in deps:
            # Use cache if enabled
            if self.cache_enabled:
                dep_state = await self.cache.get(f"task:{dep_id}:state")
            else:
                dep_state = await self.redis.hget(f"task:{dep_id}", "state")

            if dep_state != "completed":
                all_complete = False
                break

        return all_complete

    async def update_task_state(self, task_id: str, new_state: str):
        """Update task state and invalidate cache"""
        await self.redis.hset(f"task:{task_id}", "state", new_state)

        # Invalidate cache across all instances
        if self.cache_enabled:
            await self.cache.publish_invalidation(f"task:{task_id}:state")
```

### 3.5 Cache Invalidation Strategies

#### Strategy 1: Write-Through (Implemented Above)
- Every write publishes invalidation
- Guarantees consistency
- Higher pub/sub traffic

#### Strategy 2: TTL-Only (Simpler)
- No pub/sub invalidation
- Relies purely on TTL expiration
- Risk of stale reads within TTL window

#### Strategy 3: Hybrid
- Use TTL for normal operations
- Publish invalidation only for critical state changes (e.g., task completion)

**Recommendation**: Start with Strategy 1 (write-through) for correctness, measure pub/sub overhead, downgrade to Strategy 3 if needed.

### 3.6 Cache Consistency Guarantees

**Problem**: Cache may become inconsistent if:
1. Invalidation message is lost (Redis network partition)
2. Worker crashes before processing invalidation
3. Clock skew causes TTL issues

**Mitigations**:
1. **TTL Safety Net**: Cache entries expire after 5 minutes regardless of invalidation
2. **Versioning**: Include version number in cached data
   ```python
   cache_entry = {
       'data': task_state,
       'version': await redis.get(f"task:{task_id}:version"),
       'timestamp': time.time()
   }
   ```
3. **Fallback Reads**: On critical operations, bypass cache and read from Redis

### 3.7 Metrics & Observability

```python
# Cache metrics
dependency_cache_hits = Counter(
    'gleitzeit_dependency_cache_hits',
    'Cache hits'
)

dependency_cache_misses = Counter(
    'gleitzeit_dependency_cache_misses',
    'Cache misses'
)

dependency_cache_size = Gauge(
    'gleitzeit_dependency_cache_size',
    'Current cache size'
)

dependency_cache_invalidations = Counter(
    'gleitzeit_dependency_cache_invalidations',
    'Cache invalidation events'
)
```

### 3.8 Expected Performance Improvement

**Assumptions**:
- 10,000 active tasks
- Each task checked 10 times before dependencies complete
- Cache hit rate: 70%
- 2 worker instances

**Current State**:
- Total dependency checks: 10,000 × 10 = 100,000
- Redis reads: 100,000 (all checks hit Redis)

**With Cache**:
- Cache hits: 70,000 (no Redis read)
- Cache misses: 30,000 (fetch from Redis)
- **Redis read reduction**: 70%

**Trade-offs**:
- Memory usage: ~10MB per instance (10,000 entries × ~1KB each)
- Pub/sub messages: ~10,000 invalidations per batch

### 3.9 Configuration

**gleitzeit.yaml additions**:
```yaml
dependency_worker:
  cache:
    enabled: true
    max_size: 10000
    ttl: 300  # seconds
    invalidation_strategy: "write_through"  # write_through | ttl_only | hybrid
```

### 3.10 Testing Strategy

1. **Unit Tests**: Cache hit/miss logic, invalidation propagation
2. **Integration Tests**:
   - Write on instance A, read on instance B (verify invalidation)
   - Measure cache hit rate with realistic workload
   - Test cache consistency under network partition
3. **Performance Tests**:
   - Benchmark Redis load with/without cache
   - Measure memory overhead
   - Verify pub/sub throughput

### 3.11 When NOT to Use Cache

The cache should be **disabled** or **bypassed** for:
1. **Critical operations**: Final task completion checks
2. **Low-frequency reads**: Tasks checked only once
3. **High write rates**: Cache overhead exceeds benefit
4. **Strict consistency requirements**: Cannot tolerate stale reads

**Example**:
```python
async def final_completion_check(self, task_id: str) -> bool:
    """Always read from Redis for final checks"""
    # Bypass cache for critical decisions
    return await self.redis.hget(f"task:{task_id}", "state") == "completed"
```

### 3.12 Implementation Effort

- **Estimated Time**: 4-6 hours
- **Priority**: LOW (optional optimization)
- **Dependencies**: None (can be implemented independently)

---

## 4. Implementation Roadmap

### 4.1 Recommended Order

1. **Health Checks** (HIGH priority)
   - Provides immediate operational value
   - No risk to existing functionality
   - Enables safe deployment of remaining features

2. **Reconciliation Sharding** (MEDIUM priority)
   - Clear performance win
   - Moderate complexity
   - Builds on Phase 1 sharding infrastructure

3. **Dependency Cache** (LOW priority, optional)
   - Highest complexity
   - Requires careful consistency analysis
   - Should only be implemented if Redis load is proven bottleneck

### 4.2 Timeline

| Feature | Duration | Dependencies | Start |
|---------|----------|--------------|-------|
| Health Checks | 4-6 hours | None | Immediately |
| Reconciliation Sharding | 3-5 hours | Health checks (for monitoring) | After health checks |
| Dependency Cache | 4-6 hours | None (optional) | After measuring Redis load |

**Total Estimated Time**: 11-17 hours (excluding cache)

### 4.3 Success Metrics

Track these metrics before/after each feature:

| Metric | Baseline | Target |
|--------|----------|--------|
| Coordination failure detection time | N/A (manual) | < 1 minute (automated) |
| Reconciliation Redis ops (2 instances) | 3000/min | < 2000/min (-33%) |
| Dependency Redis reads (2 instances) | 100,000/hour | < 30,000/hour (-70%, with cache) |
| False positive alerts | N/A | < 1/week |

---

## 5. Risk Assessment

### 5.1 Health Checks

**Risks**:
- False positive alerts causing alert fatigue
- Health check overhead impacting performance

**Mitigations**:
- Tune thresholds based on production data
- Make health checks lightweight (< 100ms each)
- Implement rate limiting on alerts

### 5.2 Reconciliation Sharding

**Risks**:
- Rebalancing causing temporary coverage gaps
- Bugs in shard assignment leading to missed workflows

**Mitigations**:
- Overlap period during rebalancing
- Shard ownership locks prevent duplicates
- Comprehensive testing with instance churn

### 5.3 Dependency Cache

**Risks**:
- Cache inconsistency leading to incorrect dependency resolution
- Memory exhaustion with large caches
- Pub/sub message loss during network issues

**Mitigations**:
- TTL-based expiration as safety net
- LRU eviction to cap memory usage
- Bypass cache for critical operations
- Start with conservative TTL (5 minutes)

---

## 6. Alternatives Considered

### 6.1 Health Checks Alternative: External Monitoring

**Approach**: Use external tools (Datadog, New Relic) instead of built-in health checks

**Pros**:
- No development effort
- Mature alerting infrastructure

**Cons**:
- Cannot check Gleitzeit-specific coordination mechanisms
- Higher cost
- External dependency

**Decision**: Implement built-in health checks for Gleitzeit-specific coordination, use external monitoring for infrastructure metrics

### 6.2 Reconciliation Alternative: Sticky Assignment

**Approach**: Assign workflows to instances at creation time, never rebalance

**Pros**:
- Simpler implementation
- No rebalancing complexity

**Cons**:
- Uneven load distribution
- Instance failure requires manual reassignment

**Decision**: Use dynamic shard assignment for better load distribution and automatic failover

### 6.3 Cache Alternative: Redis Cluster Read Replicas

**Approach**: Use Redis read replicas to distribute read load

**Pros**:
- No application code changes
- Eventual consistency handled by Redis

**Cons**:
- Infrastructure complexity
- Higher cost
- Replication lag

**Decision**: Implement application-level cache first (cheaper, more control), consider Redis replicas if cache insufficient

---

## 7. Documentation Requirements

### 7.1 Operator Guide

Create `/docs/HORIZONTAL_SCALING_OPERATIONS.md`:
- How to interpret health check alerts
- Troubleshooting coordination failures
- Monitoring dashboards (Grafana templates)
- Runbook for common issues

### 7.2 Configuration Reference

Update `/docs/CONFIGURATION.md`:
- All new configuration options
- Recommended values for different deployment sizes
- Performance tuning guide

### 7.3 Architecture Documentation

Update `/docs/ARCHITECTURE.md`:
- Coordination mechanism diagrams
- Sharding strategy explanation
- Cache consistency model

---

## 8. Future Enhancements (Phase 3+)

### 8.1 Dynamic Shard Count

Allow changing `num_shards` without full cluster restart:
- Migration path from N to M shards
- Workflow rehashing strategy
- Zero-downtime shard count changes

### 8.2 Cross-Region Deployment

Support for multi-region Gleitzeit clusters:
- Region-aware service discovery
- Cross-region replication for workflows
- Latency-optimized routing

### 8.3 Auto-Scaling

Automatically scale worker instances based on load:
- Queue depth monitoring
- Instance spin-up/down automation
- Integration with Kubernetes HPA

---

## 9. Appendix

### 9.1 Related Documents

- [HORIZONTAL_SCALING_AUDIT.md](HORIZONTAL_SCALING_AUDIT.md) - Phase 1 audit and fixes
- [DEPLOYMENT.md](DEPLOYMENT.md) - Deployment patterns (to be created)
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture overview

### 9.2 References

- Redis Leader Election: https://redis.io/docs/manual/patterns/distributed-locks/
- Consistent Hashing: https://en.wikipedia.org/wiki/Consistent_hashing
- Cache Invalidation Patterns: https://martinfowler.com/bliki/TwoHardThings.html

### 9.3 Glossary

- **Leader Election**: Process where one instance is chosen to perform singleton work
- **Sharding**: Partitioning data across multiple streams/instances
- **Reconciliation**: Background process that fixes inconsistent workflow states
- **Pub/Sub**: Redis publish/subscribe messaging for cache invalidation
- **TTL**: Time-To-Live, automatic expiration of cached data
- **Circuit Breaker**: Pattern that stops cascading failures

---

**Document Status**: Draft for Review
**Next Steps**: Review with team, prioritize features, begin implementation
