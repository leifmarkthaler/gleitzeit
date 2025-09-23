# Redis Cluster Implementation Guide for Gleitzeit 0.0.7

## Overview

Gleitzeit 0.0.7 now uses Redis Cluster exclusively for horizontal scaling and high availability. All Redis keys use hash tags to ensure workflow locality, enabling atomic operations while distributing load across cluster nodes.

## Key Design Principles

### 1. Hash Tag Based Sharding
All keys use `{shard:N}` hash tags to control routing:
- Workflows are assigned to one of 16 logical shards (0-15)
- All data for a workflow goes to the same Redis node
- Enables atomic operations, pipelines, and Lua scripts

### 2. Workflow Locality
```python
workflow_id = "workflow_123"
shard = hash(workflow_id) % 16  # e.g., shard 5

# All these keys go to the same Redis node:
"{shard:5}:workflow:data:workflow_123"
"{shard:5}:workflow:status:workflow_123"
"{shard:5}:task:ready"
"{shard:5}:task:status:task_456"
```

### 3. Connection Pooling
Each Redis Cluster node gets its own connection pool:
- Default: 50 connections per node
- Configurable via `REDIS_MAX_CONNECTIONS` env var
- Keep-alive enabled for connection health

## Architecture Changes

### Before (Single Redis)
```
Worker → Redis Instance → Single Connection Pool
         ↓
         All Keys
```

### After (Redis Cluster)
```
Worker → Redis Cluster Client → Node 1 → Connection Pool 1 → {shard:0-5} keys
                              → Node 2 → Connection Pool 2 → {shard:6-10} keys
                              → Node 3 → Connection Pool 3 → {shard:11-15} keys
```

## Configuration

### Environment Variables
```bash
# Required
REDIS_CLUSTER_NODES=localhost:7000,localhost:7001,localhost:7002

# Optional
REDIS_MAX_CONNECTIONS=50          # Per node
REDIS_KEEPALIVE=true             # Enable TCP keepalive
REDIS_HEALTH_CHECK_INTERVAL=30   # Seconds between health checks
```

### Docker Compose Example
```yaml
version: '3.8'

services:
  redis-node-1:
    image: redis:7-alpine
    command: redis-server --port 7000 --cluster-enabled yes --cluster-config-file nodes.conf --cluster-node-timeout 5000 --appendonly yes
    ports:
      - "7000:7000"
    volumes:
      - redis-1:/data

  redis-node-2:
    image: redis:7-alpine
    command: redis-server --port 7001 --cluster-enabled yes --cluster-config-file nodes.conf --cluster-node-timeout 5000 --appendonly yes
    ports:
      - "7001:7001"
    volumes:
      - redis-2:/data

  redis-node-3:
    image: redis:7-alpine
    command: redis-server --port 7002 --cluster-enabled yes --cluster-config-file nodes.conf --cluster-node-timeout 5000 --appendonly yes
    ports:
      - "7002:7002"
    volumes:
      - redis-3:/data

  gleitzeit-worker:
    image: gleitzeit:0.0.7
    environment:
      - REDIS_CLUSTER_NODES=redis-node-1:7000,redis-node-2:7001,redis-node-3:7002
      - REDIS_MAX_CONNECTIONS=50
    depends_on:
      - redis-node-1
      - redis-node-2
      - redis-node-3

volumes:
  redis-1:
  redis-2:
  redis-3:
```

## Setting Up Redis Cluster

### 1. Start Redis Nodes
```bash
# Start 6 Redis instances (3 masters, 3 replicas)
for port in 7000 7001 7002 7003 7004 7005; do
  redis-server --port $port \
    --cluster-enabled yes \
    --cluster-config-file nodes-$port.conf \
    --cluster-node-timeout 5000 \
    --appendonly yes \
    --appendfilename appendonly-$port.aof \
    --dbfilename dump-$port.rdb \
    --logfile redis-$port.log \
    --daemonize yes
done
```

### 2. Create Cluster
```bash
redis-cli --cluster create \
  127.0.0.1:7000 127.0.0.1:7001 127.0.0.1:7002 \
  127.0.0.1:7003 127.0.0.1:7004 127.0.0.1:7005 \
  --cluster-replicas 1
```

### 3. Verify Cluster
```bash
redis-cli -c -p 7000 cluster info
redis-cli -c -p 7000 cluster nodes
```

## Code Migration Guide

### Update Worker Base Class
```python
# Old (single Redis)
from gleitzeit.workers.base import BaseWorker

# New (Redis Cluster)
from gleitzeit.workers.base_cluster import BaseWorker
```

### Update Sharding Imports
```python
# Old
from gleitzeit.core.sharding import ShardingStrategy

# New (same API, cluster-optimized)
from gleitzeit.core.sharding import ClusterShardingStrategy as ShardingStrategy
```

### Key Format Changes

All Redis keys now use hash tags:

| Operation | Old Format | New Format |
|-----------|------------|------------|
| Stream | `task:ready:5` | `{shard:5}:task:ready` |
| Workflow | `workflow:data:abc123` | `{shard:7}:workflow:data:abc123` |
| Task | `task:status:task456` | `{shard:7}:task:status:task456` |
| Signal | `signal:waiters:abc123:sig1` | `{shard:7}:signal:waiters:abc123:sig1` |
| Worker | `worker:registry:exec:w1` | `{shard:0}:worker:registry:exec:w1` |
| Metrics | `metrics:throughput` | `{shard:0}:metrics:throughput` |

## Performance Benefits

### 1. Linear Scaling
- Add more Redis nodes to handle more load
- Each node handles ~3-5 shards
- 16 shards can be distributed across 3-16 nodes

### 2. Connection Efficiency
- Connection pooling per node (not global)
- 3 nodes × 50 connections = 150 total connections
- Multiplexing via pipelining within shards

### 3. Atomic Operations
- All workflow operations hit same node
- Pipelines work within workflows
- Lua scripts work within workflows
- No cross-slot errors

### 4. High Availability
- Automatic failover with replicas
- No single point of failure
- Rolling upgrades possible

## Monitoring

### Cluster Health
```python
async def check_cluster_health():
    redis = GleitzeitRedisCluster()
    await redis.initialize()

    # Check overall cluster state
    is_healthy = await redis.healthcheck()

    # Get detailed cluster info
    info = await redis.cluster_info()
    nodes = await redis.cluster_nodes()

    return {
        "healthy": is_healthy,
        "state": info.get("cluster_state"),
        "nodes": len(nodes),
        "slots_covered": info.get("cluster_slots_ok")
    }
```

### Shard Distribution
```python
def analyze_shard_distribution(workflows):
    sharding = ClusterShardingStrategy()
    distribution = {}

    for wf_id in workflows:
        shard = sharding.get_shard(wf_id)
        distribution[shard] = distribution.get(shard, 0) + 1

    return distribution
```

## Troubleshooting

### Issue: MOVED Errors
**Cause**: Client has outdated cluster topology
**Solution**: Client automatically refreshes topology on MOVED errors

### Issue: CROSSSLOT Errors
**Cause**: Pipeline/transaction with keys from different shards
**Solution**: All Gleitzeit keys use hash tags to prevent this

### Issue: Connection Pool Exhaustion
**Cause**: Too many concurrent operations
**Solution**: Increase `REDIS_MAX_CONNECTIONS` or add more workers

### Issue: Uneven Shard Distribution
**Cause**: Poor workflow ID distribution
**Solution**: Use UUIDs or well-distributed IDs for workflows

## Best Practices

1. **Use UUIDs for Workflow IDs**: Ensures even distribution across shards
2. **Monitor Shard Balance**: Check that workflows distribute evenly
3. **Size Cluster Appropriately**: Start with 3 masters, scale as needed
4. **Use Replicas**: At least 1 replica per master for HA
5. **Pipeline Operations**: Batch operations within same workflow
6. **Health Checks**: Monitor cluster state continuously

## Testing

### Local Cluster Testing
```bash
# Start test cluster
./scripts/start_test_cluster.sh

# Run tests
REDIS_CLUSTER_NODES=localhost:7000,localhost:7001,localhost:7002 \
  pytest tests/

# Stop test cluster
./scripts/stop_test_cluster.sh
```

### Load Testing
```python
async def load_test_cluster():
    redis = GleitzeitRedisCluster()
    await redis.initialize()

    # Submit many workflows across shards
    for i in range(10000):
        workflow_id = f"test_{uuid.uuid4()}"
        shard = hash(workflow_id) % 16

        # All operations for this workflow hit same node
        async with redis.pipeline() as pipe:
            pipe.hset(f"{{shard:{shard}}}:workflow:data:{workflow_id}", ...)
            pipe.xadd(f"{{shard:{shard}}}:task:ready", ...)
            await pipe.execute()
```

## Conclusion

The Redis Cluster implementation provides:
- **Horizontal scaling** without application changes
- **High availability** with automatic failover
- **Better resource utilization** via connection pooling per node
- **Maintained atomicity** for workflow operations
- **No backward compatibility issues** - cluster-only is simpler

The hash tag approach (`{shard:N}`) ensures all benefits of sharding while maintaining the ability to perform atomic operations, pipelines, and Lua scripts within workflows.