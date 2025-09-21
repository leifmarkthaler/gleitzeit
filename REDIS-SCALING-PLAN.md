# Redis Scaling Architecture Plan

## Executive Summary
Design and implementation plan for scaling Redis data layer to support distributed Gleitzeit deployments with high availability, geographic distribution, and linear scalability.

## Current State
- **Single Redis Instance**: All nodes connect to one Redis server
- **No Sharding**: All data in single keyspace
- **No Replication**: Single point of failure
- **Limited Throughput**: Bottlenecked by single Redis instance

## Proposed Architecture

### Option 1: Redis Cluster (Recommended)
**Best for**: High throughput, automatic sharding, production environments

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Gleitzeit   │     │ Gleitzeit   │     │ Gleitzeit   │
│   Node A    │     │   Node B    │     │   Node C    │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┴───────────────────┘
                           │
                    Redis Cluster
       ┌───────────────────┴───────────────────┐
       │                                       │
┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
│ Redis       │     │ Redis       │     │ Redis       │
│ Master 1    │     │ Master 2    │     │ Master 3    │
│ Slots 0-5460│     │Slots 5461-  │     │Slots 10923- │
│             │     │    10922    │     │    16383    │
├─────────────┤     ├─────────────┤     ├─────────────┤
│ Replica 1-1 │     │ Replica 2-1 │     │ Replica 3-1 │
│ Replica 1-2 │     │ Replica 2-2 │     │ Replica 3-2 │
└─────────────┘     └─────────────┘     └─────────────┘
```

#### Advantages
- ✅ Automatic sharding across 16384 hash slots
- ✅ Built-in failover and high availability
- ✅ Linear scalability (add more masters)
- ✅ Native Redis Cluster client support
- ✅ No proxy layer needed

#### Implementation Requirements
1. Minimum 3 master nodes (6 total with replicas)
2. Cluster-aware client configuration
3. Hash tag support for related keys
4. Cross-slot operation handling

### Option 2: Redis Sentinel + Read Replicas
**Best for**: Read-heavy workloads, simpler setup

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Gleitzeit   │     │ Gleitzeit   │     │ Gleitzeit   │
│   Node A    │     │   Node B    │     │   Node C    │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┴───────────────────┘
                           │
                  Redis Sentinel HA
                           │
       ┌───────────────────┴───────────────────┐
       │                                       │
┌──────▼──────┐                         ┌──────▼──────┐
│   Master    │◄────────────────────────┤  Sentinel 1 │
│   (Write)   │                         ├─────────────┤
└──────┬──────┘                         │  Sentinel 2 │
       │                                ├─────────────┤
       ├────────────┬────────────┐      │  Sentinel 3 │
       │            │            │      └─────────────┘
┌──────▼──────┬──────▼──────┬──────▼──────┐
│  Replica 1  │  Replica 2  │  Replica 3  │
│   (Read)    │   (Read)    │   (Read)    │
└─────────────┴─────────────┴─────────────┘
```

#### Advantages
- ✅ Simpler than cluster
- ✅ Automatic failover
- ✅ Read scaling through replicas
- ✅ Lower operational overhead

#### Limitations
- ❌ Single master bottleneck for writes
- ❌ No automatic sharding
- ❌ Limited write scalability

### Option 3: Application-Level Sharding
**Best for**: Custom requirements, full control

```
┌─────────────────────────────────────────┐
│         Gleitzeit Shard Router          │
├─────────────────────────────────────────┤
│  - Consistent hashing for data          │
│  - Shard key selection                  │
│  - Cross-shard query coordination       │
└────────┬──────────┬──────────┬─────────┘
         │          │          │
    ┌────▼────┬────▼────┬────▼────┐
    │ Shard 1 │ Shard 2 │ Shard 3 │
    │ Redis   │ Redis   │ Redis   │
    └─────────┴─────────┴─────────┘
```

## Implementation Strategy

### Phase 1: Redis Cluster Support (Week 1-2)

#### 1. Update UnifiedRedisAdapter
```python
class UnifiedRedisAdapter:
    def __init__(self, 
                 redis_url: str = None,
                 redis_nodes: List[Dict] = None,  # For cluster mode
                 cluster_mode: bool = False,
                 read_preference: str = "primary"):  # primary, replica, nearest
        
        if cluster_mode:
            self.redis = RedisCluster(
                startup_nodes=redis_nodes,
                decode_responses=False,
                skip_full_coverage_check=True
            )
        else:
            self.redis = Redis.from_url(redis_url)
```

#### 2. Hash Tag Strategy for Related Keys
```python
class RedisKeyStrategy:
    """Ensure related data stays on same shard"""
    
    @staticmethod
    def workflow_keys(workflow_id: str) -> Dict[str, str]:
        """Use hash tags to keep workflow data together"""
        hash_tag = f"{{{workflow_id}}}"
        return {
            "workflow": f"workflow:{hash_tag}",
            "tasks": f"tasks:{hash_tag}",
            "execution": f"execution:{hash_tag}",
            "results": f"results:{hash_tag}"
        }
    
    @staticmethod
    def task_key(task_id: str, workflow_id: str) -> str:
        """Keep task with its workflow"""
        return f"task:{{{workflow_id}}}:{task_id}"
```

#### 3. Cross-Slot Operation Handling
```python
class ClusterOperationHandler:
    """Handle Redis Cluster constraints"""
    
    async def multi_get(self, keys: List[str]) -> Dict[str, Any]:
        """Parallel fetch across slots"""
        # Group keys by slot
        slot_groups = self._group_by_slot(keys)
        
        # Parallel fetch per slot
        tasks = []
        for slot_keys in slot_groups.values():
            tasks.append(self._fetch_slot_keys(slot_keys))
        
        results = await asyncio.gather(*tasks)
        return self._merge_results(results)
    
    def _group_by_slot(self, keys: List[str]) -> Dict[int, List[str]]:
        """Group keys by their hash slot"""
        groups = {}
        for key in keys:
            slot = crc16(key) % 16384
            groups.setdefault(slot, []).append(key)
        return groups
```

### Phase 2: Sharding Strategy (Week 2-3)

#### 1. Data Partitioning Design
```python
class ShardingStrategy:
    """Determine how to partition data"""
    
    SHARD_KEYS = {
        # Workflow sharding by ID
        "workflow": lambda wf_id: wf_id,
        
        # Tasks stay with workflow
        "task": lambda task_id, wf_id: wf_id,
        
        # Events by timestamp (time-series sharding)
        "event": lambda event_id, ts: ts // (86400 * 7),  # Weekly shards
        
        # Metrics by node (node-local)
        "metrics": lambda node_id: node_id,
        
        # Global data (registry, config) - no sharding
        "global": lambda: "global"
    }
```

#### 2. Shard-Aware Operations
```python
class ShardAwareRedisAdapter(UnifiedRedisAdapter):
    """Redis adapter with sharding awareness"""
    
    async def save_workflow(self, workflow: Workflow):
        """Save with shard routing"""
        shard_key = self.get_shard_key("workflow", workflow.id)
        
        # Use hash tags for cluster mode
        if self.cluster_mode:
            key = f"workflow:{{{shard_key}}}:{workflow.id}"
        else:
            key = f"workflow:{workflow.id}"
        
        await self.redis.hset(
            key,
            mapping=workflow.to_redis_hash()
        )
    
    async def get_workflows_cross_shard(self, 
                                       workflow_ids: List[str]) -> List[Workflow]:
        """Fetch workflows from multiple shards"""
        if not self.cluster_mode:
            # Simple batch get for single instance
            return await self._batch_get_workflows(workflow_ids)
        
        # Group by shard for cluster
        shard_groups = {}
        for wf_id in workflow_ids:
            shard = self.get_shard_key("workflow", wf_id)
            shard_groups.setdefault(shard, []).append(wf_id)
        
        # Parallel fetch from each shard
        tasks = []
        for shard_ids in shard_groups.values():
            tasks.append(self._batch_get_workflows(shard_ids))
        
        results = await asyncio.gather(*tasks)
        return [wf for sublist in results for wf in sublist]
```

### Phase 3: High Availability (Week 3-4)

#### 1. Connection Pool Management
```python
class ResilientRedisPool:
    """Manage connections with failover"""
    
    def __init__(self, 
                 primary_nodes: List[str],
                 replica_nodes: List[str] = None,
                 sentinel_nodes: List[str] = None):
        self.primary_pool = self._create_pool(primary_nodes)
        self.replica_pool = self._create_pool(replica_nodes) if replica_nodes else None
        self.sentinel = self._setup_sentinel(sentinel_nodes) if sentinel_nodes else None
        
    async def execute_write(self, command, *args, **kwargs):
        """Execute write on primary with retry"""
        for attempt in range(3):
            try:
                return await self.primary_pool.execute(command, *args, **kwargs)
            except RedisConnectionError:
                if attempt == 2:
                    raise
                await self._refresh_primary()
                await asyncio.sleep(0.1 * (2 ** attempt))
    
    async def execute_read(self, command, *args, **kwargs):
        """Execute read with replica fallback"""
        # Try replica first for read scaling
        if self.replica_pool:
            try:
                return await self.replica_pool.execute(command, *args, **kwargs)
            except:
                pass  # Fall back to primary
        
        return await self.execute_write(command, *args, **kwargs)
```

#### 2. Circuit Breaker Pattern
```python
class RedisCircuitBreaker:
    """Prevent cascading failures"""
    
    def __init__(self, 
                 failure_threshold: int = 5,
                 recovery_timeout: int = 60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
    
    async def call(self, func, *args, **kwargs):
        """Execute with circuit breaker protection"""
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half-open"
            else:
                raise CircuitOpenError("Redis circuit breaker is open")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
```

### Phase 4: Geographic Distribution (Week 4-5)

#### 1. Multi-Region Configuration
```python
class MultiRegionRedis:
    """Support for geographic distribution"""
    
    def __init__(self, regions: Dict[str, Dict]):
        """
        regions = {
            "us-west": {
                "primary": ["redis-us-west-1:6379"],
                "replicas": ["redis-us-west-2:6379"],
                "latency": 10
            },
            "eu-west": {
                "primary": ["redis-eu-west-1:6379"],
                "replicas": ["redis-eu-west-2:6379"],
                "latency": 50
            }
        }
        """
        self.regions = regions
        self.local_region = self._detect_local_region()
        self.pools = self._create_regional_pools()
    
    async def write_with_replication(self, key: str, value: Any):
        """Write to local region and replicate"""
        # Write to local region first
        await self.pools[self.local_region].set(key, value)
        
        # Async replicate to other regions
        for region in self.regions:
            if region != self.local_region:
                asyncio.create_task(
                    self._replicate_to_region(region, key, value)
                )
    
    async def read_with_fallback(self, key: str):
        """Read from nearest available region"""
        # Try local first
        try:
            return await self.pools[self.local_region].get(key)
        except:
            # Fallback to other regions by latency
            for region in self._regions_by_latency():
                try:
                    return await self.pools[region].get(key)
                except:
                    continue
        raise RedisUnavailableError("No regions available")
```

## Migration Strategy

### Step 1: Backward Compatible Updates
```python
# Add cluster support while maintaining single-instance compatibility
if redis_config.get("cluster_mode"):
    adapter = ClusterRedisAdapter(redis_config["nodes"])
else:
    adapter = UnifiedRedisAdapter(redis_config["url"])
```

### Step 2: Progressive Migration
1. Deploy with single Redis (current state)
2. Add read replicas for scaling reads
3. Migrate to Redis Cluster for production
4. Enable geographic distribution as needed

### Step 3: Data Migration Tool
```python
class RedisMigrator:
    """Migrate data between Redis configurations"""
    
    async def migrate(self, source: Redis, target: Redis, 
                     batch_size: int = 1000):
        """Zero-downtime migration"""
        # 1. Start dual writes
        await self.enable_dual_writes()
        
        # 2. Migrate existing data
        cursor = 0
        while True:
            cursor, keys = await source.scan(cursor, count=batch_size)
            
            if keys:
                await self.migrate_batch(source, target, keys)
            
            if cursor == 0:
                break
        
        # 3. Verify data integrity
        await self.verify_migration()
        
        # 4. Switch reads to new cluster
        await self.switch_reads()
        
        # 5. Stop dual writes
        await self.disable_dual_writes()
```

## Performance Optimizations

### 1. Pipeline Operations
```python
async def bulk_save_tasks(self, tasks: List[Task]):
    """Use pipelining for bulk operations"""
    pipe = self.redis.pipeline()
    
    for task in tasks:
        key = self.task_key(task.id, task.workflow_id)
        pipe.hset(key, mapping=task.to_redis_hash())
    
    await pipe.execute()
```

### 2. Lua Scripts for Atomicity
```python
WORKFLOW_UPDATE_SCRIPT = """
local workflow_key = KEYS[1]
local task_count_key = KEYS[2]
local status = ARGV[1]
local timestamp = ARGV[2]

redis.call('HSET', workflow_key, 'status', status, 'updated_at', timestamp)
local task_count = redis.call('GET', task_count_key)
return {status, task_count}
"""

async def update_workflow_atomic(self, workflow_id: str, status: str):
    """Atomic workflow update with Lua"""
    result = await self.redis.eval(
        WORKFLOW_UPDATE_SCRIPT,
        2,
        self.workflow_key(workflow_id),
        self.task_count_key(workflow_id),
        status,
        datetime.utcnow().isoformat()
    )
    return result
```

### 3. Read-Through Caching
```python
class CachedRedisAdapter:
    """Local caching layer for Redis"""
    
    def __init__(self, redis_adapter, cache_ttl: int = 60):
        self.redis = redis_adapter
        self.cache = TTLCache(maxsize=10000, ttl=cache_ttl)
    
    async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get with local cache"""
        # Check local cache
        if workflow_id in self.cache:
            return self.cache[workflow_id]
        
        # Fetch from Redis
        workflow = await self.redis.get_workflow(workflow_id)
        
        if workflow:
            self.cache[workflow_id] = workflow
        
        return workflow
```

## Monitoring & Observability

### Key Metrics to Track
```python
class RedisMetrics:
    """Redis scaling metrics"""
    
    METRICS = {
        # Cluster health
        "cluster.nodes.total": "Total nodes in cluster",
        "cluster.nodes.failed": "Failed nodes",
        "cluster.slots.migrating": "Slots being migrated",
        
        # Performance
        "latency.p50": "50th percentile latency",
        "latency.p99": "99th percentile latency",
        "ops.per.second": "Operations per second",
        
        # Sharding
        "shard.distribution": "Data distribution across shards",
        "shard.hotspots": "Hot shards by operations",
        
        # Replication
        "replication.lag": "Replication lag in seconds",
        "replication.offset": "Replication offset delta"
    }
```

## Configuration Examples

### Development (Single Instance)
```yaml
redis:
  mode: single
  url: redis://localhost:6379
  max_connections: 50
```

### Production (Redis Cluster)
```yaml
redis:
  mode: cluster
  nodes:
    - host: redis-cluster-1
      port: 7000
    - host: redis-cluster-2
      port: 7000
    - host: redis-cluster-3
      port: 7000
  read_preference: nearest
  max_connections_per_node: 50
  cluster_options:
    skip_full_coverage_check: true
    max_redirects: 3
```

### Multi-Region (Geographic Distribution)
```yaml
redis:
  mode: multi_region
  local_region: us-west
  regions:
    us-west:
      cluster_nodes:
        - redis-us-west-1:7000
        - redis-us-west-2:7000
    eu-west:
      cluster_nodes:
        - redis-eu-west-1:7000
        - redis-eu-west-2:7000
    ap-south:
      cluster_nodes:
        - redis-ap-south-1:7000
        - redis-ap-south-2:7000
  replication:
    mode: async
    consistency: eventual
```

## Testing Strategy

### 1. Cluster Failover Testing
```python
async def test_cluster_failover():
    """Test automatic failover"""
    # 1. Write data
    await adapter.save_workflow(test_workflow)
    
    # 2. Kill master node
    await kill_redis_node("master-1")
    
    # 3. Verify failover and data availability
    workflow = await adapter.get_workflow(test_workflow.id)
    assert workflow is not None
    
    # 4. Verify new master elected
    cluster_info = await adapter.redis.cluster_info()
    assert cluster_info["cluster_state"] == "ok"
```

### 2. Sharding Distribution Test
```python
async def test_even_distribution():
    """Test data distribution across shards"""
    # Generate 10000 workflows
    workflows = [create_test_workflow(i) for i in range(10000)]
    
    # Save to cluster
    for wf in workflows:
        await adapter.save_workflow(wf)
    
    # Check distribution
    distribution = await adapter.get_shard_distribution()
    
    # Verify even distribution (within 10% variance)
    avg = sum(distribution.values()) / len(distribution)
    for count in distribution.values():
        variance = abs(count - avg) / avg
        assert variance < 0.1
```

## Success Criteria

### Phase 1 (Cluster Support)
- [ ] Redis Cluster client integration
- [ ] Hash tag strategy for related keys
- [ ] Cross-slot operation handling
- [ ] Backward compatibility maintained

### Phase 2 (Sharding)
- [ ] Workflow/task co-location
- [ ] Event stream partitioning
- [ ] Metrics sharding by node
- [ ] Cross-shard query support

### Phase 3 (High Availability)
- [ ] Automatic failover < 30 seconds
- [ ] Zero data loss during failover
- [ ] Read replica support
- [ ] Circuit breaker implementation

### Phase 4 (Geographic Distribution)
- [ ] Multi-region support
- [ ] Cross-region replication
- [ ] Latency-based routing
- [ ] Regional failover

## Timeline

- **Week 1-2**: Redis Cluster support and testing
- **Week 2-3**: Sharding strategy implementation
- **Week 3-4**: High availability features
- **Week 4-5**: Geographic distribution
- **Week 5-6**: Migration tools and testing

**Total: 6 weeks for complete Redis scaling solution**