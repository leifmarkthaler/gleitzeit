# Client & Execution Engine Scaling Audit
## Targeted Analysis for Horizontal Scaling

**Date:** 2025-08-30  
**Version:** 0.0.6  
**Focus:** Client and ExecutionEngine reorganization for distributed deployment

---

## Executive Summary

The current client-engine architecture has **4 critical bottlenecks** preventing horizontal scaling:

1. **Singleton PersistenceManager** - Forces single engine instance
2. **In-memory state** - Execution stats, parameter mappings stored locally
3. **Direct instantiation** - NativeAdapter creates ExecutionEngine directly
4. **Tight coupling** - Components share object references

**Good news:** The client already has clean adapter separation (API vs Native) and the event infrastructure supports distribution. With targeted changes, the system can support multiple ExecutionEngine instances.

**Effort Required:** 4-6 weeks for full horizontal scaling capability

---

## Current Architecture Analysis

### Client Architecture ✅ Well-Designed

```python
ModularGleitzeitClient
├── APIAdapter          # Remote execution via HTTP
│   └── Stateless communication with API servers
└── NativeAdapter       # Local execution
    └── Direct ExecutionEngine instantiation ⚠️
```

**Strengths:**
- Clean adapter pattern separates concerns
- API mode already supports multiple backends
- Minimal client-side state

**Issue:**
- NativeAdapter creates ExecutionEngine directly (tight coupling)

### ExecutionEngine State Problems 🔴

```python
class ExecutionEngine:
    def __init__(self):
        # ❌ Local state that prevents scaling
        self.stats = ExecutionStats()           # In-memory stats
        self.task_name_to_id_map = {}          # Workflow mappings
        self._active_tasks = set()             # Current tasks
        self._shutdown_event = asyncio.Event() # Process control
```

**Critical Issues:**

| State Type | Current Location | Impact | Required Change |
|------------|-----------------|--------|-----------------|
| Execution Stats | Memory | Lost on restart | → Redis |
| Parameter Mappings | Memory | Not shared | → Redis per workflow |
| Active Tasks | Memory | No coordination | → Redis Set |
| Dependency Tracking | Memory | Duplicate work | → Redis |

### Singleton Bottlenecks 🔴

```python
# PersistenceManager forces single instance
class PersistenceManager:
    _adapter: Optional[PersistenceBackend] = None  # ❌ Global singleton
    
    @classmethod
    def get_adapter(cls) -> PersistenceBackend:
        if cls._adapter is None:
            cls.initialize()  # Creates single shared instance
        return cls._adapter
```

**Impact:** All components share one persistence connection, preventing multiple engines

---

## Scaling Bottleneck Analysis

### 1. State Management Issues

**Current State Distribution:**
```
┌────────────────────────────────────┐
│     ExecutionEngine Instance       │
├────────────────────────────────────┤
│ Memory:                            │
│  - stats (ExecutionStats)          │
│  - task_name_to_id_map            │
│  - _active_tasks                   │
│  - _workflow_states                │
│                                    │
│ Redis:                             │
│  - Task/Workflow persistence       │
│  - Events (pub/sub)                │
└────────────────────────────────────┘
```

**Problem:** Each engine has isolated memory state, causing:
- Incorrect global statistics
- Duplicate parameter resolution
- No task coordination
- Lost state on restart

### 2. Client-Engine Coupling

```python
# Current: Direct instantiation
class NativeAdapter:
    def __init__(self):
        self.execution_engine = ExecutionEngine(
            registry=self.registry,
            queue_manager=self.queue_manager,
            # ... direct dependencies
        )
```

**Problems:**
- Can't distribute to multiple engines
- No load balancing
- No failover capability

### 3. Missing Load Distribution

**Current Task Flow:**
```
Client → NativeAdapter → Single ExecutionEngine → Providers
                         ↑ All tasks go here
```

**Needed for Scaling:**
```
Client → LoadBalancer → Engine Pool → Selected Engine → Providers
                        ├── Engine 1
                        ├── Engine 2
                        └── Engine N
```

---

## Reorganization Plan for Scaling

### Phase 1: State Externalization (Week 1-2)

#### 1.1 Replace Singleton PersistenceManager

```python
# NEW: Factory pattern with connection pooling
class PersistenceFactory:
    @staticmethod
    async def create_connection(
        connection_id: str,
        config: Dict[str, Any]
    ) -> PersistenceBackend:
        """Create independent persistence connection"""
        if config['type'] == 'redis':
            return UnifiedRedisAdapter(
                redis_url=config['url'],
                connection_pool_size=config.get('pool_size', 10)
            )
        # ... other backends
        
# Each engine gets its own connection
engine1_persistence = await PersistenceFactory.create_connection("engine1", config)
engine2_persistence = await PersistenceFactory.create_connection("engine2", config)
```

#### 1.2 Externalize Execution Statistics

```python
# NEW: Distributed stats in Redis
class DistributedExecutionStats:
    def __init__(self, redis: Redis, engine_id: str):
        self.redis = redis
        self.engine_id = engine_id
        self.key_prefix = f"stats:{engine_id}"
        
    async def increment_tasks_processed(self):
        await self.redis.hincrby(self.key_prefix, "tasks_processed", 1)
        
    async def get_global_stats(self) -> Dict:
        """Aggregate stats across all engines"""
        pattern = "stats:*"
        stats = {}
        async for key in self.redis.scan_iter(pattern):
            engine_stats = await self.redis.hgetall(key)
            # Aggregate logic
        return stats
```

#### 1.3 Externalize Parameter Mappings

```python
# NEW: Workflow-scoped parameter storage
class DistributedParameterResolver:
    def __init__(self, redis: Redis):
        self.redis = redis
        
    async def store_workflow_mappings(
        self, 
        workflow_id: str, 
        tasks: List[Task]
    ):
        """Store task name->id mappings for workflow"""
        mapping = {task.name: task.id for task in tasks}
        key = f"workflow:{workflow_id}:mappings"
        await self.redis.hset(key, mapping=json.dumps(mapping))
        await self.redis.expire(key, 86400)  # 24h TTL
        
    async def resolve_parameters(
        self,
        task: Task,
        workflow_id: str
    ) -> Dict[str, Any]:
        """Resolve task parameters using stored mappings"""
        key = f"workflow:{workflow_id}:mappings"
        mapping = json.loads(await self.redis.hget(key, "mapping"))
        # Resolution logic using mapping
```

### Phase 2: Stateless ExecutionEngine (Week 2-3)

#### 2.1 Remove All Local State

```python
# NEW: Completely stateless engine
class StatelessExecutionEngine:
    def __init__(
        self,
        engine_id: str,
        persistence_config: Dict,
        registry_config: Dict
    ):
        self.engine_id = engine_id
        
        # All components created fresh, no shared state
        self.persistence = PersistenceFactory.create_connection(
            f"engine_{engine_id}", 
            persistence_config
        )
        self.stats = DistributedExecutionStats(
            self.persistence.redis,
            engine_id
        )
        self.param_resolver = DistributedParameterResolver(
            self.persistence.redis
        )
        
        # No local state variables!
        # No self._active_tasks, self.task_name_to_id_map, etc.
        
    async def execute_task(self, task_id: str) -> TaskResult:
        """Stateless task execution"""
        # 1. Get task from persistence
        task = await self.persistence.get_task(task_id)
        
        # 2. Check if already claimed (distributed lock)
        lock = await self.persistence.acquire_lock(
            f"task:{task_id}",
            self.engine_id,
            timeout=30000
        )
        if not lock:
            return TaskResult(status="already_claimed")
            
        # 3. Update active tasks in Redis
        await self.persistence.redis.sadd(
            f"engine:{self.engine_id}:active_tasks",
            task_id
        )
        
        try:
            # 4. Execute task
            result = await self._execute_task_impl(task)
            
            # 5. Update stats
            await self.stats.increment_tasks_processed()
            
            return result
        finally:
            # 6. Clean up
            await self.persistence.redis.srem(
                f"engine:{self.engine_id}:active_tasks",
                task_id
            )
            await self.persistence.release_lock(f"task:{task_id}")
```

#### 2.2 Engine Registry and Discovery

```python
# NEW: Engine service discovery
class EngineRegistry:
    def __init__(self, redis: Redis):
        self.redis = redis
        
    async def register_engine(
        self,
        engine_id: str,
        capabilities: List[str],
        endpoint: str,
        max_concurrent: int
    ):
        """Register engine for discovery"""
        engine_info = {
            'engine_id': engine_id,
            'endpoint': endpoint,
            'capabilities': json.dumps(capabilities),
            'max_concurrent': max_concurrent,
            'current_load': 0,
            'status': 'healthy',
            'last_heartbeat': datetime.utcnow().isoformat()
        }
        
        await self.redis.hset(
            f"engines:{engine_id}",
            mapping=engine_info
        )
        
        # Add to capability indexes
        for capability in capabilities:
            await self.redis.sadd(
                f"capability:{capability}:engines",
                engine_id
            )
    
    async def get_engines_for_protocol(
        self,
        protocol: str
    ) -> List[EngineInfo]:
        """Find engines that support protocol"""
        engine_ids = await self.redis.smembers(
            f"capability:{protocol}:engines"
        )
        
        engines = []
        for engine_id in engine_ids:
            info = await self.redis.hgetall(f"engines:{engine_id}")
            if info['status'] == 'healthy':
                engines.append(EngineInfo(**info))
                
        return engines
```

### Phase 3: Client Load Balancing (Week 3-4)

#### 3.1 Multi-Engine Native Adapter

```python
# NEW: Load-balancing native adapter
class DistributedNativeAdapter:
    def __init__(
        self,
        persistence_config: Dict,
        engine_count: int = 3
    ):
        self.persistence = PersistenceFactory.create_connection(
            "client",
            persistence_config
        )
        self.registry = EngineRegistry(self.persistence.redis)
        
        # Create engine pool
        self.engines = []
        for i in range(engine_count):
            engine = StatelessExecutionEngine(
                engine_id=f"engine_{i}",
                persistence_config=persistence_config,
                registry_config={}
            )
            self.engines.append(engine)
            
        self.load_balancer = LoadBalancer(
            strategy=LoadBalancingStrategy.LEAST_LOADED
        )
        
    async def submit_task(self, task: Task) -> str:
        """Submit task with load balancing"""
        # 1. Store task in persistence
        task_id = await self.persistence.create_task(task)
        
        # 2. Find capable engines
        capable_engines = await self.registry.get_engines_for_protocol(
            task.protocol
        )
        
        # 3. Select best engine
        selected = self.load_balancer.select_resource(
            capable_engines,
            await self._get_engine_loads()
        )
        
        # 4. Route to engine (async via event)
        await self.persistence.redis.publish(
            f"engine:{selected.engine_id}:tasks",
            task_id
        )
        
        return task_id
```

#### 3.2 Load Balancing Strategies

```python
class LoadBalancer:
    def __init__(self, strategy: LoadBalancingStrategy):
        self.strategy = strategy
        self.request_counts = {}  # Track for round-robin
        
    async def select_resource(
        self,
        resources: List[EngineInfo],
        loads: Dict[str, int] = None
    ) -> EngineInfo:
        """Select best resource based on strategy"""
        
        if self.strategy == LoadBalancingStrategy.ROUND_ROBIN:
            # Simple round-robin
            selected = resources[self.request_counts.get('index', 0) % len(resources)]
            self.request_counts['index'] = self.request_counts.get('index', 0) + 1
            return selected
            
        elif self.strategy == LoadBalancingStrategy.LEAST_LOADED:
            # Select engine with lowest load
            return min(resources, key=lambda e: loads.get(e.engine_id, 0))
            
        elif self.strategy == LoadBalancingStrategy.RANDOM:
            # Random selection
            return random.choice(resources)
            
        elif self.strategy == LoadBalancingStrategy.WEIGHTED:
            # Weight by capacity
            weights = [e.max_concurrent - loads.get(e.engine_id, 0) for e in resources]
            return random.choices(resources, weights=weights)[0]
```

### Phase 4: Distributed Coordination (Week 4-5)

#### 4.1 Work Stealing Queue

```python
# NEW: Distributed work-stealing for load balancing
class WorkStealingQueue:
    def __init__(self, redis: Redis, engine_id: str):
        self.redis = redis
        self.engine_id = engine_id
        self.local_queue = f"queue:{engine_id}"
        self.global_queue = "queue:global"
        
    async def get_task(self) -> Optional[str]:
        """Get task with work stealing"""
        # 1. Try local queue first
        task_id = await self.redis.lpop(self.local_queue)
        if task_id:
            return task_id
            
        # 2. Try global queue
        task_id = await self.redis.lpop(self.global_queue)
        if task_id:
            return task_id
            
        # 3. Try stealing from other engines
        return await self._steal_work()
        
    async def _steal_work(self) -> Optional[str]:
        """Steal work from overloaded engines"""
        # Find overloaded engines
        engines = await self.redis.keys("queue:engine_*")
        for engine_queue in engines:
            if engine_queue == self.local_queue:
                continue
                
            # Check queue length
            length = await self.redis.llen(engine_queue)
            if length > 10:  # Threshold for stealing
                # Steal from the back (oldest tasks)
                task_id = await self.redis.rpoplpush(
                    engine_queue,
                    self.local_queue
                )
                if task_id:
                    return task_id
                    
        return None
```

#### 4.2 Engine Health Monitoring

```python
# NEW: Health monitoring and auto-recovery
class EngineHealthMonitor:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.health_check_interval = 10  # seconds
        
    async def run_health_checks(self):
        """Monitor engine health"""
        while True:
            engines = await self.redis.keys("engines:*")
            
            for engine_key in engines:
                engine_info = await self.redis.hgetall(engine_key)
                last_heartbeat = datetime.fromisoformat(
                    engine_info['last_heartbeat']
                )
                
                # Check if heartbeat is stale
                if datetime.utcnow() - last_heartbeat > timedelta(seconds=30):
                    # Mark engine as unhealthy
                    await self.redis.hset(
                        engine_key,
                        'status',
                        'unhealthy'
                    )
                    
                    # Redistribute tasks
                    await self._redistribute_tasks(
                        engine_info['engine_id']
                    )
                    
            await asyncio.sleep(self.health_check_interval)
            
    async def _redistribute_tasks(self, failed_engine_id: str):
        """Redistribute tasks from failed engine"""
        # Get active tasks from failed engine
        active_tasks = await self.redis.smembers(
            f"engine:{failed_engine_id}:active_tasks"
        )
        
        # Move to global queue for redistribution
        for task_id in active_tasks:
            await self.redis.lpush("queue:global", task_id)
            
        # Clear failed engine's active tasks
        await self.redis.delete(
            f"engine:{failed_engine_id}:active_tasks"
        )
```

---

## Implementation Checklist

### Week 1-2: State Externalization
- [ ] Replace PersistenceManager singleton with factory
- [ ] Implement DistributedExecutionStats
- [ ] Implement DistributedParameterResolver
- [ ] Move all engine state to Redis

### Week 2-3: Stateless Engine
- [ ] Create StatelessExecutionEngine
- [ ] Implement EngineRegistry
- [ ] Add distributed locking for tasks
- [ ] Remove all local state variables

### Week 3-4: Load Balancing
- [ ] Implement DistributedNativeAdapter
- [ ] Create LoadBalancer with strategies
- [ ] Add engine selection logic
- [ ] Implement connection pooling

### Week 4-5: Coordination
- [ ] Implement WorkStealingQueue
- [ ] Add EngineHealthMonitor
- [ ] Create task redistribution
- [ ] Add circuit breakers

### Week 5-6: Testing & Optimization
- [ ] Load testing with multiple engines
- [ ] Failover testing
- [ ] Performance optimization
- [ ] Documentation

---

## Success Metrics

### Performance Targets
- **Horizontal Scaling:** Support 10+ ExecutionEngine instances
- **Task Throughput:** 1000+ tasks/second across cluster
- **Load Distribution:** <10% variance between engines
- **Failover Time:** <5 seconds for engine failure recovery

### Architecture Goals
- **Zero Local State:** All state in Redis/persistence
- **Independent Engines:** No shared memory or singletons
- **Dynamic Scaling:** Add/remove engines without restart
- **Fault Tolerance:** Automatic task redistribution

---

## Migration Path

### Option 1: Parallel Development (Recommended)
1. Build new stateless components alongside existing
2. Test thoroughly in isolation
3. Switch over with feature flag
4. Remove old components

### Option 2: Incremental Refactoring
1. Externalize state piece by piece
2. Test after each change
3. Higher risk but continuous operation

---

## Conclusion

The client and ExecutionEngine require **moderate refactoring** to enable horizontal scaling:

1. **State externalization** (2 weeks) - Move all memory state to Redis
2. **Stateless engine** (1 week) - Remove singletons and local state
3. **Load balancing** (1 week) - Add multi-engine support to client
4. **Coordination** (1 week) - Implement work stealing and health monitoring

Total effort: **4-6 weeks** with 1-2 developers

The existing event infrastructure and Redis backend provide a solid foundation. The main work is externalizing state and removing singletons. Once complete, the system will support true horizontal scaling with multiple ExecutionEngine instances.

---

**Document Status:** Complete  
**Priority:** High - Required for production scaling  
**Next Steps:** Begin with PersistenceManager singleton removal