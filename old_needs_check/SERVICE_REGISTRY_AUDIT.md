# Service Registry Audit - Heartbeat and State Management

## Current Implementation Analysis

### Two Different Service Registration Architectures

#### 1. API/UI Registration (Centrally Managed - PROBLEMATIC)

**Initial Registration** ([async_process_manager.py:540-549](src/gleitzeit/core/async_process_manager.py#L540-L549)):
```python
await self.smart_manager.register_service("api", {
    "pid": str(result.pid),
    "port": str(port),
    "host": network_host,
    "started_at": datetime.now().isoformat(),
    "mode": "native"
})
```
- Key pattern: `service:registry:api` or `service:registry:ui`
- TTL: 60 seconds
- Managed externally by AsyncServiceManager

**Heartbeat** ([async_process_manager.py:899-960](src/gleitzeit/core/async_process_manager.py#L899-L960)):
```python
# Runs every 30 seconds
for name, info in self.process_manager.processes.items():
    if name == "api" or name == "ui":
        service_data = {"pid": str(info.pid), ...}  # ← FROM MEMORY
        await self.smart_manager.register_service(name, service_data)
```
- ❌ Uses in-memory state (STATEFUL)
- ❌ No process verification
- ❌ Assumes memory matches reality

#### 2. Worker Registration (Self-Managed - BETTER) ✅

**Initial Registration** ([workers/base.py:465-486](src/gleitzeit/workers/base.py#L465-L486)):
```python
async def _register_worker(self):
    worker_info = {
        "worker_type": self.config.worker_type,
        "worker_id": self.config.worker_id,
        "status": "running",
        "pid": os.getpid(),  # ← ALWAYS CURRENT
        ...
    }
    key = f"{{shard:0}}:worker:registry:{self.config.worker_type}:{self.config.worker_id}"
    await self.redis.hset(key.encode(), mapping={...})
    await self.redis.expire(key.encode(), 60)
```
- Key pattern: `{shard:0}:worker:registry:{type}:{id}`
- TTL: 60 seconds
- Each worker registers itself

**Heartbeat** ([workers/base.py:487-491](src/gleitzeit/workers/base.py#L487-L491)):
```python
async def _heartbeat_loop(self):
    while self._running:
        await self._register_worker()  # ← Calls registration directly
```
- ✅ Worker is the authority on its own state
- ✅ No external memory dependency
- ✅ Better for distributed systems

**Test Evidence:**
```bash
$ gleitzeit ps
worker-*  localhost  N/A  docker  ✅ healthy  4h 13m
Summary: 9 healthy, 0 stale
```
Workers running 4+ hours proves heartbeat works correctly!

### Discovery Tool: `gleitzeit ps` ✅

**Implementation:** [ps_command.py](src/gleitzeit/cli/ps_command.py)

```python
# Scans Redis directly (stateless!)
async for key in redis.scan_iter(match=b"service:registry:*"):
    service_data = await redis.hgetall(key)

async for key in redis.scan_iter(match=b"{shard:0}:worker:registry:*:*"):
    worker_data = await redis.hgetall(key)
    ttl = await redis.ttl(key)  # ✅ Verifies heartbeat is active
```

**Features:**
- ✅ Queries Redis directly (single source of truth)
- ✅ Shows both services and workers
- ✅ Checks TTL for health detection
- ✅ Displays uptime and health status
- ✅ Works across all deployment modes

---

## Problems Identified

### 1. Memory-Based State for API/UI (Anti-pattern for Distributed Systems)

**Issue:** API/UI heartbeat uses `self.process_manager.processes` which is in-memory state.

**Scope:** This problem only affects API/UI services, NOT workers.
- ❌ API/UI: Centrally managed, uses memory
- ✅ Workers: Self-managed, always current

**Why This is Wrong for API/UI:**
- In a distributed system, multiple instances can manage services
- Memory state can become stale if:
  - Process is killed externally (kill -9, OOM killer)
  - Process crashes and restarts with different PID
  - Network partition prevents state updates
  - Instance restarts and loses memory

**Example Failure Scenario:**
```
1. Instance A starts API on PID 1234 (native mode)
2. API crashes (kill -9)
3. Instance A's memory still has PID 1234
4. Heartbeat refreshes registry with dead PID 1234
5. Instance B tries to start API, sees registry entry, thinks it's running
6. Instance B doesn't start API
7. No API is actually running!
```

**Evidence This Is Real:**
- `gleitzeit ps` shows 9 healthy workers (running 4+ hours)
- `gleitzeit ps` shows 0 API/UI services (native ones expired)

### 2. No Process Verification

**Issue:** Heartbeat doesn't check if process is actually alive before refreshing.

**Why This is Wrong:**
- Process could have died between heartbeat cycles
- Another process could have taken that PID
- Zombie processes (defunct) would still be registered

**Current Code:**
```python
if info.process is not None or info.pid:  # ← Just checks memory
    await self.smart_manager.register_service(name, service_data)
```

**Should Be:**
```python
if is_process_actually_running(info.pid):  # ← Verify with OS
    await self.smart_manager.register_service(name, service_data)
```

### 3. No Port Verification

**Issue:** Heartbeat doesn't verify the port is still occupied by the registered process.

**Why This is Wrong:**
- Process could have died and port released
- Another process could have bound to that port
- Service could have crashed and restarted on different port

**Example Failure:**
```
1. API registered on port 8000, PID 1234
2. API crashes
3. Different service binds to port 8000 (PID 5678)
4. Heartbeat refreshes registration with PID 1234, port 8000
5. Registry now points to wrong process!
```

### 4. TTL Too Short for Production

**Issue:** 60-second TTL with 30-second heartbeat has minimal safety margin.

**Why This is Wrong:**
- Any network hiccup > 30 seconds causes expiry
- GC pause > 30 seconds causes expiry
- CPU spike > 30 seconds causes expiry
- Redis slow query > 30 seconds causes expiry

**Industry Standards:**
- Kubernetes: 10-40 second heartbeat, 60-120 second timeout
- Consul: 10 second heartbeat, 60 second timeout
- etcd: 5 second heartbeat, 20-60 second timeout

### 5. Two Separate Heartbeat Systems (Architectural Inconsistency)

**Observation:** API/UI and Workers use different heartbeat mechanisms.

**API/UI Heartbeat** ([async_process_manager.py:881-960](src/gleitzeit/core/async_process_manager.py#L881-L960)):
- Managed centrally by `AsyncServiceManager._service_heartbeat_loop()`
- Refreshes `service:registry:api` and `service:registry:ui`
- 30-second interval, 60-second TTL
- Uses memory state from process manager

**Worker Heartbeat** ([workers/base.py:465-491](src/gleitzeit/workers/base.py#L465-L491)):
- Each worker manages its own heartbeat
- Refreshes `{shard:0}:worker:registry:{type}:{id}`
- Workers self-register independently
- 60-second TTL
- Worker process registers itself (not managed externally)

**Architectural Analysis:**
- ✅ Workers self-register (better for distributed systems) - PROVEN WORKING
- ❌ API/UI use external manager (creates stateful dependency)
- ❌ Inconsistent key patterns (`service:registry:*` vs `worker:registry:*`)
- ✅ Workers use `os.getpid()` directly (stateless, always current)
- ❌ API/UI use memory state (stateful, can become stale)
- ❓ Why different approaches for similar services?

**Better Design:** API/UI should adopt worker self-registration pattern.

### 6. No Graceful Shutdown Hook

**Issue:** When instance stops, services remain in registry until TTL expires.

**Why This is Wrong:**
- New instances wait 60 seconds before detecting service is gone
- Port conflicts during the TTL window
- Unnecessary failover delays

---

## Impact on Horizontal Scaling

### Scenario 1: API Horizontal Scaling
```bash
# Instance A
gleitzeit serve --api-only --api-port 8000

# Instance B (30 seconds later)
gleitzeit serve --api-only --api-port 8001
```

**Current Behavior:**
- ✅ Both start successfully (different ports)
- ✅ Both register in Redis
- ❓ If Instance A API crashes, heartbeat still refreshes with stale PID
- ❌ Instance B might think Instance A is still running when it's not
- ❌ Load balancer routes traffic to dead instance

### Scenario 2: Worker Scaling
```bash
# Instance A
gleitzeit serve --workers-only

# Instance B
gleitzeit serve --workers-only
```

**Current Behavior:**
- ✅ Both start successfully
- ✅ Workers have their own heartbeat system (`workers/base.py:_heartbeat_loop`)
- ✅ Workers self-register at `{shard:0}:worker:registry:{type}:{id}`
- ✅ Workers use `os.getpid()` directly (always current, not memory-based)
- ✅ Evidence shows workers running healthy for 4+ hours
- ⚠️ Still no process verification before re-registration (could improve)

### Scenario 3: Network Partition
```bash
# Instance A running API and Workers
# Network partition occurs for 35 seconds
```

**API/UI Behavior (PROBLEMATIC):**
- ❌ Heartbeat can't reach Redis for 35 seconds
- ❌ TTL expires at 60 seconds (5 seconds after partition heals)
- ❌ Service disappears from registry
- ✅ Recent fix allows re-registration even if key expired
- ⚠️ But still uses memory state (could be stale)

**Worker Behavior (BETTER):**
- ❌ Heartbeat can't reach Redis for 35 seconds
- ❌ TTL expires, workers disappear from registry
- ✅ When partition heals, workers re-register using `os.getpid()` (always current)
- ✅ Workers correctly restore their registration

---

## Data Flow Issues

### Registration Data Sources

1. **Initial Registration:** Real process data (PID from just-started process)
2. **Heartbeat Refresh:** Memory data (could be stale)

**Inconsistency Risk:**
- Initial registration is authoritative
- Heartbeat could overwrite with stale data
- No single source of truth

### State Synchronization

**Current:**
```
OS (actual processes)
    ↓ (at start only)
Memory (self.process_manager.processes)
    ↓ (heartbeat every 30s)
Redis (service registry)
```

**Problem:** One-way flow from memory to Redis, no verification against OS

**Should Be:**
```
OS (actual processes) ← ALWAYS query for truth
    ↓
Redis (service registry) ← Update based on OS state
    ↓
Memory (cache only) ← Don't use for heartbeat
```

---

## Security Considerations

### PID Reuse Attack

**Vulnerability:**
```
1. Malicious process starts with PID 1234
2. Gleitzeit API crashes (was PID 1234)
3. Heartbeat refreshes registration with PID 1234
4. Registry now points to malicious process
```

**Mitigation:** Verify process command line matches expected service

### Port Hijacking

**Vulnerability:**
```
1. API crashes, releases port 8000
2. Attacker binds to port 8000
3. Load balancer routes traffic to attacker
4. Registry still shows legitimate service
```

**Mitigation:** Verify port is still bound to correct PID

---

## Recommendations Summary

### For API/UI Services (NEEDS FIXING)
1. **Adopt worker self-registration pattern** - Each service should register itself using current process state
2. **Always verify process state with OS** before refreshing (like `os.getpid()`)
3. **Increase TTL to 5 minutes** for production stability
4. **Add process verification** (PID exists, not zombie, correct command)
5. **Add port verification** (port still bound to expected PID)
6. **Add graceful shutdown** to unregister immediately
7. **Add service health checks** beyond just "process exists"

### For Workers (ALREADY WORKING)
1. ✅ Already use self-registration pattern
2. ✅ Already use `os.getpid()` for current state
3. ⚠️ Could add process verification before re-registration
4. ⚠️ Could add graceful shutdown hook

### System-Wide
1. **Unify registration patterns** - Use same approach for all services
2. **Consider higher-level orchestration** (Kubernetes, Consul) for production

---

## Next Steps

### Immediate Priority (Fix API/UI Heartbeat)
1. **Create design document** for migrating API/UI to self-registration pattern
2. **Implement self-registration** for API/UI services (like workers do)
3. **Remove memory-based heartbeat** from AsyncServiceManager
4. **Test horizontal scaling** with multiple API instances

### Medium Priority (Improvements)
5. Add process verification to worker heartbeat (for robustness)
6. Add configuration for TTL (don't hard-code 60 seconds)
7. Implement graceful shutdown hooks for all services
8. Add health checks beyond "process exists"

### Long-term (Production Scaling)
9. Consider migrating to proper service mesh (Consul, etcd)
10. Implement load balancer integration with service discovery
11. Add metrics and monitoring for service health
