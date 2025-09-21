# Horizontal Scaling Implementation Plan for Gleitzeit

## Executive Summary

This plan outlines the systematic transformation of Gleitzeit from a stateful, single-instance system to a stateless, horizontally scalable distributed system. The implementation is divided into 4 phases with clear deliverables and success criteria.

**Timeline**: 8-12 weeks for full implementation
**Complexity**: High - Requires fundamental architectural changes
**Risk**: High if not implemented systematically

## Current State Assessment

- **Scaling Capability**: 0/10
- **Stateless Violations**: 36+ files with loops, 69+ state variables
- **Blocking Issues**: Consumer groups, persistent loops, singletons
- **Dead Consumers**: 24+ accumulated, causing workflow hangs

## Phase 1: Critical Fixes (Week 1-2)
**Goal**: Stop the bleeding - Fix issues preventing basic operation

### 1.1 Dead Consumer Cleanup
```python
# src/gleitzeit/events/consumer_lifecycle.py (NEW)
class ConsumerLifecycle:
    """Manages consumer registration with TTL"""

    async def register_consumer(self, consumer_id: str, ttl: int = 60):
        """Register consumer with automatic expiry"""
        await self.redis.setex(
            f"consumer:{consumer_id}:alive",
            ttl,
            json.dumps({"started": time.time(), "pid": os.getpid()})
        )

    async def heartbeat(self, consumer_id: str):
        """Extend consumer TTL on activity"""
        await self.redis.expire(f"consumer:{consumer_id}:alive", 60)

    async def cleanup_dead_consumers(self):
        """Remove consumers without heartbeat"""
        # Check all consumers in group
        for consumer in await self.get_consumers():
            if not await self.redis.exists(f"consumer:{consumer.id}:alive"):
                await self.remove_consumer(consumer.id)
```

**Files to Modify**:
- `src/gleitzeit/events/stream_event_bus.py` - Add consumer lifecycle
- `src/gleitzeit/system/reconciliation_service.py` - Add dead consumer cleanup

### 1.2 Idempotency Framework
```python
# src/gleitzeit/core/idempotency.py (NEW)
class IdempotencyChecker:
    """Ensures tasks can be safely rerun"""

    async def can_rerun(self, task_id: str) -> bool:
        task = await self.persistence.get_task(task_id)

        # Already completed
        if task.status == TaskStatus.COMPLETED:
            return False

        # Check if still being processed
        if task.status == TaskStatus.EXECUTING:
            executor_alive = await self.check_executor_alive(task.executor_id)
            if executor_alive:
                return False

        # Check idempotency flag
        if not task.metadata.get('idempotent', False):
            if task.attempts > 0:
                logger.warning(f"Cannot rerun non-idempotent task {task_id}")
                return False

        return True
```

**Files to Modify**:
- `src/gleitzeit/core/task_executor.py` - Check before rerun
- `src/gleitzeit/system/reconciliation_service.py` - Add idempotency checks

### 1.3 Emergency Loop Removal
Replace the most critical loops with event-driven patterns:

```python
# BEFORE (stateful)
async def _consume_events(self):
    while self._running:
        messages = await self.redis.xreadgroup(...)
        await self.process(messages)
        await asyncio.sleep(0.1)

# AFTER (stateless)
async def consume_batch(self, max_messages: int = 100):
    """Process one batch of messages and exit"""
    messages = await self.redis.xreadgroup(..., count=max_messages)
    await self.process(messages)
    # Exit - no loop
```

**Priority Files**:
1. `src/gleitzeit/events/stream_event_bus.py`
2. `src/gleitzeit/system/reconciliation_service.py`
3. `src/gleitzeit/core/task_orchestrator.py`

## Phase 2: Stateless Conversion (Week 3-5)
**Goal**: Remove all stateful patterns

### 2.1 Eliminate All Loops
Convert 36+ files from loops to event-driven:

```python
# src/gleitzeit/events/stateless_consumer.py (NEW)
class StatelessEventConsumer:
    """Event-driven consumer without loops"""

    async def process_events(self, trigger: dict):
        """Called by external trigger (cron, webhook, etc)"""
        batch = await self.fetch_batch()
        results = await self.process_batch(batch)
        await self.report_results(results)
        # Exit - no persistent state
```

**Implementation Strategy**:
1. Create external trigger service (Redis keyspace notifications or cron)
2. Replace each loop with single-execution handler
3. Use Redis EXPIRE for time-based triggers

### 2.2 Remove Singletons
Replace 20+ singleton patterns:

```python
# BEFORE (singleton)
class ProviderHub:
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

# AFTER (dependency injection)
class ProviderHub:
    def __init__(self, redis: Redis, config: Config):
        self.redis = redis
        self.config = config
    # No singleton, created per request
```

### 2.3 Externalize All State
Move all instance variables to Redis:

```python
# BEFORE (internal state)
class TaskOrchestrator:
    def __init__(self):
        self._tasks = {}  # BAD: internal state
        self._running = False  # BAD: instance state

# AFTER (external state)
class TaskOrchestrator:
    def __init__(self, redis: Redis):
        self.redis = redis  # All state in Redis

    async def get_task(self, task_id: str):
        return await self.redis.hgetall(f"task:{task_id}")
```

## Phase 3: Distributed Coordination (Week 6-8)
**Goal**: Enable true distributed processing

### 3.1 Instance-Specific Consumer Groups
```python
# src/gleitzeit/events/distributed_consumer.py (NEW)
class DistributedConsumer:
    """Each instance has unique consumer group"""

    def __init__(self, instance_id: str):
        self.instance_id = instance_id
        self.consumer_group = f"worker_{instance_id}"
        self.consumer_id = f"consumer_{instance_id}_{uuid.uuid4().hex[:8]}"

    async def claim_work(self, workflow_id: str) -> bool:
        """Atomically claim workflow for this instance"""
        claimed = await self.redis.set(
            f"workflow:{workflow_id}:owner",
            self.instance_id,
            nx=True,  # Only if not exists
            ex=300    # 5 minute lease
        )
        return claimed
```

### 3.2 Distributed Locking
```python
# src/gleitzeit/coordination/distributed_lock.py (NEW)
class DistributedLock:
    """Redis-based distributed locking"""

    async def acquire(self, resource: str, ttl: int = 30) -> Optional[str]:
        """Acquire distributed lock"""
        lock_id = uuid.uuid4().hex
        acquired = await self.redis.set(
            f"lock:{resource}",
            lock_id,
            nx=True,
            ex=ttl
        )
        return lock_id if acquired else None

    async def release(self, resource: str, lock_id: str):
        """Release only if we own it"""
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        await self.redis.eval(lua_script, 1, f"lock:{resource}", lock_id)
```

### 3.3 Work Distribution via Consistent Hashing
```python
# src/gleitzeit/scaling/work_distributor.py (NEW)
class WorkDistributor:
    """Distributes work using consistent hashing"""

    def __init__(self, nodes: List[str]):
        self.ring = ConsistentHashRing(nodes)

    def get_owner(self, workflow_id: str) -> str:
        """Determine which node owns this workflow"""
        return self.ring.get_node(workflow_id)

    async def should_process(self, workflow_id: str, my_node_id: str) -> bool:
        """Check if this node should process workflow"""
        owner = self.get_owner(workflow_id)
        return owner == my_node_id
```

### 3.4 Remove Leader Election
Transform leader-only operations to distributed:

```python
# BEFORE (leader-only)
if self.is_leader:
    await self.reconcile_all_workflows()

# AFTER (distributed)
my_workflows = await self.get_my_workflows(self.instance_id)
await self.reconcile_workflows(my_workflows)
```

## Phase 4: Production Scaling (Week 9-12)
**Goal**: Production-ready horizontal scaling

### 4.1 API Layer Scaling
```python
# src/gleitzeit/api/stateless_app.py
class StatelessAPI:
    """Stateless API that can scale horizontally"""

    async def startup(self):
        # No singleton dependencies
        self.redis = await create_redis_pool()
        self.persistence = RedisPersistence(self.redis)
        # Dependencies created per instance

    async def route_to_owner(self, workflow_id: str):
        """Route request to workflow owner"""
        owner_node = await self.get_workflow_owner(workflow_id)
        if owner_node != self.node_id:
            return RedirectResponse(f"http://{owner_node}/...")
```

### 4.2 WebSocket Session Management
```python
# src/gleitzeit/api/websocket_scaling.py
class ScalableWebSocket:
    """WebSocket with Redis-backed sessions"""

    async def connect(self, websocket: WebSocket, client_id: str):
        # Store session in Redis, not memory
        await self.redis.hset(
            f"websocket:session:{client_id}",
            mapping={
                "node_id": self.node_id,
                "connected_at": time.time()
            }
        )

        # Subscribe to client's Redis channel for messages
        await self.subscribe_to_client_channel(client_id)
```

### 4.3 Load Balancer Configuration
```yaml
# kubernetes/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: gleitzeit-api
spec:
  type: LoadBalancer
  sessionAffinity: ClientIP  # Sticky sessions for WebSocket
  selector:
    app: gleitzeit
  ports:
    - port: 80
      targetPort: 8000
---
# kubernetes/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit
spec:
  replicas: 3  # Start with 3 instances
  strategy:
    type: RollingUpdate
  template:
    spec:
      containers:
      - name: gleitzeit
        env:
        - name: INSTANCE_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: SCALING_MODE
          value: "MULTI_NODE"
```

### 4.4 Auto-Scaling Configuration
```yaml
# kubernetes/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gleitzeit-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gleitzeit
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Pods
    pods:
      metric:
        name: redis_stream_lag
      target:
        type: AverageValue
        averageValue: "100"  # Scale up if lag > 100 messages
```

## Implementation Checklist

### Phase 1 (Critical Fixes)
- [ ] Implement consumer lifecycle with TTL
- [ ] Add idempotency framework
- [ ] Remove critical loops in event bus
- [ ] Add task status checks before rerun
- [ ] Clean up dead consumers

### Phase 2 (Stateless Conversion)
- [ ] Replace all 36+ loops with event-driven
- [ ] Remove all singleton patterns
- [ ] Externalize all state to Redis
- [ ] Remove all `_running` flags
- [ ] Implement request-scoped processing

### Phase 3 (Distributed Coordination)
- [ ] Instance-specific consumer groups
- [ ] Distributed locking via Redis
- [ ] Consistent hashing for work distribution
- [ ] Remove leader election
- [ ] Add work stealing for load balancing

### Phase 4 (Production Scaling)
- [ ] Stateless API layer
- [ ] Redis-backed WebSocket sessions
- [ ] Kubernetes deployment configs
- [ ] Load balancer with session affinity
- [ ] Auto-scaling based on metrics

## Success Metrics

### Phase 1 Success Criteria
- No dead consumers accumulating
- No workflows stuck in pending
- Tasks not rerun unsafely
- System stable with single instance

### Phase 2 Success Criteria
- Zero persistent loops in codebase
- No singleton patterns
- All state in Redis
- Clean shutdown/startup

### Phase 3 Success Criteria
- Multiple instances can run without conflicts
- Work distributed evenly
- No duplicate processing
- Automatic failover working

### Phase 4 Success Criteria
- Linear scaling with load
- < 100ms latency at 1000 RPS
- Automatic scaling 2-10 instances
- Zero downtime deployments
- 99.9% availability

## Risk Mitigation

### High-Risk Changes
1. **Removing loops**: Test thoroughly, may break existing workflows
2. **Consumer group changes**: May lose messages during transition
3. **State externalization**: Performance impact, add caching layer

### Rollback Strategy
1. Feature flags for each phase
2. Parallel deployment (old and new)
3. Gradual traffic shift
4. Automated rollback on error rate > 1%

## Testing Strategy

### Unit Tests
- Test idempotency checker
- Test distributed lock
- Test consistent hashing
- Test consumer lifecycle

### Integration Tests
- Multi-instance coordination
- Failover scenarios
- Load distribution
- WebSocket session handoff

### Load Tests
- Single instance baseline
- 2, 4, 8 instance scaling
- Measure linear scaling
- Identify bottlenecks

### Chaos Testing
- Kill random instances
- Network partitions
- Redis failures
- High load spikes

## Monitoring Requirements

### Key Metrics
- Consumer lag per instance
- Task processing rate
- Error rate by component
- Instance CPU/memory
- Redis connection pool usage
- WebSocket connections per instance

### Alerts
- Consumer lag > 1000 messages
- Dead consumers detected
- Task retry rate > 10%
- Instance CPU > 80%
- Redis memory > 80%

## Migration Path

### Phase 1 Migration (No Downtime)
1. Deploy consumer lifecycle in parallel
2. Start heartbeat for new consumers
3. Clean dead consumers gradually
4. Monitor for stability

### Phase 2 Migration (Brief Downtime)
1. Stop all instances
2. Clear Redis streams
3. Deploy stateless version
4. Restart with clean state

### Phase 3 Migration (Rolling)
1. Deploy one new instance
2. Test distributed coordination
3. Gradually add instances
4. Remove old instances

### Phase 4 Migration (Zero Downtime)
1. Deploy behind load balancer
2. Gradually shift traffic
3. Scale based on load
4. Monitor and optimize

## Conclusion

This plan transforms Gleitzeit from a stateful, single-instance system to a truly horizontally scalable distributed system. The phased approach minimizes risk while delivering incremental value. Each phase builds on the previous, with clear success criteria and rollback strategies.

**Total Effort**: 8-12 weeks
**Team Size**: 2-3 senior engineers
**Complexity**: High
**Business Value**: Enables 10x+ scale capacity

After implementation, Gleitzeit will achieve:
- **True horizontal scaling** (2-100+ instances)
- **High availability** (99.9%+)
- **Auto-scaling** based on load
- **Zero-downtime deployments**
- **Linear performance scaling**