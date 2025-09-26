# Gleitzeit Layered Architecture Scaling Audit

## Executive Summary
This document audits the scaling design patterns across all layers of Gleitzeit 0.0.7's architecture, focusing on Redis key patterns, coordination mechanisms, and scalability bottlenecks.

## Current Architecture Overview

```
Layer 4: ProcessOrchestrator     (Coordination)
Layer 3: ServiceManager/WorkerManager (Domain Logic)
Layer 2: SmartProcessManager     (Lifecycle)
Layer 1: PortManager/Instance    (Resources)
```

## Key Pattern Analysis by Layer

### Layer 1: Resource Management (PortManager + Instance)

**Current Implementation:**
- **Port locks:** File-based (`/tmp/gleitzeit_port_{port}.lock`)
- **Instance identity:** In-memory only
- **No Redis keys at this layer**

**Scaling Issues:**
- ❌ **File locks don't work across machines**
- ❌ **No distributed port coordination**
- ❌ **Instance discovery impossible**

**Recommendation:**
```python
# Add Redis-based resource coordination
instance:registry -> SET of all instance IDs
instance:{id}:info -> {name, host, capabilities, port_offset}
port:allocated:{port} -> {instance_id, service, allocated_at}
```

### Layer 2: SmartProcessManager

**Current Implementation:**
```python
# Service ownership (distributed lock)
service:ownership:{name} -> {instance_id, instance_name, port}

# Instance process data (monitoring)
instance:{id}:process:{name} -> {pid, port, status, type, ...}

# Port ownership (local only)
port:owner:{port} -> instance_id
```

**Scaling Analysis:**
- ✅ **Service ownership prevents duplicates** (good for uniqueness)
- ✅ **Instance namespacing for monitoring** (no contention)
- ❌ **Mixed patterns** (service vs instance centric)
- ❌ **No service registry** (can't find all API instances)

### Layer 3: Domain Managers

#### ServiceManager
**Current Implementation:**
- Relies entirely on SmartProcessManager
- No additional Redis keys
- No service discovery mechanism

**Scaling Issues:**
- ❌ **Can't run multiple API instances** (port conflict)
- ❌ **No load balancer support** (can't discover services)
- ❌ **No health endpoint aggregation**

**Recommendation:**
```python
# Service registry for load balancing
service:registry:api -> SET {instance_id1, instance_id2, ...}
service:registry:ui -> SET {instance_id1, instance_id2, ...}

# Service health
service:health:api:{instance_id} -> {healthy, last_check, response_time}
```

#### WorkerManager
**Current Implementation:**
```python
# Shard assignment (ephemeral, in-memory)
self.shard_assignments[worker_name] = assigned_shards

# No Redis persistence of shard assignments
```

**Scaling Issues:**
- ❌ **Shard assignments lost on restart**
- ❌ **No global view of shard coverage**
- ❌ **Can't rebalance shards dynamically**

**Recommendation:**
```python
# Persistent shard assignments
worker:shards:{worker_name} -> [0, 2, 4, 6, ...]
shard:owner:{shard_num} -> {worker_name, instance_id}

# Worker registry
worker:registry:{type} -> SET {worker1, worker2, ...}
```

### Layer 4: ProcessOrchestrator

**Current Implementation:**
- Pure coordination, no Redis keys
- Delegates everything to lower layers

**Scaling Issues:**
- ✅ **Clean separation** (good)
- ❌ **No global orchestration view**
- ❌ **Can't coordinate multi-instance deploys**

## Critical Scaling Problems

### 1. **No Service Discovery**
```python
# PROBLEM: Can't find all API servers for load balancing
# Currently: Must know exact instance ID
# Need: service:registry:api -> [instances...]
```

### 2. **Port Conflicts**
```python
# PROBLEM: File locks fail across machines
# Currently: /tmp/gleitzeit_port_8000.lock
# Need: Redis distributed locks
```

### 3. **Lost Shard Assignments**
```python
# PROBLEM: Worker restarts lose shard assignments
# Currently: In-memory only
# Need: Persistent shard registry
```

### 4. **No Instance Discovery**
```python
# PROBLEM: Can't list all instances
# Currently: No registry
# Need: instance:registry -> SET
```

### 5. **Monitoring Confusion**
```python
# PROBLEM: Mixed key patterns
# Currently: service:ownership:* AND instance:*:process:*
# Need: Consistent hybrid approach
```

## Recommended Scaling Architecture

### Hybrid Key Pattern (Best of Both)

```python
# 1. COORDINATION KEYS (Service-centric)
service:ownership:{name} -> {instance_id, claimed_at}  # Uniqueness
service:registry:{type} -> SET {instance_ids...}       # Discovery
service:health:{type}:{id} -> {status, metrics}        # Health

# 2. MONITORING KEYS (Instance-centric)
instance:registry -> SET {all_instance_ids}            # Discovery
instance:{id}:info -> {name, host, capabilities}       # Metadata
instance:{id}:process:{name} -> {pid, port, status}    # Process data
instance:{id}:metrics -> {cpu, memory, uptime}         # Resources

# 3. WORKER KEYS (Work-centric)
worker:registry:{type} -> SET {worker_ids}             # Discovery
worker:shards:{id} -> [assigned_shards]                # Assignment
shard:owner:{num} -> {worker_id, instance_id}          # Ownership

# 4. RESOURCE KEYS (Global)
port:allocated:{port} -> {instance_id, service}        # Port registry
lock:{resource} -> {owner, expires_at}                 # Distributed locks
```

### Benefits of Hybrid Approach

1. **Service Uniqueness**: `service:ownership` prevents duplicates
2. **Easy Discovery**: `*:registry` keys for finding services/instances
3. **Clean Monitoring**: `instance:*` namespace for per-instance queries
4. **No Contention**: Instance keys don't conflict between instances
5. **Global View**: Registry keys provide system-wide visibility

## Implementation Priority

### Phase 1: Fix Critical Issues
1. Add `service:registry` keys for service discovery
2. Move port locks to Redis
3. Persist shard assignments

### Phase 2: Enable Multi-Instance Services
1. Support multiple API instances (different ports)
2. Add health check aggregation
3. Implement load balancer support

### Phase 3: Advanced Scaling
1. Dynamic shard rebalancing
2. Auto-scaling based on metrics
3. Cross-region coordination

## Code Changes Required

### 1. SmartProcessManager
```python
async def claim_service(self, service_name: str, port: int):
    # ... existing ownership claim ...

    # ADD: Register in service registry
    service_type = self._get_service_type(service_name)
    await self.redis.sadd(f"service:registry:{service_type}",
                         self.instance.instance_id)
```

### 2. WorkerManager
```python
async def start_worker(self, worker_name: str, shards: List[int]):
    # ... existing start logic ...

    # ADD: Persist shard assignment
    await self.redis.set(f"worker:shards:{worker_name}",
                        json.dumps(shards))

    # ADD: Register worker
    await self.redis.sadd(f"worker:registry:{worker_type}",
                         worker_name)
```

### 3. ServiceManager
```python
async def start_api(self, port: Optional[int] = None):
    # ADD: Support multiple instances
    if not port:
        port = await self._find_available_port(base=8000)

    # ... start with dynamic port ...
```

## Monitoring Impact

The current `gleitzeit ps` command needs updating:
1. Check `service:registry` keys first (find instances)
2. Then scan `instance:*:process` for each instance
3. Show instance hostname in output for distributed view

## Conclusion

The layered architecture has good separation of concerns, but the Redis key patterns are inconsistent and missing critical scaling features:

**Current State**: Mixed patterns, no discovery, local-only resources
**Target State**: Hybrid pattern with service discovery and distributed coordination

The hybrid approach (service-centric for coordination, instance-centric for monitoring) provides the best scaling characteristics while maintaining the clean layered architecture.

**Critical Changes Needed:**
1. Service registries for discovery
2. Redis-based port coordination
3. Persistent shard assignments
4. Instance registry for global view

These changes would enable true horizontal scaling across multiple machines while preserving the benefits of the layered architecture.