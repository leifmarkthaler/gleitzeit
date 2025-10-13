# Gleitzeit 0.0.7 - Horizontal Scaling Fix Design Plan

**Date**: 2025-10-13
**Status**: Design Phase
**Related Documents**:
- HORIZONTAL_SCALING_AUDIT.md
- PROCESS_MANAGEMENT_DEEP_DIVE.md

## Executive Summary

This document provides a comprehensive design plan to fix all identified horizontal scaling issues in Gleitzeit 0.0.7. The fixes are organized into phases based on priority and dependencies.

**Total Estimated Effort**: 12-18 hours
**Target Completion**: Enables production multi-host deployment

---

## Issues to Fix

| Priority | Issue | Severity | Effort | Files Affected |
|----------|-------|----------|--------|----------------|
| **P0** | Loki Exporter - No Coordination | CRITICAL | 2-4h | loki_exporter_worker.py |
| **P1** | Service Registry Key Collision | CRITICAL | 4-6h | process_manager.py, async_process_manager.py |
| **P2** | Sharding Config Validation | HIGH | 1-2h | async_process_manager.py, sharding.py |
| **P3** | Enhanced Health Checking | MEDIUM | 4-6h | process_manager.py, async_process_manager.py |

---

# Phase 0: Loki Exporter Leader Election (P0 - CRITICAL)

## Problem Statement

Multiple Loki exporter instances will export the same logs to Loki, causing:
- Duplicate log entries
- Wasted storage
- Potential timestamp conflicts
- Increased load on Redis and Loki

**Current Code**: [loki_exporter_worker.py:209-234](src/gleitzeit/workers/loki_exporter_worker.py#L209-L234)

```python
async def run(self):
    await self.initialize()
    self.running = True

    levels = ["DEBUG", "INFO", "WARNING", "ERROR"]

    while self.running:
        # No coordination - all instances will do this!
        for level in levels:
            await self.export_level(level)

        await asyncio.sleep(self.poll_interval)
```

## Design Solution

Add leader election following the proven pattern from TimerWorker and SignalWorker.

### Architecture

```
LokiExporter Instance 1         LokiExporter Instance 2
        ↓                                ↓
   Leader Election ←----Redis----→ Leader Election
        ↓                                ↓
    IS LEADER                       NOT LEADER
        ↓                                ↓
   Export Logs                      (Wait)
```

### Implementation Details

**1. Add Leader Election to LokiExporterWorker**

```python
class LokiExporterWorker:
    def __init__(
        self,
        redis_url: str,
        loki_url: str = "http://localhost:3100",
        batch_size: int = 100,
        poll_interval: int = 5,
        worker_id: str = "loki-exporter"
    ):
        # ... existing code ...

        # Add leader election
        self.leader_election: Optional[LeaderElection] = None
        self.leader_key = "global:loki_exporter:leader"  # Global key (shard 0)
        self.leader_ttl = 30  # 30 second TTL
        self.is_leader = False
```

**2. Initialize Leader Election**

```python
async def initialize(self):
    """Initialize Redis connection and leader election"""
    # ... existing Redis connection code ...

    # Initialize leader election
    from gleitzeit.core.leader_election import LeaderElection
    from gleitzeit.core.sharding import default_sharding

    self.leader_key = default_sharding.get_global_key("loki_exporter:leader")
    self.leader_election = LeaderElection(
        self.redis,
        self.leader_key,
        self.worker_id,
        self.leader_ttl
    )

    self.logger.info(f"LokiExporter {self.worker_id} initialized with leader election")
```

**3. Add Leader Election Loop**

```python
async def _leader_election_loop(self):
    """Participate in leader election for log export"""
    self.logger.info(f"Starting leader election loop for {self.worker_id}")

    while self.running:
        try:
            # Try to become/remain leader
            status = await self.leader_election.try_elect()

            if status == LeaderStatus.BECAME_LEADER:
                self.logger.info(f"LokiExporter {self.worker_id} became leader")
            elif status == LeaderStatus.LOST_LEADERSHIP:
                self.logger.warning(f"LokiExporter {self.worker_id} lost leadership")

            # Heartbeat every 1/3 of TTL
            await asyncio.sleep(self.leader_ttl // 3)

        except Exception as e:
            self.logger.error(f"Leader election error: {e}")
            await asyncio.sleep(5)
```

**4. Modify Main Run Loop**

```python
async def run(self):
    """Main loop - only export logs if leader"""
    await self.initialize()
    self.running = True

    levels = ["DEBUG", "INFO", "WARNING", "ERROR"]

    # Start leader election task
    election_task = asyncio.create_task(self._leader_election_loop())

    try:
        while self.running:
            # Only export if we're the leader
            if self.leader_election and self.leader_election.is_leader:
                for level in levels:
                    try:
                        await self.export_level(level)
                    except Exception as e:
                        self.logger.error(f"Error exporting {level} logs: {e}")
            else:
                # Not leader - just wait
                self.logger.debug(f"Not leader, waiting... (leader: {await self.leader_election.get_current_leader()})")

            await asyncio.sleep(self.poll_interval)

    finally:
        # Cleanup
        election_task.cancel()
        if self.leader_election and self.leader_election.is_leader:
            await self.leader_election.release()

        if self.redis:
            await self.redis.close()
```

### Files to Modify

1. **src/gleitzeit/workers/loki_exporter_worker.py**
   - Add `leader_election` import
   - Add leader election attributes to `__init__`
   - Add `_leader_election_loop()` method
   - Modify `initialize()` to create LeaderElection
   - Modify `run()` to check leadership before exporting

### Testing

```python
# Test 1: Single Instance (Should work as before)
# Start one Loki exporter
# Expected: Becomes leader, exports logs

# Test 2: Two Instances Same Host
# Start two Loki exporters
# Expected: One becomes leader, other waits
# Expected: Only one set of exports to Loki

# Test 3: Leader Failover
# Start two instances, identify leader
# Kill leader process
# Expected: Follower becomes leader within 30s
# Expected: No gap in log exports > 30s
```

### Risks & Mitigation

**Risk 1**: Leader dies during export batch
- **Mitigation**: Use atomic batch operations, new leader will see `last_exported_timestamp` in Redis and continue from there

**Risk 2**: TTL too short causes leadership thrashing
- **Mitigation**: Use 30s TTL with 10s heartbeat (3x safety margin)

**Risk 3**: Network partition causes split-brain
- **Mitigation**: Lua script for atomic leader election prevents this

---

# Phase 1: Service Registry Multi-Instance Support (P1 - CRITICAL)

## Problem Statement

Current service registry uses service name as the key, causing collisions when multiple instances register the same service:

```redis
# Host 1 registers
HSET service:registry:api {pid: 12345, host: "host1", port: 8000}

# Host 2 registers - OVERWRITES Host 1!
HSET service:registry:api {pid: 67890, host: "host2", port: 8000}
```

**Result**: Only one instance is discoverable at a time.

## Design Solution

Use instance-aware keys while maintaining backward compatibility.

### New Redis Key Structure

```
# Instance-specific service info
service:instance:{instance_id}:{service_name}
  → Hash with {pid, host, port, started_at, status, ...}

# Service type registry (for discovery)
service:type:{service_name}:instances
  → Set of instance_ids providing this service

# Backward compatibility (optional)
service:registry:{service_name}
  → Hash pointing to "primary" instance for simple lookups
```

### Architecture

```
Instance 1 (host1)                 Instance 2 (host2)
       ↓                                   ↓
   Register API                        Register API
       ↓                                   ↓
service:instance:inst1:api        service:instance:inst2:api
       ↓                                   ↓
       └──────────→ Redis ←───────────────┘
                      ↓
        service:type:api:instances
             {inst1, inst2}
```

### Implementation Details

**1. Update SmartProcessManager.register_service()**

**File**: `src/gleitzeit/core/process_manager.py`

**Current Code** (lines 1264-1273):
```python
async def register_service(self, name: str, info: Dict):
    """Add persistent service registration with shorter TTL for heartbeat"""
    if not self.redis:
        await self.initialize()

    key = f"service:registry:{name}"  # ← PROBLEM: Same for all instances
    await self.redis.hset(key, mapping=info)
    await self.redis.expire(key, 60)
    logger.info(f"Registered service {name} in registry with 60s TTL")
```

**New Code**:
```python
async def register_service(self, name: str, info: Dict):
    """
    Register service with instance-aware keys for multi-instance support.

    Args:
        name: Service name (api, ui, worker_task_execution, etc)
        info: Service metadata (pid, host, port, etc)
    """
    if not self.redis:
        await self.initialize()

    instance_id = self.instance.instance_id

    # Add instance_id to info for tracking
    info['instance_id'] = instance_id
    info['registered_at'] = datetime.utcnow().isoformat()

    # 1. Store instance-specific service info
    instance_key = f"service:instance:{instance_id}:{name}"
    await self.redis.hset(instance_key, mapping=info)
    await self.redis.expire(instance_key, 60)  # 60s TTL, refreshed by heartbeat

    # 2. Add to service type registry for discovery
    type_key = f"service:type:{name}:instances"
    await self.redis.sadd(type_key, instance_id)
    await self.redis.expire(type_key, 120)  # Longer TTL for discovery

    # 3. Backward compatibility: Update single registry key to point to "first" instance
    compat_key = f"service:registry:{name}"
    exists = await self.redis.exists(compat_key)
    if not exists:
        # Only set if not exists (first instance wins for backward compat)
        await self.redis.hset(compat_key, mapping=info)
        await self.redis.expire(compat_key, 60)

    logger.info(
        f"Registered service {name} for instance {instance_id} "
        f"(host: {info.get('host')}, port: {info.get('port')})"
    )
```

**2. Update get_registered_services() to Return All Instances**

**Current Code** (lines 1275-1316):
```python
async def get_registered_services(self) -> Dict:
    """Get all registered services"""
    # ... scans service:registry:* keys ...
    # Returns {service_name: info}
```

**New Code**:
```python
async def get_registered_services(self) -> Dict[str, List[Dict]]:
    """
    Get all registered services across all instances.

    Returns:
        Dict mapping service_name to list of instance info dicts
        Example: {
            "api": [
                {instance_id: "inst1", host: "host1", port: 8000, ...},
                {instance_id: "inst2", host: "host2", port: 8000, ...}
            ],
            "ui": [...]
        }
    """
    if not self.redis:
        await self.initialize()

    services = {}

    try:
        # Scan for all instance-specific service keys
        async for key in self.redis.scan_iter(match="service:instance:*"):
            key_str = key.decode() if isinstance(key, bytes) else key

            # Parse: service:instance:{instance_id}:{service_name}
            parts = key_str.split(":")
            if len(parts) >= 4:
                instance_id = parts[2]
                service_name = ":".join(parts[3:])  # Handle service names with colons

                # Get service info
                info_raw = await self.redis.hgetall(key_str)
                info = {
                    k.decode() if isinstance(k, bytes) else k:
                    v.decode() if isinstance(v, bytes) else v
                    for k, v in info_raw.items()
                }

                # Validate process is still running
                if 'pid' in info:
                    try:
                        pid = int(info['pid'])
                        os.kill(pid, 0)  # Check if process exists

                        # Add to services dict
                        if service_name not in services:
                            services[service_name] = []
                        services[service_name].append(info)

                    except (OSError, ValueError):
                        # Process is dead, clean up
                        logger.info(f"Cleaning up dead service {service_name} from instance {instance_id}")
                        await self.redis.delete(key_str)
                        await self.redis.srem(f"service:type:{service_name}:instances", instance_id)

    except Exception as e:
        logger.error(f"Error scanning service registry: {e}")

    return services


async def get_service_instances(self, service_name: str) -> List[Dict]:
    """
    Get all instances of a specific service.

    Args:
        service_name: Name of service (api, ui, etc)

    Returns:
        List of instance info dicts
    """
    if not self.redis:
        await self.initialize()

    instances = []

    # Get all instance IDs for this service
    type_key = f"service:type:{service_name}:instances"
    instance_ids = await self.redis.smembers(type_key)

    for instance_id_bytes in instance_ids:
        instance_id = instance_id_bytes.decode() if isinstance(instance_id_bytes, bytes) else instance_id_bytes

        # Get instance info
        instance_key = f"service:instance:{instance_id}:{service_name}"
        info_raw = await self.redis.hgetall(instance_key)

        if info_raw:
            info = {
                k.decode() if isinstance(k, bytes) else k:
                v.decode() if isinstance(v, bytes) else v
                for k, v in info_raw.items()
            }
            instances.append(info)

    return instances
```

**3. Update unregister_service()**

**Current Code** (lines 1318-1325):
```python
async def unregister_service(self, name: str):
    """Remove service from registry"""
    if not self.redis:
        await self.initialize()

    key = f"service:registry:{name}"
    await self.redis.delete(key)
    logger.info(f"Unregistered service {name} from registry")
```

**New Code**:
```python
async def unregister_service(self, name: str):
    """
    Remove service from registry for this instance.

    Args:
        name: Service name to unregister
    """
    if not self.redis:
        await self.initialize()

    instance_id = self.instance.instance_id

    # 1. Remove instance-specific key
    instance_key = f"service:instance:{instance_id}:{name}"
    await self.redis.delete(instance_key)

    # 2. Remove from service type registry
    type_key = f"service:type:{name}:instances"
    await self.redis.srem(type_key, instance_id)

    # 3. Clean up empty type registry
    remaining = await self.redis.scard(type_key)
    if remaining == 0:
        await self.redis.delete(type_key)

    logger.info(f"Unregistered service {name} for instance {instance_id}")
```

**4. Update AsyncServiceManager to Use Instance-Aware Registry**

**File**: `src/gleitzeit/core/async_process_manager.py`

**Modify** `_init_smart_manager()` (lines 406-459):

```python
async def _init_smart_manager(self):
    """Initialize SmartProcessManager for service registry"""
    from .process_manager import SmartProcessManager
    from .instance import initialize_instance, get_current_instance

    try:
        # Initialize instance if not already done
        if not get_current_instance():
            # Generate unique instance ID based on hostname + process
            import socket
            hostname = socket.gethostname()
            instance_name = f"{hostname}-{os.getpid()}"

            initialize_instance(
                instance_name=instance_name,
                role="standalone",
                port_offset=0
            )
            logger.info(f"Initialized instance identity: {instance_name}")

        self.smart_manager = SmartProcessManager(config=self.config, redis_url=self.redis_url)
        await self.smart_manager.initialize()

        # Check for existing services FOR THIS HOST
        all_services = await self.smart_manager.get_registered_services()

        # Filter to only services running on THIS host
        import socket
        local_hostname = socket.gethostname()
        local_hosts = ['localhost', '127.0.0.1', local_hostname]

        self.existing_services = {}

        for service_name, instances in all_services.items():
            for instance_info in instances:
                instance_host = instance_info.get('host', 'localhost')

                # Only consider services on THIS host for attachment
                if instance_host in local_hosts:
                    pid = int(instance_info.get('pid', 0))

                    # Validate process is still running
                    import psutil
                    if pid and psutil.pid_exists(pid):
                        proc = psutil.Process(pid)
                        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                            self.existing_services[service_name] = instance_info
                            logger.info(f"  ✅ {service_name} (PID: {pid}) is healthy on this host")
                        else:
                            logger.info(f"  ❌ {service_name} (PID: {pid}) is zombie/dead")
                            await self.smart_manager.unregister_service(service_name)
                    else:
                        logger.info(f"  ❌ {service_name} has invalid PID")
                        await self.smart_manager.unregister_service(service_name)

        if self.existing_services:
            logger.info(f"Found {len(self.existing_services)} healthy services on this host")

    except Exception as e:
        import traceback
        logger.warning(f"Failed to initialize SmartProcessManager: {e}")
        logger.warning(f"Traceback: {traceback.format_exc()}")
        self.smart_manager = None
```

### New API Endpoints for Service Discovery

**File**: `src/gleitzeit/api/routes/services.py` (NEW FILE)

```python
"""
Service discovery API endpoints.

Provides APIs for discovering all service instances across the cluster.
"""

from fastapi import APIRouter, Depends
from typing import Dict, List
import redis.asyncio as aioredis

from ..dependencies import get_redis
from ...core.process_manager import SmartProcessManager

router = APIRouter(prefix="/services", tags=["services"])


@router.get("/discover/{service_name}")
async def discover_service(service_name: str, redis: aioredis.Redis = Depends(get_redis)) -> List[Dict]:
    """
    Discover all instances of a specific service.

    Args:
        service_name: Name of service (api, ui, worker_task_execution, etc)

    Returns:
        List of instance info:
        [
            {
                instance_id: "host1-12345",
                host: "host1.example.com",
                port: 8000,
                pid: 12345,
                started_at: "2025-10-13T10:00:00",
                status: "running"
            },
            ...
        ]
    """
    manager = SmartProcessManager(redis_url=str(redis.connection_pool.connection_kwargs.get('host')))
    await manager.initialize()

    instances = await manager.get_service_instances(service_name)
    return instances


@router.get("/discover")
async def discover_all_services(redis: aioredis.Redis = Depends(get_redis)) -> Dict[str, List[Dict]]:
    """
    Discover all services across all instances.

    Returns:
        Dict mapping service names to lists of instances:
        {
            "api": [{instance_id: ..., host: ..., ...}, ...],
            "ui": [...],
            "worker_task_execution": [...]
        }
    """
    manager = SmartProcessManager(redis_url=str(redis.connection_pool.connection_kwargs.get('host')))
    await manager.initialize()

    services = await manager.get_registered_services()
    return services


@router.get("/health")
async def cluster_health(redis: aioredis.Redis = Depends(get_redis)) -> Dict:
    """
    Get health status of all services across the cluster.

    Returns:
        {
            total_instances: 5,
            services: {
                "api": {count: 2, healthy: 2, unhealthy: 0},
                "ui": {count: 2, healthy: 2, unhealthy: 0},
                "worker_task_execution": {count: 3, healthy: 3, unhealthy: 0}
            },
            unhealthy_instances: []
        }
    """
    manager = SmartProcessManager(redis_url=str(redis.connection_pool.connection_kwargs.get('host')))
    await manager.initialize()

    all_services = await manager.get_registered_services()

    health = {
        "total_instances": 0,
        "services": {},
        "unhealthy_instances": []
    }

    for service_name, instances in all_services.items():
        healthy_count = len(instances)
        health["total_instances"] += healthy_count
        health["services"][service_name] = {
            "count": healthy_count,
            "healthy": healthy_count,
            "unhealthy": 0
        }

    return health
```

### Files to Modify

1. **src/gleitzeit/core/process_manager.py**
   - `register_service()` - Use instance-aware keys
   - `get_registered_services()` - Return all instances
   - `get_service_instances()` - NEW method
   - `unregister_service()` - Clean up instance-specific keys

2. **src/gleitzeit/core/async_process_manager.py**
   - `_init_smart_manager()` - Filter services by host
   - `_refresh_service_registrations()` - Update to use new keys

3. **src/gleitzeit/api/routes/services.py** (NEW)
   - Service discovery endpoints

4. **src/gleitzeit/api/main.py**
   - Register services router

### Testing

```python
# Test 1: Single Instance
# Start one instance
# Expected: Service registered with instance ID
# redis-cli: KEYS "service:instance:*" shows one entry

# Test 2: Two Instances, Same Host
# Start two instances
# Expected: Both have different instance IDs
# Expected: Both services visible in discovery API

# Test 3: Two Instances, Different Hosts (simulated)
# Start two instances with different instance IDs
# Expected: Both registered separately
# Expected: GET /services/discover/api returns both

# Test 4: Instance Failure
# Start two instances, kill one
# Expected: Dead instance cleaned up within 60s (TTL)
# Expected: Remaining instance still discoverable
```

---

# Phase 2: Sharding Configuration Validation (P2 - HIGH)

## Problem Statement

The `default_sharding` singleton uses a hardcoded `num_shards=16`. If different instances use different values, workflows will be routed to wrong shards causing corruption.

**Current Code**: [sharding.py:259](src/gleitzeit/core/sharding.py#L259)
```python
default_sharding = ClusterShardingStrategy(num_shards=16)
```

## Design Solution

Store sharding configuration in Redis and validate all instances use the same config.

### Implementation Details

**1. Add Configuration Validation on Startup**

**File**: `src/gleitzeit/core/async_process_manager.py`

Add method:
```python
async def _validate_sharding_config(self):
    """
    Ensure all instances use the same sharding configuration.

    Raises:
        ConfigurationError: If sharding config doesn't match cluster
    """
    from .sharding import default_sharding
    import redis.asyncio as aioredis

    # Connect to Redis
    redis = aioredis.from_url(self.redis_url)

    try:
        config_key = "global:config:sharding:num_shards"

        # Get stored configuration
        stored_shards = await redis.get(config_key)

        if stored_shards:
            stored_shards = int(stored_shards)

            if stored_shards != default_sharding.num_shards:
                raise ConfigurationError(
                    f"Sharding configuration mismatch!\n"
                    f"  This instance: {default_sharding.num_shards} shards\n"
                    f"  Cluster expects: {stored_shards} shards\n"
                    f"  CRITICAL: All instances must use the same num_shards value.\n"
                    f"  Fix: Update gleitzeit.yaml or clear Redis to reset cluster config."
                )
            else:
                logger.info(f"✅ Sharding config validated: {default_sharding.num_shards} shards")
        else:
            # First instance - store configuration
            await redis.set(config_key, str(default_sharding.num_shards))
            # Don't expire - this is permanent cluster config
            logger.info(
                f"📝 Stored sharding config in cluster: {default_sharding.num_shards} shards "
                f"(first instance)"
            )
    finally:
        await redis.close()


class ConfigurationError(Exception):
    """Raised when instance configuration doesn't match cluster"""
    pass
```

**2. Call Validation in start_all()**

**File**: `src/gleitzeit/core/async_process_manager.py`

Modify `start_all()` (around line 747):
```python
async def start_all(self, ...):
    """Start all services"""

    # CRITICAL: Validate sharding config before starting anything
    try:
        await self._validate_sharding_config()
    except ConfigurationError as e:
        logger.error(f"Configuration validation failed: {e}")
        raise

    # Initialize SmartProcessManager for service registry
    await self._init_smart_manager()

    # ... rest of startup ...
```

### Files to Modify

1. **src/gleitzeit/core/async_process_manager.py**
   - Add `_validate_sharding_config()` method
   - Call it in `start_all()` before any services start
   - Add `ConfigurationError` exception class

### Testing

```bash
# Test 1: First Instance
# Start instance
# Expected: Stores num_shards=16 in Redis
# redis-cli: GET global:config:sharding:num_shards → "16"

# Test 2: Second Instance (Matching Config)
# Start second instance with num_shards=16
# Expected: Validation passes, instance starts

# Test 3: Mismatched Config
# Manually set: redis-cli SET global:config:sharding:num_shards 8
# Start instance with num_shards=16
# Expected: ConfigurationError raised, instance fails to start
# Expected: Clear error message explaining the mismatch
```

---

# Phase 3: Enhanced Health Checking (P3 - MEDIUM)

## Problem Statement

Current heartbeat only refreshes services in the local process list. It doesn't:
- Check services on other hosts
- Clean up stale entries proactively
- Provide cross-instance health visibility

## Design Solution

Add distributed health checking with proper coordination.

### Implementation Details

**1. Add Health Check Method**

**File**: `src/gleitzeit/core/async_process_manager.py`

```python
async def _perform_health_check(self):
    """
    Perform distributed health check of all registered services.

    - Validates PIDs are still running
    - Cleans up stale registrations
    - Updates health metrics
    """
    if not self.smart_manager:
        return

    all_services = await self.smart_manager.get_registered_services()

    health_status = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_instances": 0,
        "healthy_instances": 0,
        "unhealthy_instances": 0,
        "services": {}
    }

    for service_name, instances in all_services.items():
        service_health = {
            "total": len(instances),
            "healthy": 0,
            "unhealthy": 0,
            "instances": []
        }

        for instance_info in instances:
            instance_id = instance_info.get('instance_id')
            pid = int(instance_info.get('pid', 0))
            host = instance_info.get('host')

            # Check if instance is on this host (can validate PID)
            import socket
            local_hostname = socket.gethostname()
            is_local = host in ['localhost', '127.0.0.1', local_hostname]

            if is_local and pid:
                # Local instance - check PID
                try:
                    import psutil
                    if psutil.pid_exists(pid):
                        proc = psutil.Process(pid)
                        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                            service_health["healthy"] += 1
                            service_health["instances"].append({
                                "instance_id": instance_id,
                                "host": host,
                                "status": "healthy"
                            })
                        else:
                            service_health["unhealthy"] += 1
                            service_health["instances"].append({
                                "instance_id": instance_id,
                                "host": host,
                                "status": "zombie"
                            })
                            # Clean up zombie
                            await self.smart_manager.unregister_service(service_name)
                    else:
                        service_health["unhealthy"] += 1
                        service_health["instances"].append({
                            "instance_id": instance_id,
                            "host": host,
                            "status": "dead"
                        })
                        # Clean up dead
                        await self.smart_manager.unregister_service(service_name)
                except Exception as e:
                    logger.warning(f"Error checking {service_name} on {host}: {e}")
            else:
                # Remote instance - trust TTL for now
                # TODO: Add cross-host health checks via HTTP/gRPC
                service_health["healthy"] += 1
                service_health["instances"].append({
                    "instance_id": instance_id,
                    "host": host,
                    "status": "unknown (remote)"
                })

        health_status["services"][service_name] = service_health
        health_status["total_instances"] += service_health["total"]
        health_status["healthy_instances"] += service_health["healthy"]
        health_status["unhealthy_instances"] += service_health["unhealthy"]

    # Store health status in Redis for monitoring
    if self.smart_manager:
        health_key = "global:cluster:health"
        await self.smart_manager.redis.set(
            health_key,
            json.dumps(health_status),
            ex=120  # 2 minute TTL
        )

    # Log summary
    logger.info(
        f"Health check: {health_status['healthy_instances']}/{health_status['total_instances']} "
        f"instances healthy"
    )

    return health_status
```

**2. Add Health Check to Monitor Loop**

**File**: `src/gleitzeit/core/async_process_manager.py`

Modify `monitor_loop()` (around line 912):
```python
async def monitor_loop(self, auto_restart=True):
    """Monitor services and restart if needed"""
    restart_attempts = {}
    max_restart_attempts = 3
    health_check_interval = 60  # Health check every 60 seconds

    # Start heartbeat task
    heartbeat_task = asyncio.create_task(self._service_heartbeat_loop())

    last_health_check = 0

    try:
        while True:
            status = await self.process_manager.monitor_processes()

            # Periodic distributed health check
            now = time.time()
            if now - last_health_check > health_check_interval:
                try:
                    await self._perform_health_check()
                    last_health_check = now
                except Exception as e:
                    logger.error(f"Health check failed: {e}")

            # ... existing restart logic ...

            await asyncio.sleep(5)
    finally:
        # ... existing cleanup ...
```

### Files to Modify

1. **src/gleitzeit/core/async_process_manager.py**
   - Add `_perform_health_check()` method
   - Modify `monitor_loop()` to call health checks periodically

2. **src/gleitzeit/api/routes/services.py** (from Phase 1)
   - Add `/health` endpoint that reads from `global:cluster:health`

### Testing

```python
# Test 1: All Healthy
# Start 3 instances
# Call /services/health
# Expected: All instances reported as healthy

# Test 2: One Dies
# Start 3 instances, kill one
# Wait 60 seconds for health check
# Call /services/health
# Expected: Dead instance removed from registry
# Expected: Only 2 instances reported

# Test 3: Cross-Host (Simulated)
# Start instances with different hostnames
# Expected: Remote instances marked as "unknown (remote)"
# Expected: Local instances checked via PID
```

---

# Implementation Order

## Phase 0: Loki Exporter (CRITICAL - Do First)
**Effort**: 2-4 hours
**Blockers**: None
**Files**: loki_exporter_worker.py

✅ Can be implemented and tested independently

## Phase 1: Service Registry (CRITICAL - Do Second)
**Effort**: 4-6 hours
**Blockers**: None
**Files**: process_manager.py, async_process_manager.py, services.py (new)

✅ Can be implemented and tested independently

## Phase 2: Sharding Validation (HIGH - Do Third)
**Effort**: 1-2 hours
**Blockers**: None
**Files**: async_process_manager.py

✅ Quick win, minimal risk

## Phase 3: Health Checking (MEDIUM - Optional)
**Effort**: 4-6 hours
**Blockers**: Requires Phase 1 (service registry)
**Files**: async_process_manager.py

⚠️ Can be deferred to later release

---

# Testing Strategy

## Unit Tests

```python
# test_leader_election_loki.py
async def test_loki_single_instance():
    """Single instance should become leader"""

async def test_loki_two_instances():
    """Two instances, one leader"""

async def test_loki_failover():
    """Leader dies, follower takes over"""

# test_service_registry.py
async def test_register_single_instance():
    """Register service for single instance"""

async def test_register_multiple_instances():
    """Register same service from multiple instances"""

async def test_discover_all_instances():
    """Discover all instances of a service"""

async def test_unregister_cleans_up():
    """Unregister removes instance-specific keys"""

# test_sharding_validation.py
async def test_first_instance_stores_config():
    """First instance stores sharding config"""

async def test_matching_config_passes():
    """Second instance with matching config succeeds"""

async def test_mismatched_config_fails():
    """Instance with different config raises error"""
```

## Integration Tests

```bash
# test_multi_instance.sh

# Test 1: Same host, multiple instances
echo "Starting first instance..."
gleitzeit serve &
PID1=$!
sleep 5

echo "Starting second instance..."
gleitzeit serve &
PID2=$!
sleep 5

echo "Checking services..."
curl http://localhost:8000/services/discover/api
# Expected: 1 API instance (attached mode)

kill $PID1 $PID2

# Test 2: Different hosts (simulated with different instance IDs)
# TODO: Add Docker Compose test with multiple containers
```

## Load Tests

```python
# test_load_multi_instance.py

async def test_load_distributed():
    """Submit 1000 workflows with 3 worker instances"""
    # Expected: Load balanced across workers
    # Expected: No duplicate executions
    # Expected: All workflows complete successfully
```

---

# Rollout Plan

## Stage 1: Development (Week 1)
- Implement Phase 0 (Loki)
- Implement Phase 1 (Service Registry)
- Implement Phase 2 (Sharding Validation)
- Unit tests for all phases

## Stage 2: Testing (Week 2)
- Integration tests
- Load tests
- Multi-host Docker Compose testing
- Kubernetes testing

## Stage 3: Documentation (Week 2)
- Update DEPLOYMENT.md with multi-instance patterns
- Add Kubernetes examples
- Add Docker Compose examples
- Update API documentation

## Stage 4: Release (Week 3)
- Merge to main
- Tag release 0.0.8
- Release notes highlighting horizontal scaling support

---

# Backward Compatibility

## Redis Key Migration

**Old keys** (for backward compatibility):
```
service:registry:{name}
```

**New keys**:
```
service:instance:{instance_id}:{name}
service:type:{name}:instances
```

**Strategy**: Maintain both key formats for 1 release cycle
- New code writes to both old and new keys
- New code reads from new keys primarily, falls back to old
- Deprecation notice in release notes
- Remove old keys in 0.0.9

## API Compatibility

**Old API** (still works):
```
GET /health
```

**New APIs**:
```
GET /services/discover/{service_name}
GET /services/discover
GET /services/health
```

---

# Success Criteria

## Must Have (Before Merge)
- ✅ Loki exporter has leader election
- ✅ Multiple instances can run on different hosts
- ✅ Service discovery shows all instances
- ✅ Sharding config validation prevents mismatches
- ✅ All unit tests pass
- ✅ Integration tests pass for 2-3 instances

## Nice to Have (Can Defer)
- ⏸️ Enhanced health checking (Phase 3)
- ⏸️ Cross-host PID validation
- ⏸️ Grafana dashboard for cluster health
- ⏸️ Automatic failover orchestration

---

# Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Breaking existing deployments | LOW | HIGH | Maintain backward compatibility |
| Performance degradation | LOW | MEDIUM | Benchmark before/after |
| Redis connection failures | MEDIUM | HIGH | Circuit breaker already implemented |
| Split-brain scenarios | LOW | HIGH | Atomic Lua scripts prevent this |
| TTL expiry during network issues | MEDIUM | MEDIUM | Use longer TTLs (60s+ with heartbeat) |

---

# Questions for Review

1. **Instance ID Generation**: Should we use hostname+PID or UUID?
   - **Recommendation**: hostname+PID for debuggability

2. **Service Registry TTL**: 60s or 120s?
   - **Recommendation**: 60s with 30s heartbeat (2x safety margin)

3. **Backward Compatibility Duration**: 1 release or 2?
   - **Recommendation**: 1 release (0.0.8 supports both, 0.0.9 removes old keys)

4. **Health Checking Scope**: Include Phase 3 or defer?
   - **Recommendation**: Defer to 0.0.9 - Phases 0-2 are sufficient for MVP

---

**End of Design Document**
