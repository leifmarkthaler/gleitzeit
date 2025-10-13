# Gleitzeit 0.0.7 - Process Management Deep Dive

**Date**: 2025-10-13
**Focus**: Multi-Instance Deployment and Service Coordination
**Related**: HORIZONTAL_SCALING_AUDIT.md

## Executive Summary

This document provides an in-depth analysis of Gleitzeit's process management architecture, specifically focusing on how multiple instances coordinate and what happens when you run `gleitzeit serve` on multiple hosts or with multiple instances.

**Key Finding**: Gleitzeit has **GOOD service registry architecture** with Redis-backed coordination, but has **CRITICAL implementation gaps** that prevent safe multi-instance deployment.

---

## Architecture Overview

Gleitzeit uses a **two-tier process management system**:

1. **AsyncProcessManager** ([async_process_manager.py](src/gleitzeit/core/async_process_manager.py)) - Low-level process spawning and monitoring
2. **SmartProcessManager** ([process_manager.py](src/gleitzeit/core/process_manager.py)) - High-level service coordination with Redis

### Process Lifecycle

```
gleitzeit serve
    ↓
AsyncServiceManager.start_all()
    ↓
├── _init_smart_manager() ← Checks Redis for existing services
├── start_api() ← Spawns API process
├── start_ui() ← Spawns UI process
├── start_essential_workers() ← Spawns worker processes
└── start_loki_exporter() ← Spawns Loki exporter
```

---

## Service Registry Architecture

### Redis Key Structure

Gleitzeit uses the following Redis keys for service coordination:

```
service:registry:{service_name}   # Hash with service metadata (PID, port, host, etc)
service:registry:{service_type}   # Set of instance IDs providing this service
service:ownership:{service_name}  # JSON with ownership details
service_lock:{service_name}       # Distributed lock for service claim
```

###Examples:
```redis
# Service metadata
HGETALL service:registry:api
  pid → "12345"
  port → "8000"
  host → "localhost"
  started_at → "2025-10-13T10:30:00"
  mode → "native"

# Service type registry
SMEMBERS service:registry:api
  → {instance-id-1, instance-id-2}

# Service lock (with TTL)
GET service_lock:api
  → "instance-id-1:12345"
  (expires in 30 seconds)
```

---

## Current Behavior: What Happens with Multiple Instances?

### Scenario 1: Running `gleitzeit serve` Twice on Same Host

**Test**:
```bash
# Terminal 1
gleitzeit serve

# Terminal 2 (same host)
gleitzeit serve
```

**What Happens**:

1. **First instance starts successfully**:
   - API starts on port 8000
   - UI starts on port 8004
   - Workers start (all shards assigned)
   - Loki exporter starts
   - Services registered in Redis

2. **Second instance behavior** ([async_process_manager.py:500-510](src/gleitzeit/core/async_process_manager.py#L500-L510)):
   ```python
   # Check if already running in registry
   if "api" in self.existing_services:
       existing = self.existing_services["api"]
       logger.info(f"API service already running (PID: {existing.get('pid')}, Port: {existing.get('port')})")
       return ProcessInfo(
           pid=int(existing.get('pid')),
           name="api",
           command=[],
           process=None,  # Attached, not owned
           port=int(existing.get('port', port)),
           started_at=datetime.now()
       )
   ```

   **Result**: ✅ **GOOD** - Second instance **attaches** to existing services instead of starting duplicates!

3. **Worker behavior**:
   - Workers use Redis Streams with consumer groups
   - Both instances' workers join the same consumer group
   - Messages are load-balanced automatically
   - ✅ **SAFE** - No conflicts

4. **Loki Exporter behavior**:
   - ⚠️ **PROBLEM** - NO coordination!
   - Both instances will start their own Loki exporter
   - Both will poll Redis and export logs
   - **Result**: Duplicate log exports to Loki

**Overall Result**: **MOSTLY WORKS** but with Loki duplication issue

---

### Scenario 2: Running on Different Hosts

**Test**:
```bash
# Host 1 (192.168.1.10)
gleitzeit serve

# Host 2 (192.168.1.11)
gleitzeit serve
```

**What Happens**:

1. **Both instances start their own services**:
   - Each starts API on port 8000 (no conflict - different hosts)
   - Each starts UI on port 8004 (no conflict - different hosts)
   - Each starts workers (✅ coordinated via Redis Streams)
   - Each starts Loki exporter (⚠️ **DUPLICATE EXPORTS**)

2. **Service Registry State**:
   ```redis
   HGETALL service:registry:api_host1
     pid → "12345"
     port → "8000"
     host → "192.168.1.10"

   HGETALL service:registry:api_host2
     pid → "67890"
     port → "8000"
     host → "192.168.1.11"
   ```

   **Issue**: Service registry uses service NAME as key, not instance-specific!
   - Second instance will **OVERWRITE** first instance's registration
   - Only one API will be discoverable at a time
   - ⚠️ **BUG** - Lost service discovery

3. **Worker Coordination**:
   - ✅ **WORKS** - Workers from both hosts join same consumer groups
   - Load balanced automatically
   - No issues here

**Overall Result**: **BROKEN** - Service discovery only shows one instance

---

## Critical Issues Identified

### Issue 1: Service Registry Key Collision ⚠️ **CRITICAL**

**Location**: [async_process_manager.py:536-542](src/gleitzeit/core/async_process_manager.py#L536-L542)

**Problem**:
```python
# Register in service registry
if result and self.smart_manager:
    network_host = self._get_network_hostname(host)
    await self.smart_manager.register_service("api", {  # ← "api" is not unique!
        "pid": str(result.pid),
        "port": str(port),
        "host": network_host,  # Different hosts but same key
        "started_at": datetime.now().isoformat(),
        "mode": "native"
    })
```

**Issue**: The key `service:registry:api` is shared across ALL instances. When Host 2 registers, it overwrites Host 1's data.

**Impact**:
- **HIGH** - Service discovery broken for multi-host deployments
- Load balancers can't find all API instances
- Failover doesn't work (lost instances not tracked)
- Metrics/monitoring only sees one instance

**Evidence**:
```python
# From process_manager.py:1269-1272
async def register_service(self, name: str, info: Dict):
    """Add persistent service registration with shorter TTL for heartbeat"""
    key = f"service:registry:{name}"  # ← Same key for all instances!
    await self.redis.hset(key, mapping=info)
```

**Fix Required**:

Option 1: **Include instance ID in key**:
```python
# In SmartProcessManager
async def register_service(self, name: str, info: Dict):
    instance_id = get_current_instance().instance_id
    key = f"service:registry:{name}:{instance_id}"  # Unique per instance
    await self.redis.hset(key, mapping=info)
    await self.redis.expire(key, 60)

    # Also add to service type set for discovery
    await self.redis.sadd(f"service:type:{name}:instances", instance_id)
```

Option 2: **Use Redis Sets instead of single hash**:
```python
async def register_service(self, name: str, info: Dict):
    # Add instance to service set
    instance_id = get_current_instance().instance_id
    instance_key = f"service:instance:{instance_id}:{name}"

    await self.redis.hset(instance_key, mapping=info)
    await self.redis.expire(instance_key, 60)

    # Register in service registry for discovery
    await self.redis.sadd(f"service:registry:{name}:instances", instance_key)
```

---

### Issue 2: Heartbeat Only Refreshes Local Services ⚠️ **MEDIUM**

**Location**: [async_process_manager.py:878-910](src/gleitzeit/core/async_process_manager.py#L878-L910)

**Problem**:
```python
async def _refresh_service_registrations(self):
    # Re-register all running services
    services_refreshed = 0
    for name, info in self.process_manager.processes.items():
        if info.process is not None or info.pid:  # Service is running
            if name == "api" or name == "ui":
                # Re-register service with updated TTL
                service_data = await self.smart_manager.redis.hgetall(f"service:registry:{name}")
                # ...refresh...
```

**Issue**: Heartbeat loop only refreshes services **in the local process_manager.processes dict**. It doesn't:
- Check if the service is still healthy
- Remove stale registrations from other instances
- Coordinate with other instances

**Impact**:
- **MEDIUM** - Stale service registrations persist
- Dead instances remain in registry beyond TTL
- No active health checking

**Fix Required**: Implement distributed health checking with proper coordination.

---

### Issue 3: No Loki Exporter Coordination ⚠️ **CRITICAL**

**Already documented in HORIZONTAL_SCALING_AUDIT.md**

**Location**: [loki_exporter_worker.py](src/gleitzeit/workers/loki_exporter_worker.py)

**Problem**: No leader election or coordination

**Impact**: **HIGH** - Duplicate log exports

**Fix**: Add leader election (already documented in audit)

---

### Issue 4: Port Management Has No Multi-Host Awareness ⚠️ **LOW**

**Location**: [async_process_manager.py:497-510](src/gleitzeit/core/async_process_manager.py#L497-L510)

**Current Code**:
```python
async def start_api(self, host: str = "0.0.0.0", port: int = 8000, dev_mode: bool = False):
    # Check if already running in registry
    if "api" in self.existing_services:
        existing = self.existing_services["api"]
        logger.info(f"API service already running...")
        return ProcessInfo(...)  # Attach to existing

    # Start new API on fixed port
    command = [
        self.python_path, "-m", "uvicorn",
        "gleitzeit.api.main:app",
        "--host", host,
        "--port", str(port),  # ← Hardcoded port
        "--log-level", "info"
    ]
```

**Issue**: When instance finds existing service, it assumes it's the same one and "attaches". But in multi-host scenario:
- Host 1 has API on 192.168.1.10:8000
- Host 2 checks registry, sees "api" exists
- Host 2 "attaches" to Host 1's API metadata
- Host 2 thinks it has an API running locally, but it's on Host 1!

**Impact**:
- **LOW** - Confusing logs and metrics
- Local health checks might fail
- Not a correctness issue (workers still function)

**Fix**: Check if existing service is on THIS host before attaching:
```python
async def start_api(self, host: str = "0.0.0.0", port: int = 8000, dev_mode: bool = False):
    if "api" in self.existing_services:
        existing = self.existing_services["api"]
        existing_host = existing.get('host', 'localhost')
        local_hostname = socket.gethostname()

        # Only attach if service is on THIS host
        if existing_host in ['localhost', '127.0.0.1', local_hostname]:
            logger.info(f"API service already running locally, attaching...")
            return ProcessInfo(...)
        else:
            logger.info(f"API service running on {existing_host}, starting local instance...")
            # Start new local API
```

---

## Good Patterns Found ✅

### 1. Attach-to-Existing Pattern

**Location**: [async_process_manager.py:756-780](src/gleitzeit/core/async_process_manager.py#L756-L780)

```python
# If services exist and not restarting, attach to them
if self.existing_services and not restart:
    logger.info(f"Found {len(self.existing_services)} existing services, attaching to them")
    self.attached_mode = True

    # Reconstruct ProcessInfo objects for existing services
    for service_name, service_info in self.existing_services.items():
        pid = int(service_info.get('pid', 0))
        port = service_info.get('port')

        # Create a ProcessInfo object for the existing service
        info = ProcessInfo(
            pid=pid,
            name=service_name,
            command=[],
            process=None,  # Can't attach to subprocess, but we can monitor via PID
            port=port,
            started_at=datetime.fromisoformat(service_info.get('started_at'))
        )
        self.process_manager.processes[service_name] = info
```

**Analysis**: ✅ **EXCELLENT PATTERN**
- Prevents duplicate service starts on same host
- Allows monitoring of externally-started services
- Enables graceful restarts

### 2. Service Heartbeat with Circuit Breaker

**Location**: [async_process_manager.py:835-876](src/gleitzeit/core/async_process_manager.py#L835-L876)

```python
async def _service_heartbeat_loop(self):
    """Periodically refresh service registrations to prevent expiry."""
    from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitOpenError

    circuit_breaker = CircuitBreaker(
        "service_heartbeat",
        CircuitBreakerConfig(
            failure_threshold=10,
            success_threshold=2,
            reset_timeout=300  # 5 minutes
        )
    )

    while True:  # Never exit - keep trying forever
        try:
            await asyncio.sleep(30)  # Heartbeat every 30 seconds
            await circuit_breaker.call(self._refresh_service_registrations)
```

**Analysis**: ✅ **EXCELLENT PATTERN**
- Circuit breaker prevents cascading failures
- Automatic backoff on Redis connection issues
- Never gives up (resilient)

### 3. Process Health Validation

**Location**: [async_process_manager.py:426-449](src/gleitzeit/core/async_process_manager.py#L426-L449)

```python
# Validate that registered services are actually still running
self.existing_services = {}
if registered_services:
    logger.info(f"Found {len(registered_services)} services in registry, checking health...")
    import psutil

    for service_name, service_info in registered_services.items():
        try:
            pid = int(service_info.get('pid', 0))
            if pid and psutil.pid_exists(pid):
                # Check if process is actually running
                proc = psutil.Process(pid)
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    self.existing_services[service_name] = service_info
                    logger.info(f"  ✅ {service_name} (PID: {pid}) is healthy")
                else:
                    logger.info(f"  ❌ {service_name} (PID: {pid}) is zombie/dead, removing from registry")
                    await self.smart_manager.unregister_service(service_name)
```

**Analysis**: ✅ **EXCELLENT PATTERN**
- Validates PIDs before trusting registry
- Cleans up stale entries
- Uses psutil for robust process checking

---

## Deployment Patterns Analysis

### Pattern 1: Single Instance (Current Default) ✅

**Command**:
```bash
gleitzeit serve
```

**Behavior**:
- Starts all services (API, UI, workers, Loki exporter)
- Works perfectly
- No scaling issues

**Use Case**: Development, small workloads, single-host deployments

**Status**: ✅ **FULLY SUPPORTED**

---

### Pattern 2: Multiple Instances, Same Host ⚠️

**Command**:
```bash
# Terminal 1
gleitzeit serve

# Terminal 2
gleitzeit serve
```

**Behavior**:
- Instance 2 detects existing services via Redis
- Attaches to existing API/UI
- Starts additional workers (✅ coordinated via streams)
- Starts duplicate Loki exporter (⚠️ **BUG**)

**Use Case**: Scaling workers on powerful single host

**Status**: **MOSTLY WORKS** with Loki duplication issue

**Fix Required**: Add Loki leader election

---

### Pattern 3: Multiple Instances, Multiple Hosts ❌

**Command**:
```bash
# Host 1
gleitzeit serve

# Host 2
gleitzeit serve
```

**Behavior**:
- Both start full stack
- Service registry collision (last writer wins)
- Workers coordinate correctly ✅
- Loki exporters duplicate ⚠️
- Service discovery broken ⚠️

**Use Case**: True distributed deployment, high availability

**Status**: ❌ **BROKEN** - Service registry collision

**Fix Required**:
1. Fix service registry keys (add instance ID)
2. Add Loki leader election
3. Implement proper service discovery

---

### Pattern 4: Separate Service and Worker Deployments (Ideal) 🎯

**Architecture**:
```
# Service Host (singleton)
gleitzeit serve --no-workers

# Worker Host 1
gleitzeit serve --no-api --no-ui

# Worker Host 2
gleitzeit serve --no-api --no-ui
```

**Behavior** (after fixes):
- Service host runs API, UI, Loki exporter (singleton)
- Worker hosts only run workers
- Workers coordinate via Redis Streams ✅
- Clean separation of concerns

**Use Case**: Production deployments, Kubernetes

**Status**: **SUPPORTED** but needs --no-workers, --no-api flags

**Current Support**:
- `--no-ui` flag exists ✅
- `--no-workers` flag exists ✅
- `--no-api` flag exists ✅

**Recommendation**: ✅ **USE THIS PATTERN** for production

---

## Recommended Deployment Architecture

### Option 1: Kubernetes (Recommended for Production)

```yaml
# Service Deployment (1 replica)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-services
spec:
  replicas: 1  # Singleton
  template:
    spec:
      containers:
      - name: gleitzeit
        image: gleitzeit:0.0.7
        command: ["gleitzeit", "serve", "--no-workers"]
        ports:
        - containerPort: 8000  # API
        - containerPort: 8004  # UI

---
# Worker Deployment (scalable)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-workers
spec:
  replicas: 3  # Scale as needed
  template:
    spec:
      containers:
      - name: gleitzeit
        image: gleitzeit:0.0.7
        command: ["gleitzeit", "serve", "--no-api", "--no-ui"]
```

### Option 2: Docker Compose

```yaml
services:
  gleitzeit-services:
    image: gleitzeit:0.0.7
    command: gleitzeit serve --no-workers
    ports:
      - "8000:8000"
      - "8004:8004"

  gleitzeit-worker-1:
    image: gleitzeit:0.0.7
    command: gleitzeit serve --no-api --no-ui
    depends_on:
      - gleitzeit-services

  gleitzeit-worker-2:
    image: gleitzeit:0.0.7
    command: gleitzeit serve --no-api --no-ui
    depends_on:
      - gleitzeit-services
```

---

## Summary of Findings

| Component | Issue | Severity | Impact | Fix Required |
|-----------|-------|----------|--------|--------------|
| **Service Registry Keys** | Collision on multi-host | **CRITICAL** | Service discovery broken | Yes - Add instance ID |
| **Loki Exporter** | No coordination | **CRITICAL** | Duplicate exports | Yes - Add leader election |
| **Heartbeat** | Only refreshes local | **MEDIUM** | Stale entries persist | Optional improvement |
| **Port Management** | No host awareness | **LOW** | Confusing metrics | Optional improvement |
| **Worker Coordination** | None - works perfectly ✅ | **NONE** | None | No |
| **Service Attachment** | Works well ✅ | **NONE** | None | No |

---

## Remediation Priorities

### Priority 1: CRITICAL - Service Registry Fix

**Effort**: 4-6 hours
**Impact**: Enables multi-host deployment

**Implementation**:
1. Modify `SmartProcessManager.register_service()` to include instance ID in key
2. Update `get_registered_services()` to scan all instance-specific keys
3. Add service discovery API that returns all instances of a service type
4. Update existing code to use new discovery API

### Priority 2: CRITICAL - Loki Leader Election

**Effort**: 2-4 hours (already documented in HORIZONTAL_SCALING_AUDIT.md)
**Impact**: Eliminates duplicate log exports

### Priority 3: MEDIUM - Enhanced Health Checking

**Effort**: 4-6 hours
**Impact**: Better reliability, faster failure detection

**Features**:
- Cross-instance health checking
- Automatic stale entry cleanup
- Health status propagation to monitoring

---

## Testing Plan

### Test 1: Same-Host Multiple Instances
```bash
# Terminal 1
gleitzeit serve

# Terminal 2
gleitzeit serve

# Expected: Second instance attaches, no port conflicts
# Verify: ps aux | grep gleitzeit shows 2 sets of workers but shared API/UI
```

### Test 2: Multi-Host Deployment
```bash
# Host 1 (IP: 192.168.1.10)
gleitzeit serve

# Host 2 (IP: 192.168.1.11)
gleitzeit serve

# Expected: Both instances register separately
# Verify: redis-cli KEYS "service:registry:*" shows both instances
# Verify: Both APIs are discoverable
```

### Test 3: Service/Worker Split
```bash
# Service host
gleitzeit serve --no-workers

# Worker host
gleitzeit serve --no-api --no-ui

# Expected: Clean separation, no conflicts
# Verify: Only one Loki exporter running
```

---

## Conclusion

Gleitzeit has a **well-designed foundation** for multi-instance deployment:
- Redis-backed service registry ✅
- Process attachment pattern ✅
- Heartbeat with circuit breaker ✅
- Worker coordination via streams ✅

**However**, two critical bugs prevent production multi-host deployment:
1. Service registry key collision
2. Loki exporter duplication

**Estimated effort to fix**: 6-10 hours

**Recommended deployment until fixes**:
- Use `--no-workers` and `--no-api` flags to separate concerns
- Run services as singleton
- Scale workers horizontally (works today!)

---

**End of Deep Dive**
