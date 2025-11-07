# Port Locks to Redis: Multi-Machine Design & Audit

## Executive Summary
This document audits the current file-based port locking mechanism and designs a Redis-based distributed port coordination system for Gleitzeit 0.0.7, with a focus on **enabling multi-machine deployments**.

## Vision: Multi-Machine Gleitzeit

### Target Architecture
```
┌─────────────────────────────────────────────────────────┐
│                   Redis (Shared State)                   │
│  - Port allocations                                      │
│  - Service registry                                      │
│  - Shard assignments                                     │
│  - Instance discovery                                    │
└─────────────────────┬───────────────────────────────────┘
                      │
      ┌───────────────┼───────────────┬──────────────┐
      ▼               ▼               ▼              ▼
┌──────────┐    ┌──────────┐    ┌──────────┐   ┌──────────┐
│Machine A │    │Machine B │    │Machine C │   │Machine D │
│US-East-1 │    │US-West-2 │    │EU-West-1│   │AP-South │
├──────────┤    ├──────────┤    ├──────────┤   ├──────────┤
│API:8000  │    │API:8000  │    │Workers   │   │Dev:8100  │
│UI:8004   │    │UI:8004   │    │Shards 8-15│  │All Svcs  │
│Workers   │    │Workers   │    │          │   │          │
│Shards 0-3│    │Shards 4-7│    │          │   │          │
└──────────┘    └──────────┘    └──────────┘   └──────────┘
```

### Key Benefits of Multi-Machine
1. **Geographic Distribution** - Services close to users
2. **Fault Tolerance** - Survive machine/region failures
3. **Load Distribution** - Scale horizontally
4. **Resource Optimization** - Different machine types for different workloads
5. **Development Isolation** - Separate dev/staging/prod on different machines

## Current State Audit

### 1. File-Based Port Locking (`ports.py`)

**Current Implementation:**
```python
# Registry file at /tmp/gleitzeit_ports.json (LOCAL ONLY!)
self.registry_path = Path("/tmp/gleitzeit_ports.json")

# Structure:
{
  "instance-id-1": {
    "api": 8000,
    "ui": 8004
  },
  "instance-id-2": {
    "api": 8100,  // with port offset
    "ui": 8104
  }
}
```

**Problems Identified:**
1. ❌ **No Cross-Machine Coordination** - File at `/tmp/` is local only
2. ❌ **Race Conditions** - Multiple instances can read/write simultaneously
3. ❌ **No Atomic Operations** - Read-modify-write is not atomic
4. ❌ **Stale Data** - Dead instances leave port allocations
5. ❌ **No TTL/Expiry** - Ports remain "allocated" after crashes
6. ❌ **No Conflict Detection** - Can't detect if another machine uses same port
7. ❌ **Single Service Assumption** - `service:ownership:api` assumes ONE api globally

### 2. Service Ownership Problems

**Current Issue: Service Uniqueness Blocks Multi-Machine**
```python
# PROBLEM: This prevents multiple API servers on different machines!
if await redis.exists(f"service:ownership:{service_name}"):
    raise Exception("Service already owned")
```

**Impact:** Can't run multiple API servers even on different machines!

## Proposed Multi-Machine Redis Design

### Core Principles

1. **Machine-Aware** - All keys include machine identity
2. **Service Multiplicity** - Allow multiple instances of same service type
3. **Port Locality** - Same port number OK on different machines
4. **Global Discovery** - Find services across all machines
5. **Distributed Coordination** - Redis as single source of truth

### Redis Key Schema for Multi-Machine

```python
# 1. MACHINE REGISTRY
machine:registry -> SET ["machineA", "machineB", "machineC"]
machine:{machine_id}:info -> {
  "hostname": "prod-us-east-1.example.com",
  "ip": "10.0.1.5",
  "region": "us-east-1",
  "capabilities": {"cpu": 8, "memory": 32, "gpu": false}
}

# 2. PORT ALLOCATION (Machine-Scoped)
port:allocated:{machine_id}:{port} -> {
  "instance_id": "abc123",
  "service": "api",
  "allocated_at": "2024-01-01T12:00:00Z",
  "pid": 12345  # Process ID for verification
}
TTL: 300 seconds

# 3. SERVICE INSTANCES (Multiple per Service Type)
service:instances:{service_type} -> SET [
  "machineA:prod-api-1",
  "machineB:prod-api-2",
  "machineC:dev-api"
]

service:instance:{machine_id}:{instance_id} -> {
  "type": "api",
  "port": 8000,
  "started_at": "2024-01-01T12:00:00Z",
  "status": "running",
  "endpoint": "http://machineA.example.com:8000"
}

# 4. SHARD DISTRIBUTION (Global)
shard:owner:{shard_num} -> {
  "worker": "task-worker-0",
  "machine": "machineA",
  "instance": "prod-workers-1"
}

# 5. SERVICE DISCOVERY
service:endpoints:{service_type} -> [
  {
    "machine": "machineA",
    "instance": "prod-api-1",
    "endpoint": "http://10.0.1.5:8000",
    "region": "us-east-1",
    "healthy": true
  },
  {
    "machine": "machineB",
    "instance": "prod-api-2",
    "endpoint": "http://10.0.2.5:8000",
    "region": "us-west-2",
    "healthy": true
  }
]
```

### New Multi-Machine PortManager

```python
class MultiMachinePortManager:
    def __init__(self, redis_client, instance):
        self.redis = redis_client
        self.instance = instance
        self.machine_id = socket.gethostname()
        self.machine_ip = self._get_machine_ip()

    async def allocate_port(self, service_name: str, allow_shared: bool = False) -> int:
        """
        Allocate a port for a service on this machine.

        Args:
            service_name: Name of the service
            allow_shared: If True, allow same port on different machines
        """
        preferred = self.DEFAULT_PORTS[service_name] + self.instance.port_offset

        if allow_shared:
            # Multi-machine mode: scope by machine
            port_key = f"port:allocated:{self.machine_id}:{preferred}"
        else:
            # Single-machine mode: global port lock
            port_key = f"port:allocated:global:{preferred}"

        # Lua script for atomic allocation
        script = """
        local port_key = KEYS[1]
        local instance_id = ARGV[1]
        local service = ARGV[2]
        local machine = ARGV[3]
        local ttl = ARGV[4]

        -- Check if port is allocated on this machine
        local current = redis.call('GET', port_key)
        if current then
            local data = cjson.decode(current)
            if data.instance_id ~= instance_id then
                return nil  -- Port taken by another instance
            end
        end

        -- Allocate port
        local allocation = {
            instance_id = instance_id,
            service = service,
            machine = machine,
            allocated_at = ARGV[5]
        }

        redis.call('SET', port_key, cjson.encode(allocation), 'EX', ttl)

        -- Register in machine's port set
        redis.call('SADD', 'machine:' .. machine .. ':ports', ARGV[6])

        return ARGV[6]  -- Return the port number
        """

        result = await self.redis.eval(
            script, 1, port_key,
            self.instance.instance_id,
            service_name,
            self.machine_id,
            self.port_ttl,
            datetime.utcnow().isoformat(),
            str(preferred)
        )

        if result:
            # Register service endpoint for discovery
            await self._register_service_endpoint(service_name, int(result))
            return int(result)

        # Port taken, find alternative
        return await self._find_available_port(service_name)

    async def _register_service_endpoint(self, service_name: str, port: int):
        """Register service endpoint for discovery"""
        endpoint_info = {
            "machine": self.machine_id,
            "instance": self.instance.instance_id,
            "endpoint": f"http://{self.machine_ip}:{port}",
            "region": os.getenv("REGION", "default"),
            "started_at": datetime.utcnow().isoformat()
        }

        # Add to service instances set
        await self.redis.sadd(
            f"service:instances:{service_name}",
            f"{self.machine_id}:{self.instance.instance_id}"
        )

        # Store instance details
        await self.redis.hset(
            f"service:instance:{self.machine_id}:{self.instance.instance_id}",
            mapping=endpoint_info
        )
```

### Service Ownership Changes for Multi-Machine

```python
class MultiMachineProcessManager(SmartProcessManager):

    async def claim_service(self, service_name: str, port: int):
        """
        Claim service ownership (machine-scoped, not global)
        """
        # NEW: Machine-scoped ownership
        ownership_key = f"service:ownership:{self.machine_id}:{service_name}"

        # Check for conflicts ON THIS MACHINE ONLY
        existing = await self.redis.get(ownership_key)
        if existing:
            owner = json.loads(existing)
            if owner['instance_id'] != self.instance.instance_id:
                raise Exception(f"Service {service_name} already owned on this machine")

        # Claim ownership on this machine
        ownership_info = {
            "instance_id": self.instance.instance_id,
            "machine": self.machine_id,
            "port": port,
            "claimed_at": datetime.utcnow().isoformat()
        }

        await self.redis.set(ownership_key, json.dumps(ownership_info), ex=300)

        # Register in global service registry
        await self.redis.sadd(
            f"service:instances:{service_name}",
            f"{self.machine_id}:{self.instance.instance_id}"
        )

        # Register in service type registry (for load balancing)
        await self._update_service_registry(service_name, port)
```

### Worker Shard Distribution Across Machines

```python
class MultiMachineWorkerManager:

    async def assign_shards_globally(self):
        """
        Distribute shards across all available workers on all machines
        """
        # Get all workers across all machines
        all_workers = []
        machines = await self.redis.smembers("machine:registry")

        for machine in machines:
            workers = await self.redis.smembers(f"machine:{machine}:workers")
            for worker in workers:
                all_workers.append({"machine": machine, "worker": worker})

        # Distribute shards round-robin across all workers
        num_shards = 16
        for shard in range(num_shards):
            worker_index = shard % len(all_workers)
            worker_info = all_workers[worker_index]

            # Assign shard
            await self.redis.set(
                f"shard:owner:{shard}",
                json.dumps({
                    "worker": worker_info["worker"],
                    "machine": worker_info["machine"],
                    "assigned_at": datetime.utcnow().isoformat()
                }),
                ex=3600  # 1 hour TTL
            )
```

### Enhanced PS Command for Multi-Machine

```python
async def _get_processes_multi_machine(redis, instance_filter=None, machine_filter=None):
    """Get processes from all machines"""
    processes = []

    # Get all machines
    machines = await redis.smembers(b"machine:registry")

    for machine_id_bytes in machines:
        machine_id = machine_id_bytes.decode()

        # Apply machine filter if specified
        if machine_filter and machine_filter not in machine_id:
            continue

        # Get machine info
        machine_info = await redis.hgetall(f"machine:{machine_id}:info".encode())

        # Get all instances on this machine
        instance_ids = await redis.smembers(f"machine:{machine_id}:instances".encode())

        for instance_id_bytes in instance_ids:
            instance_id = instance_id_bytes.decode()

            # Apply instance filter if specified
            if instance_filter and instance_filter not in instance_id:
                continue

            # Get processes for this instance
            pattern = f"instance:{instance_id}:process:*"
            async for key in redis.scan_iter(match=pattern.encode()):
                process_data = await redis.hgetall(key)

                process_info = {
                    'name': key.decode().split(':')[-1],
                    'instance': instance_id[:12],  # Truncate for display
                    'machine': machine_id,
                    'region': machine_info.get(b'region', b'').decode(),
                    'pid': process_data.get(b'pid', b'').decode(),
                    'port': process_data.get(b'port', b'').decode(),
                    'status': process_data.get(b'status', b'').decode(),
                    # ... other fields
                }
                processes.append(process_info)

    return processes

# Enhanced table display
def _create_multi_machine_process_table(processes):
    table = Table(title="Gleitzeit Processes (Multi-Machine)")

    table.add_column("NAME", style="cyan", width=15)
    table.add_column("INSTANCE", style="green", width=12)
    table.add_column("MACHINE", style="blue", width=15)
    table.add_column("REGION", style="yellow", width=10)
    table.add_column("PID", justify="right", width=8)
    table.add_column("PORT", justify="right", width=8)
    table.add_column("STATUS", width=10)

    for proc in processes:
        table.add_row(
            proc['name'],
            proc['instance'],
            proc['machine'],
            proc['region'],
            str(proc['pid']),
            str(proc['port']) if proc['port'] else '-',
            proc['status']
        )

    return table
```

## Multi-Machine Deployment Scenarios

### Scenario 1: Geographic Distribution
```bash
# US East Coast
machine-a$ gleitzeit serve --instance-name "prod-east" \
    --services api,ui --region us-east-1

# US West Coast
machine-b$ gleitzeit serve --instance-name "prod-west" \
    --services api,ui --region us-west-2

# Europe
machine-c$ gleitzeit serve --instance-name "prod-eu" \
    --services api,ui,workers --region eu-west-1
```

### Scenario 2: Service Specialization
```bash
# API Machines (CPU optimized)
machine-api-1$ gleitzeit serve --instance-name "api-1" --services api,ui
machine-api-2$ gleitzeit serve --instance-name "api-2" --services api,ui

# Worker Machines (Memory optimized)
machine-worker-1$ gleitzeit serve --instance-name "workers-1" \
    --services workers --worker-count 8 --shards 0-7

machine-worker-2$ gleitzeit serve --instance-name "workers-2" \
    --services workers --worker-count 8 --shards 8-15
```

### Scenario 3: Dev/Staging/Prod Isolation
```bash
# Production machines
machine-prod$ gleitzeit serve --instance-name "prod" --port-offset 0

# Staging machine
machine-stage$ gleitzeit serve --instance-name "staging" --port-offset 100

# Development machine
machine-dev$ gleitzeit serve --instance-name "dev" --port-offset 200
```

## Load Balancer Integration

### Service Discovery API
```python
@app.get("/discovery/services/{service_type}")
async def discover_services(service_type: str):
    """Return all healthy instances of a service type"""
    instances = []

    # Get all service instances
    instance_keys = await redis.smembers(f"service:instances:{service_type}")

    for instance_key in instance_keys:
        machine_id, instance_id = instance_key.decode().split(":")

        # Get instance info
        info = await redis.hgetall(
            f"service:instance:{machine_id}:{instance_id}"
        )

        # Check health
        health = await check_health(info['endpoint'])

        instances.append({
            "endpoint": info['endpoint'],
            "machine": machine_id,
            "region": info.get('region', 'default'),
            "healthy": health,
            "weight": calculate_weight(info)  # For weighted load balancing
        })

    return {"service": service_type, "instances": instances}
```

### HAProxy Configuration Generator
```python
def generate_haproxy_config():
    """Generate HAProxy config from service discovery"""
    config = """
global
    daemon

defaults
    mode http
    timeout connect 5000
    timeout client 50000
    timeout server 50000

frontend api_frontend
    bind *:80
    default_backend api_servers

backend api_servers
    balance roundrobin
"""

    # Get API servers from Redis
    api_instances = redis.smembers("service:instances:api")

    for instance in api_instances:
        machine, instance_id = instance.split(":")
        info = redis.hgetall(f"service:instance:{machine}:{instance_id}")

        config += f"""
    server {machine}_{instance_id} {info['endpoint']} check
"""

    return config
```

## Migration Strategy for Multi-Machine

### Phase 1: Single Machine Compatibility
- Maintain backward compatibility
- Default to single-machine mode
- Add `--multi-machine` flag for new behavior

### Phase 2: Machine Registration
- Add machine discovery
- Implement machine-scoped port allocation
- Update service ownership logic

### Phase 3: Service Discovery
- Implement discovery API
- Add load balancer integration
- Update monitoring tools

### Phase 4: Full Distribution
- Enable cross-machine worker coordination
- Implement global shard rebalancing
- Add cross-region replication

## Network & Security Considerations

### Network Requirements
1. **Redis Connectivity** - All machines need Redis access
2. **Service Ports** - Machines need exposed service ports (or private network)
3. **Health Checks** - Load balancers need health check access
4. **Metrics Collection** - Prometheus/monitoring access

### Security Requirements
1. **Redis Auth** - Use Redis ACLs and TLS
2. **Network Isolation** - VPC/private networks
3. **Service Auth** - Inter-service authentication
4. **Audit Logging** - Log all cross-machine operations

## Testing Multi-Machine Deployments

### Local Testing with Docker
```yaml
# docker-compose.yml for multi-machine testing
version: '3.8'

services:
  redis:
    image: redis:7
    ports:
      - "6379:6379"

  machine-a:
    build: .
    environment:
      REDIS_URL: redis://redis:6379
      MACHINE_ID: machine-a
      REGION: us-east-1
    command: gleitzeit serve --instance-name prod-a

  machine-b:
    build: .
    environment:
      REDIS_URL: redis://redis:6379
      MACHINE_ID: machine-b
      REGION: us-west-2
    command: gleitzeit serve --instance-name prod-b
```

### Integration Tests
```python
@pytest.mark.asyncio
async def test_multi_machine_coordination():
    """Test multiple machines can coordinate"""

    # Start instances on different "machines"
    instance_a = await start_instance(machine_id="machine-a", port=8000)
    instance_b = await start_instance(machine_id="machine-b", port=8000)

    # Both should succeed (same port, different machines)
    assert instance_a.is_running()
    assert instance_b.is_running()

    # Verify service discovery finds both
    services = await discover_services("api")
    assert len(services) == 2
    assert "machine-a" in [s['machine'] for s in services]
    assert "machine-b" in [s['machine'] for s in services]
```

## Performance Impact

### Benefits
- **Horizontal Scaling** - Add machines for more capacity
- **Geographic Performance** - Services closer to users
- **Resource Optimization** - Right-sized machines for workloads

### Overhead
- **Redis Round Trips** - ~1-2ms for port allocation
- **Service Discovery** - ~5-10ms to find all instances
- **Health Checks** - Continuous background monitoring

## Success Metrics for Multi-Machine

1. **Multiple API servers running** on different machines
2. **Automatic service discovery** across machines
3. **Worker shards distributed** globally
4. **Zero port conflicts** even with same ports on different machines
5. **Failover capability** when a machine goes down
6. **Load balancer integration** working
7. **Cross-region latency < 100ms** for service discovery

## Conclusion

The Redis-based port lock system with multi-machine support will transform Gleitzeit from a single-machine orchestrator to a **truly distributed workflow engine**. Key advantages:

- ✅ **Geographic Distribution** - Run anywhere
- ✅ **Horizontal Scaling** - Add machines as needed
- ✅ **Fault Tolerance** - Survive machine failures
- ✅ **Service Discovery** - Automatic load balancing
- ✅ **Resource Optimization** - Different machines for different workloads

The implementation is backward compatible and can be rolled out gradually, making it a safe evolution of the current architecture.