# Gleitzeit Stream Architecture - Enterprise Scale Implementation

## Executive Summary

This document describes Gleitzeit's pure stream-based architecture implementation using Redis Streams for enterprise-scale distributed processing. The system achieves 100,000+ events/second throughput with horizontal scaling to 1,000+ instances while maintaining stateless, event-driven principles.

**Target Metrics:**
- 100,000+ events/second throughput
- 1,000+ application instances
- 99.99% availability
- <5ms event processing latency
- Multi-region deployment capability

## Current State Analysis

### Strengths
- ✅ Stateless event-driven architecture (RedisEventScheduler)
- ✅ Proper separation of concerns (timers, signals, coordination)
- ✅ No persistent loops in application code
- ✅ Redis-based state management

### Bottlenecks
- ❌ Single Redis instance dependency
- ❌ Keyspace notifications broadcast to all instances
- ❌ JSON serialization inefficiency in sorted sets
- ❌ No work distribution/sharding mechanism
- ❌ Race conditions in concurrent processing

## Enterprise Scaling Strategy

### Phase 1: Stream-Based Event Distribution (3-6 months)

**Goal**: Replace keyspace notifications with Redis Streams for scalable work distribution

#### Current Pattern
```python
# Keyspace notifications - broadcasts to ALL instances
await self.persistence.redis.config_set("notify-keyspace-events", "Ex")
# Every instance receives every notification
```

#### New Pattern
```python
# Stream-based distribution with consumer groups
class StreamEventScheduler:
    async def schedule_event(self, event_type: str, delay_seconds: float, payload: dict):
        event_id = f"evt-{uuid.uuid4().hex[:8]}"

        # Add to timer stream with delay
        await self.redis.xadd("events:scheduled", {
            "event_id": event_id,
            "event_type": event_type,
            "scheduled_at": (datetime.utcnow() + timedelta(seconds=delay_seconds)).timestamp(),
            "payload": json.dumps(payload),
            "shard": self._calculate_shard(event_id)
        })

        return event_id

    async def process_events(self):
        # Consumer group ensures each event processed once
        messages = await self.redis.xreadgroup(
            "event-processors",
            f"instance-{self.instance_id}",
            {"events:scheduled": ">"},
            count=100,
            block=1000
        )

        for stream, msgs in messages:
            for msg_id, fields in msgs:
                await self._process_event_message(msg_id, fields)
```

**Benefits:**
- Each event processed by exactly one instance
- Natural load balancing across instances
- Automatic retry handling with Redis Streams
- Target: 10,000 events/sec, 100 instances

### Phase 2: Horizontal Sharding + Redis Cluster (6-12 months)

**Goal**: Implement consistent hashing and Redis cluster for horizontal scale

#### Sharding Strategy
```python
class ShardedEventManager:
    def __init__(self, total_shards=256):
        self.total_shards = total_shards
        self.redis_cluster = redis.RedisCluster(startup_nodes=cluster_nodes)

    def _calculate_shard(self, key: str) -> int:
        """Consistent hashing for event distribution"""
        return hash(key) % self.total_shards

    async def schedule_event(self, workflow_id: str, event_data: dict):
        shard = self._calculate_shard(workflow_id)
        stream_key = f"events:shard:{shard}"

        # Events for same workflow always go to same shard
        await self.redis_cluster.xadd(stream_key, {
            "workflow_id": workflow_id,
            "shard": shard,
            **event_data
        })

    async def process_shard_events(self, shard_id: int):
        """Process events for assigned shards only"""
        stream_key = f"events:shard:{shard_id}"
        consumer_group = f"processors-shard-{shard_id}"

        messages = await self.redis_cluster.xreadgroup(
            consumer_group,
            self.instance_id,
            {stream_key: ">"},
            count=1000
        )
```

#### Redis Cluster Configuration
```yaml
# redis-cluster.yml
redis_cluster:
  nodes: 12  # 4 primary + 8 replicas across 3 AZs
  memory_per_node: "32GB"
  shards: 256
  replication_factor: 2

  performance:
    max_connections: 10000
    tcp_keepalive: 60
    timeout: 5000

  persistence:
    rdb_enabled: true
    aof_enabled: true
    aof_fsync: "everysec"
```

**Benefits:**
- Horizontal scaling across multiple Redis nodes
- Automatic failover and data replication
- Workflow affinity (same workflow → same shard)
- Target: 50,000 events/sec, 500 instances

### Phase 3: Multi-Region + Advanced Optimization (12-18 months)

**Goal**: Global deployment with cross-region replication and advanced optimizations

#### Multi-Region Architecture
```python
class GlobalEventManager:
    def __init__(self, region: str, global_regions: List[str]):
        self.region = region
        self.local_cluster = RedisCluster(nodes=get_local_nodes())
        self.global_clusters = {
            r: RedisCluster(nodes=get_region_nodes(r))
            for r in global_regions
        }

    async def schedule_global_event(self, event_data: dict, target_regions: List[str]):
        """Schedule event across multiple regions"""
        event_id = f"global-{uuid.uuid4().hex}"

        tasks = []
        for region in target_regions:
            if region == self.region:
                # Local processing
                tasks.append(self._schedule_local_event(event_id, event_data))
            else:
                # Cross-region replication
                tasks.append(self._replicate_to_region(region, event_id, event_data))

        await asyncio.gather(*tasks)
```

#### Performance Optimizations
```python
class OptimizedEventProcessor:
    async def batch_process_events(self, max_batch_size=1000):
        """Process events in batches for efficiency"""
        pipeline = self.redis.pipeline()

        # Read multiple events
        messages = await self.redis.xreadgroup(
            self.consumer_group,
            self.instance_id,
            self.streams,
            count=max_batch_size
        )

        # Batch process
        for stream, msgs in messages:
            for msg_id, fields in msgs:
                pipeline.xack(stream, self.consumer_group, msg_id)
                await self._process_event_batch(fields)

        await pipeline.execute()

    async def _optimize_memory_usage(self):
        """Use Redis data structures efficiently"""
        # Use hashes for timer data instead of JSON in sorted sets
        timer_data = {
            "workflow_id": workflow_id,
            "scheduled_time": timestamp,
            "payload_ref": f"payload:{timer_id}"  # Reference to separate payload
        }

        # Store payload separately if large
        if len(payload) > 1024:
            await self.redis.hset(f"payload:{timer_id}", payload)
            timer_data["payload_ref"] = f"payload:{timer_id}"
        else:
            timer_data["payload"] = json.dumps(payload)
```

## Implementation Roadmap

### Milestone 1: Stream Foundation (Month 1-2)
- [ ] Implement `StreamEventScheduler` class
- [ ] Replace keyspace notifications in `RedisEventScheduler`
- [ ] Add consumer group management
- [ ] Create stream-based timer processing
- [ ] Update signal manager to use streams

### Milestone 2: Performance Baseline (Month 3)
- [ ] Load testing framework
- [ ] Benchmark current vs stream performance
- [ ] Identify bottlenecks and optimize
- [ ] Document performance characteristics

### Milestone 3: Sharding Implementation (Month 4-6)
- [ ] Implement consistent hashing
- [ ] Add shard-aware event routing
- [ ] Create shard rebalancing logic
- [ ] Test shard failover scenarios

### Milestone 4: Redis Cluster Migration (Month 7-9)
- [ ] Deploy Redis cluster infrastructure
- [ ] Migrate existing data to cluster
- [ ] Update all components for cluster support
- [ ] Implement cluster monitoring

### Milestone 5: Multi-Region (Month 10-12)
- [ ] Design cross-region replication strategy
- [ ] Implement region-aware routing
- [ ] Add conflict resolution mechanisms
- [ ] Deploy to multiple regions

## Risk Mitigation

### Technical Risks
1. **Redis Cluster Complexity**
   - Mitigation: Extensive testing in staging environment
   - Fallback: Gradual rollout with feature flags

2. **Data Consistency**
   - Mitigation: Implement idempotency keys
   - Monitoring: Add consistency checking tools

3. **Network Partitions**
   - Mitigation: Design for eventual consistency
   - Recovery: Automated reconciliation processes

### Operational Risks
1. **Increased Infrastructure Costs**
   - Mitigation: Cost monitoring and optimization
   - Strategy: Gradual scaling based on demand

2. **Operational Complexity**
   - Mitigation: Comprehensive monitoring and alerting
   - Training: Redis cluster operations training

## Success Metrics

### Performance Targets
- **Throughput**: 100,000+ events/second
- **Latency**: P99 < 5ms for event processing
- **Availability**: 99.99% uptime
- **Scalability**: Linear scaling to 1,000+ instances

### Monitoring Dashboard
```python
# Key metrics to track
metrics = {
    "events_per_second": "gauge",
    "processing_latency_p99": "histogram",
    "redis_cluster_health": "gauge",
    "consumer_group_lag": "gauge",
    "shard_distribution": "histogram",
    "cross_region_replication_lag": "gauge"
}
```

## Cost Analysis

### Infrastructure Costs (Monthly)
- **Redis Enterprise Cluster**: $15,000
- **Additional Compute**: $8,000
- **Network/Bandwidth**: $3,000
- **Monitoring/Observability**: $2,000
- **Total**: ~$28,000/month

### Development Costs (One-time)
- **Engineering**: 6 engineers × 12 months = $1.2M
- **Infrastructure Setup**: $100K
- **Testing/Validation**: $200K
- **Total**: ~$1.5M

### ROI Justification
- Supports 100x scale increase
- Enables enterprise customer acquisition
- Reduces operational overhead at scale
- Future-proofs architecture for 5+ years

## Conclusion

This scaling strategy transforms Gleitzeit from a single-instance system to an enterprise-grade, globally distributed event processing platform. The phased approach minimizes risk while delivering incremental value at each milestone.

The existing stateless architecture provides an excellent foundation - most scaling improvements are infrastructure and configuration changes rather than fundamental code rewrites.

**Recommendation**: Proceed with Phase 1 (Stream-based distribution) as it provides immediate scale benefits with minimal risk and can be implemented incrementally alongside the existing system.