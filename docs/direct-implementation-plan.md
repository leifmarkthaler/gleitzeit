# Direct Multi-Machine Implementation Plan (No Migration)

## Executive Summary
Since Gleitzeit 0.0.7 is not in production, we can implement the Redis-based multi-machine support directly without migration complexity. This simplified plan focuses on building the right architecture from the start.

## Implementation Approach

```
Week 1-2: Core Infrastructure
├── Redis-based port management
├── Machine-aware instance identity
└── Service registry

Week 3-4: Multi-Machine Features
├── Machine registry
├── Service discovery API
└── Multi-instance support

Week 5: Testing & Polish
├── Enhanced monitoring
├── Integration testing
└── Documentation
```

---

## Week 1-2: Core Infrastructure

### Task 1.1: Replace File-Based Port Manager
**File:** `src/gleitzeit/core/ports.py` (REPLACE)

```python
import redis.asyncio as aioredis
import json
from typing import Optional, Dict
from datetime import datetime

class PortManager:
    """Redis-based distributed port management"""

    DEFAULT_PORTS = {
        "api": 8000,
        "ui": 8004,
        "metrics": 9090,
        "health": 8080,
    }

    def __init__(self, redis_client: aioredis.Redis, instance):
        self.redis = redis_client
        self.instance = instance
        self.machine_id = instance.machine_id
        self.port_ttl = 300  # 5 minutes

    async def get_service_port(self, service_name: str) -> int:
        """Get port for a service with Redis-based allocation"""

        # Check if already allocated for this instance
        port_key = f"port:allocated:{self.machine_id}:{service_name}"
        existing = await self.redis.get(port_key)

        if existing:
            data = json.loads(existing)
            return data['port']

        # Allocate new port
        base_port = self.DEFAULT_PORTS.get(service_name, 8000)
        port = base_port + self.instance.port_offset

        # Try to claim the port atomically
        allocation_key = f"port:allocated:{self.machine_id}:{port}"

        # Lua script for atomic allocation
        script = """
        local key = KEYS[1]
        local data = ARGV[1]
        local ttl = ARGV[2]

        if redis.call('EXISTS', key) == 0 then
            redis.call('SET', key, data, 'EX', ttl)
            return 1
        end
        return 0
        """

        allocation_data = json.dumps({
            "instance_id": self.instance.instance_id,
            "service": service_name,
            "port": port,
            "machine": self.machine_id,
            "allocated_at": datetime.utcnow().isoformat()
        })

        success = await self.redis.eval(
            script, 1, allocation_key,
            allocation_data, str(self.port_ttl)
        )

        if success:
            # Also store service -> port mapping
            await self.redis.set(
                port_key,
                json.dumps({"port": port, "service": service_name}),
                ex=self.port_ttl
            )

            # Start TTL refresh task
            asyncio.create_task(self._refresh_ttl_loop(allocation_key, port_key))
            return port

        # Port taken, try next one
        return await self._find_next_available_port(service_name, port + 1)

    async def _refresh_ttl_loop(self, *keys):
        """Keep port allocation alive while service runs"""
        while True:
            await asyncio.sleep(self.port_ttl // 2)
            for key in keys:
                await self.redis.expire(key, self.port_ttl)
```

**Deliverables:**
- [x] Remove file-based port registry completely
- [x] Redis-based atomic port allocation
- [x] TTL refresh for active ports
- [x] Machine-scoped port allocation

### Task 1.2: Enhance Instance Identity
**File:** `src/gleitzeit/core/instance.py` (MODIFY)

```python
import socket
import hashlib
import netifaces

class InstanceIdentity:
    def __init__(self, instance_name: Optional[str] = None,
                 role: str = "standalone", port_offset: int = 0):

        # Existing fields
        self.instance_id = self._generate_instance_id(instance_name)
        self.instance_name = instance_name or self.instance_id[:8]
        self.role = role
        self.port_offset = port_offset

        # NEW: Machine awareness
        self.machine_id = socket.gethostname()
        self.machine_ip = self._get_machine_ip()
        self.machine_ip_internal = self._get_internal_ip()
        self.region = os.getenv('GLEITZEIT_REGION', 'default')
        self.zone = os.getenv('GLEITZEIT_ZONE', 'default')

    def _get_internal_ip(self) -> str:
        """Get internal IP for machine-to-machine communication"""
        # Prefer private IPs (10.x, 172.16-31.x, 192.168.x)
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in addrs:
                for addr in addrs[netifaces.AF_INET]:
                    ip = addr['addr']
                    if ip.startswith(('10.', '172.', '192.168.')):
                        return ip
        return self.machine_ip  # Fallback to primary IP
```

**Deliverables:**
- [x] Machine ID from hostname
- [x] Internal vs external IP detection
- [x] Region/zone configuration
- [x] No file dependencies

### Task 1.3: Update Process Manager
**File:** `src/gleitzeit/core/process_manager.py` (MODIFY)

```python
class SmartProcessManager:

    async def initialize(self):
        """Initialize with Redis-based systems"""

        # Register machine in Redis
        await self._register_machine()

        # Register instance
        await self._register_instance()

        # No file-based port manager!
        from .ports import PortManager
        self.port_manager = PortManager(self.redis, self.instance)

    async def _register_machine(self):
        """Register this machine in the cluster"""

        machine_info = {
            "hostname": self.instance.machine_id,
            "ip": self.instance.machine_ip,
            "ip_internal": self.instance.machine_ip_internal,
            "region": self.instance.region,
            "zone": self.instance.zone,
            "cpu_count": psutil.cpu_count(),
            "memory_gb": psutil.virtual_memory().total / (1024**3),
            "registered_at": datetime.utcnow().isoformat()
        }

        # Add to machine registry
        await self.redis.sadd("machine:registry", self.instance.machine_id)

        # Store machine info
        await self.redis.hset(
            f"machine:{self.instance.machine_id}:info",
            mapping={k: str(v) for k, v in machine_info.items()}
        )

        # Set TTL and start heartbeat
        await self.redis.expire(f"machine:{self.instance.machine_id}:info", 600)
        asyncio.create_task(self._machine_heartbeat())

    async def _machine_heartbeat(self):
        """Keep machine registration alive"""
        while True:
            await asyncio.sleep(300)  # 5 minutes
            await self.redis.expire(
                f"machine:{self.instance.machine_id}:info", 600
            )
            await self.redis.hset(
                f"machine:{self.instance.machine_id}:info",
                "last_heartbeat", datetime.utcnow().isoformat()
            )

    async def claim_service(self, service_name: str, port: int):
        """Machine-scoped service ownership"""

        # Machine-scoped ownership key
        ownership_key = f"service:ownership:{self.instance.machine_id}:{service_name}"

        # Check for conflicts on THIS MACHINE only
        existing = await self.redis.get(ownership_key)
        if existing:
            owner = json.loads(existing)
            if owner['instance_id'] != self.instance.instance_id:
                logger.warning(f"Service {service_name} already owned on this machine")
                return False

        # Claim ownership
        ownership_info = {
            "instance_id": self.instance.instance_id,
            "machine": self.instance.machine_id,
            "port": port,
            "claimed_at": datetime.utcnow().isoformat()
        }

        await self.redis.set(ownership_key, json.dumps(ownership_info), ex=300)

        # Register in global service instances
        await self.redis.sadd(
            f"service:instances:{service_name}",
            f"{self.instance.machine_id}:{self.instance.instance_id}"
        )

        # Store service endpoint for discovery
        endpoint_key = f"service:endpoint:{self.instance.machine_id}:{self.instance.instance_id}:{service_name}"
        endpoint_info = {
            "url": f"http://{self.instance.machine_ip}:{port}",
            "internal_url": f"http://{self.instance.machine_ip_internal}:{port}",
            "port": port,
            "machine": self.instance.machine_id,
            "region": self.instance.region,
            "healthy": True
        }

        await self.redis.hset(endpoint_key, mapping={
            k: str(v) for k, v in endpoint_info.items()
        })
        await self.redis.expire(endpoint_key, 300)

        # Add to service type registry for this machine
        await self.redis.sadd(
            f"service:registry:{service_name}",
            f"{self.instance.machine_id}:{self.instance.instance_id}"
        )

        return True
```

**Deliverables:**
- [x] Machine registration in Redis
- [x] Machine heartbeat mechanism
- [x] Machine-scoped service ownership
- [x] Service endpoint storage for discovery

---

## Week 3-4: Multi-Machine Features

### Task 2.1: Service Discovery API
**File:** `src/gleitzeit/api/routers/discovery.py` (NEW)

```python
from fastapi import APIRouter, Query
from typing import Optional, List
import redis.asyncio as aioredis

router = APIRouter(prefix="/discovery", tags=["discovery"])

@router.get("/services/{service_type}")
async def discover_services(
    service_type: str,
    region: Optional[str] = Query(None),
    healthy_only: bool = Query(True)
):
    """Discover all instances of a service type across all machines"""

    redis = aioredis.from_url("redis://localhost:6379")
    instances = []

    # Get all service instances
    instance_keys = await redis.smembers(f"service:instances:{service_type}")

    for instance_key in instance_keys:
        machine_id, instance_id = instance_key.decode().split(":")

        # Get endpoint info
        endpoint_key = f"service:endpoint:{machine_id}:{instance_id}:{service_type}"
        endpoint_info = await redis.hgetall(endpoint_key)

        if not endpoint_info:
            continue

        # Convert bytes to strings
        info = {k.decode(): v.decode() for k, v in endpoint_info.items()}

        # Apply filters
        if region and info.get('region') != region:
            continue

        if healthy_only and info.get('healthy') != 'True':
            continue

        instances.append({
            "machine": machine_id,
            "instance": instance_id,
            "url": info.get('url'),
            "internal_url": info.get('internal_url'),
            "port": int(info.get('port', 0)),
            "region": info.get('region', 'default'),
            "healthy": info.get('healthy') == 'True'
        })

    await redis.close()

    return {
        "service": service_type,
        "instances": instances,
        "count": len(instances)
    }

@router.get("/machines")
async def list_machines():
    """List all registered machines in the cluster"""

    redis = aioredis.from_url("redis://localhost:6379")
    machines = []

    machine_ids = await redis.smembers("machine:registry")

    for machine_id in machine_ids:
        info = await redis.hgetall(f"machine:{machine_id.decode()}:info")
        if info:
            machine_data = {k.decode(): v.decode() for k, v in info.items()}
            machines.append({
                "id": machine_id.decode(),
                "hostname": machine_data.get('hostname'),
                "ip": machine_data.get('ip'),
                "region": machine_data.get('region'),
                "cpu_count": int(machine_data.get('cpu_count', 0)),
                "memory_gb": float(machine_data.get('memory_gb', 0)),
                "last_heartbeat": machine_data.get('last_heartbeat')
            })

    await redis.close()

    return {"machines": machines, "count": len(machines)}
```

**Deliverables:**
- [x] Service discovery endpoint
- [x] Machine listing endpoint
- [x] Region filtering
- [x] Health filtering

### Task 2.2: Update PS Command for Multi-Machine
**File:** `src/gleitzeit/cli/process_commands.py` (MODIFY)

```python
@process.command('ps')
@click.option('--machine', help='Filter by machine ID or hostname')
@click.option('--region', help='Filter by region')
@click.option('--all-machines', is_flag=True, help='Show processes from all machines')
def ps(machine: Optional[str], region: Optional[str], all_machines: bool, ...):
    """Enhanced ps command for multi-machine"""

    asyncio.run(_ps_async(machine, region, all_machines, ...))

async def _get_processes(redis, machine_filter, region_filter, all_machines):
    """Get processes with multi-machine support"""

    processes = []

    # Determine which machines to query
    if all_machines:
        # Get all machines from registry
        machine_ids = await redis.smembers(b"machine:registry")
        machines_to_query = [m.decode() for m in machine_ids]
    else:
        # Default to current machine only
        current_instance = get_current_instance()
        machines_to_query = [current_instance.machine_id]

    # Apply machine filter
    if machine_filter:
        machines_to_query = [m for m in machines_to_query if machine_filter in m]

    # Get processes from each machine
    for machine_id in machines_to_query:
        # Get machine info for region filtering
        if region_filter:
            machine_info = await redis.hget(f"machine:{machine_id}:info".encode(), b"region")
            if machine_info and machine_info.decode() != region_filter:
                continue

        # Get all instances on this machine
        # ... existing instance discovery logic ...

        # Add machine info to each process
        for process in machine_processes:
            process['machine'] = machine_id[:15]  # Truncate for display
            process['region'] = await redis.hget(
                f"machine:{machine_id}:info".encode(), b"region"
            ) or b"default"
            processes.append(process)

    return processes

def _create_process_table(processes: List[Dict]) -> Table:
    """Create table with machine column"""

    table = Table(title="Gleitzeit Processes")

    table.add_column("NAME", style="cyan", width=15)
    table.add_column("INSTANCE", style="green", width=12)

    # NEW: Machine column if showing multiple machines
    if len(set(p.get('machine', '') for p in processes)) > 1:
        table.add_column("MACHINE", style="blue", width=15)
        table.add_column("REGION", style="yellow", width=8)

    table.add_column("PID", justify="right", width=8)
    table.add_column("PORT", justify="right", width=8)
    table.add_column("STATUS", width=10)
    table.add_column("UPTIME", width=10)

    # ... rest of table creation
```

**Deliverables:**
- [x] Multi-machine ps support
- [x] Machine and region filtering
- [x] Machine column in output
- [x] --all-machines flag

### Task 2.3: Update Worker Manager for Global Shards
**File:** `src/gleitzeit/core/worker_manager.py` (MODIFY)

```python
async def _assign_shards_to_worker(self, worker_name: str, ...):
    """Assign shards with global awareness"""

    # Store in Redis for persistence and global visibility
    await self.redis.set(
        f"worker:shards:{self.instance.machine_id}:{worker_name}",
        json.dumps(assigned_shards),
        ex=3600
    )

    # Register shard ownership globally
    for shard in assigned_shards:
        await self.redis.set(
            f"shard:owner:{shard}",
            json.dumps({
                "worker": worker_name,
                "machine": self.instance.machine_id,
                "instance": self.instance.instance_id,
                "assigned_at": datetime.utcnow().isoformat()
            }),
            ex=3600
        )
```

---

## Week 5: Testing & Polish

### Task 3.1: Integration Tests
**File:** `tests/test_multi_machine.py` (NEW)

```python
import pytest
import asyncio
from unittest.mock import Mock, patch

@pytest.mark.asyncio
async def test_port_allocation_multi_machine():
    """Test that same port can be allocated on different machines"""

    # Mock different machine IDs
    instance1 = Mock(machine_id="machine-a", instance_id="inst-1")
    instance2 = Mock(machine_id="machine-b", instance_id="inst-2")

    # Both should get port 8000 on their respective machines
    port1 = await manager1.get_service_port("api")
    port2 = await manager2.get_service_port("api")

    assert port1 == 8000
    assert port2 == 8000

@pytest.mark.asyncio
async def test_service_discovery():
    """Test service discovery across machines"""

    # Register services on different machines
    # ...

    # Discover should find all
    services = await discover_services("api")
    assert len(services["instances"]) == 2
    assert "machine-a" in [s["machine"] for s in services["instances"]]
    assert "machine-b" in [s["machine"] for s in services["instances"]]
```

### Task 3.2: Local Multi-Machine Testing
**File:** `docker-compose.test.yml` (NEW)

```yaml
version: '3.8'

services:
  redis:
    image: redis:7
    ports:
      - "6379:6379"

  machine-1:
    build: .
    environment:
      REDIS_URL: redis://redis:6379
      GLEITZEIT_REGION: us-east-1
      HOSTNAME: machine-1
    command: python -m gleitzeit.cli.main serve --instance-name prod-1

  machine-2:
    build: .
    environment:
      REDIS_URL: redis://redis:6379
      GLEITZEIT_REGION: us-west-2
      HOSTNAME: machine-2
    command: python -m gleitzeit.cli.main serve --instance-name prod-2

  machine-3:
    build: .
    environment:
      REDIS_URL: redis://redis:6379
      GLEITZEIT_REGION: eu-west-1
      HOSTNAME: machine-3
    command: python -m gleitzeit.cli.main serve --instance-name prod-3
```

### Task 3.3: Documentation
**File:** `docs/multi-machine-setup.md` (NEW)

- How to configure multi-machine deployment
- Environment variables needed
- Redis requirements
- Network setup
- Example deployments

---

## Testing Checklist

### Functional Tests
- [ ] Port allocation works on single machine
- [ ] Port allocation works across multiple machines
- [ ] Same port number allowed on different machines
- [ ] Service discovery finds all instances
- [ ] PS command shows all machines
- [ ] Machine failure handled gracefully

### Performance Tests
- [ ] Port allocation < 10ms
- [ ] Service discovery < 20ms
- [ ] PS command < 100ms for 10 machines

### Failure Scenarios
- [ ] Redis connection loss
- [ ] Machine network partition
- [ ] Port exhaustion
- [ ] Stale machine cleanup

---

## Benefits of Direct Implementation

1. **No Migration Complexity** - Start fresh with the right architecture
2. **No Legacy Code** - No hybrid managers or compatibility layers
3. **Faster Development** - 5 weeks instead of 10
4. **Cleaner Codebase** - No temporary migration code
5. **Immediate Testing** - Can test multi-machine from day 1

## Success Criteria

- ✅ File-based port manager completely removed
- ✅ Redis-based port allocation working
- ✅ Multiple machines can run same services
- ✅ Service discovery API functional
- ✅ PS command shows multi-machine view
- ✅ All tests passing

## Next Steps After Implementation

1. **Deploy test cluster** with 3+ machines
2. **Load test** with multiple instances
3. **Add monitoring** (Prometheus metrics)
4. **Create Helm charts** for Kubernetes deployment
5. **Add load balancer** configuration (HAProxy/NGINX)