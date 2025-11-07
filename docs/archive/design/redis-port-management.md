# Redis-Based Port Management

## Overview

The Redis-based port management system enables distributed port allocation across multiple machines and instances of Gleitzeit. It replaces the previous file-based system (`/tmp/gleitzeit_ports.json`) with a robust, scalable solution that supports multi-machine deployments.

## Architecture

### Key Components

1. **PortManager** (`/src/gleitzeit/core/ports.py`)
   - Async Redis-based port allocation
   - Machine-scoped port management
   - TTL-based resource cleanup
   - Atomic operations via Lua scripts

2. **Redis Key Structure**
   ```
   port:allocated:{machine_id}:{port}     # Machine-specific port allocation
   port:instance:{machine_id}:{instance_id}:{service}  # Instance service mapping
   machine:{machine_id}:ports             # Set of ports per machine
   ```

3. **Integration Points**
   - ServiceManager: Uses async port allocation
   - ProcessOrchestrator: Initializes and shares Redis connection
   - ProcessManager: Port conflict detection and resolution

## Features

### Distributed Port Allocation

- **Machine Awareness**: Ports are scoped per machine, allowing the same port on different machines
- **Atomic Operations**: Lua scripts ensure race-free port allocation
- **Conflict Detection**: Automatically detects and reports port conflicts
- **Alternative Port Selection**: Automatically finds available ports when conflicts occur

### TTL Management

- **Automatic Expiration**: Port allocations expire after 5 minutes (configurable)
- **Keep-Alive Mechanism**: Background tasks refresh TTLs every 2 minutes for active services
- **Stale Cleanup**: Expired allocations are automatically removed

### Port Allocation Flow

```python
# 1. Check for existing allocation
existing = await redis.get(f"port:instance:{machine_id}:{instance_id}:{service}")
if existing:
    return int(existing)

# 2. Calculate preferred port
base_port = DEFAULT_PORTS[service_name]  # e.g., 8000 for API
port = base_port + instance.port_offset

# 3. Try atomic allocation with Lua script
for attempt in range(max_attempts):
    if allocate_port_atomically(port):
        return port
    port += 1  # Try next port

# 4. Start TTL refresh task
asyncio.create_task(refresh_ttl_loop(service_name, port))
```

## API Reference

### PortManager Class

#### Initialization
```python
port_manager = PortManager(redis_client=redis)
```

#### Key Methods

##### `async get_service_port(service_name: str) -> int`
Allocate or retrieve a port for a service.

```python
api_port = await port_manager.get_service_port('api')
# Returns: 8000 (or next available)
```

##### `async release_port(service_name: str)`
Release a port allocation and cancel TTL refresh.

```python
await port_manager.release_port('api')
```

##### `async get_allocated_ports(machine_id: Optional[str] = None) -> Dict[str, int]`
Get all allocated ports for a machine.

```python
ports = await port_manager.get_allocated_ports()
# Returns: {'api': 8000, 'ui': 8004}
```

##### `async check_port_conflicts() -> Dict[str, str]`
Check for port conflicts on the current machine.

```python
conflicts = await port_manager.check_port_conflicts()
# Returns: {'api:8000': 'other-instance-id/api'}
```

##### `async cleanup()`
Clean up resources and cancel background tasks.

```python
await port_manager.cleanup()
```

### Synchronous Compatibility Methods

For backward compatibility, synchronous methods are provided:

##### `is_port_available(port: int, host: str = '0.0.0.0') -> bool`
```python
if port_manager.is_port_available(8000):
    # Port is free
```

##### `find_available_port(base_port: int, max_attempts: int = 100) -> int`
```python
port = port_manager.find_available_port(8000)
# Returns first available port starting from 8000
```

## Configuration

### Default Ports

```python
DEFAULT_PORTS = {
    "api": 8000,
    "ui": 8004,
    "metrics": 9090,
    "health": 8080,
    "grpc": 50051,
    "orchestrator": 8001,
    "worker": 8002
}
```

### TTL Settings

```python
port_ttl = 300           # 5 minutes - port allocation TTL
refresh_interval = 120   # 2 minutes - TTL refresh interval
```

## Redis Schema

### Keys and Data Structures

#### Port Allocation
```
Key: port:allocated:{machine_id}:{port}
Value: JSON {
    "instance_id": "instance-abc123",
    "service": "api",
    "machine": "server-1",
    "allocated_at": "2025-09-24T20:30:00Z"
}
TTL: 300 seconds
```

#### Instance Port Mapping
```
Key: port:instance:{machine_id}:{instance_id}:{service}
Value: "8000"
TTL: 300 seconds
```

#### Machine Port Set
```
Key: machine:{machine_id}:ports
Type: Set
Members: ["8000", "8004", "9090"]
```

## Lua Script for Atomic Allocation

The system uses a Lua script to ensure atomic port allocation:

```lua
local machine_port_key = KEYS[1]
local instance_port_key = KEYS[2]
local port = ARGV[1]
local instance_id = ARGV[2]
local service = ARGV[3]
local machine = ARGV[4]
local ttl = ARGV[5]

-- Check if port is already allocated
local existing = redis.call('GET', machine_port_key)
if existing then
    local data = cjson.decode(existing)
    -- Allow same instance to reclaim
    if data.instance_id ~= instance_id then
        return nil
    end
end

-- Allocate the port
local allocation = cjson.encode({
    instance_id = instance_id,
    service = service,
    machine = machine,
    allocated_at = ARGV[6]
})

-- Set both keys atomically
redis.call('SET', machine_port_key, allocation, 'EX', ttl)
redis.call('SET', instance_port_key, port, 'EX', ttl)
redis.call('SADD', 'machine:' .. machine .. ':ports', port)

return port
```

## Usage Examples

### Basic Usage

```python
from gleitzeit.core.ports import PortManager
from gleitzeit.core.instance import get_current_instance

# Initialize
port_manager = PortManager()

# Get port for API service
api_port = await port_manager.get_service_port('api')
print(f"API will use port: {api_port}")

# Check for conflicts
conflicts = await port_manager.check_port_conflicts()
if conflicts:
    print("Port conflicts detected:")
    for conflict, owner in conflicts.items():
        print(f"  {conflict} used by {owner}")

# Clean up when done
await port_manager.cleanup()
```

### Integration with ServiceManager

```python
class ServiceManager:
    async def start_api(self, ...):
        # Get port from PortManager
        service_port = await self.port_manager.get_service_port('api')

        # Start service with allocated port
        await self.process_manager.start_service(
            service_name="api",
            port=service_port,
            ...
        )
```

## Multi-Machine Deployment

### Scenario: Two Machines

**Machine A** (192.168.1.10)
```bash
gleitzeit serve --instance-name "prod-1" --port-offset 0
# Allocates: api=8000, ui=8004
```

**Machine B** (192.168.1.11)
```bash
gleitzeit serve --instance-name "prod-2" --port-offset 0
# Also allocates: api=8000, ui=8004 (no conflict, different machine)
```

### Scenario: Same Machine, Multiple Instances

**Instance 1**
```bash
gleitzeit serve --instance-name "dev-1" --port-offset 0
# Allocates: api=8000, ui=8004
```

**Instance 2** (same machine)
```bash
gleitzeit serve --instance-name "dev-2" --port-offset 10
# Detects conflict on 8000, allocates: api=8001, ui=8005
```

## Migration from File-Based System

### Old System (File-Based)
- Used `/tmp/gleitzeit_ports.json`
- Single machine only
- No TTL or cleanup
- File locking for concurrency

### New System (Redis-Based)
- Uses Redis for coordination
- Multi-machine support
- Automatic TTL and cleanup
- Atomic operations via Lua scripts

### Key Differences

| Feature | File-Based | Redis-Based |
|---------|------------|-------------|
| Storage | `/tmp/gleitzeit_ports.json` | Redis |
| Scope | Single machine | Multi-machine |
| Concurrency | File locks | Atomic Lua scripts |
| Cleanup | Manual | Automatic (TTL) |
| Availability | Synchronous only | Async + sync |
| Conflict Resolution | Basic | Advanced with alternatives |

## Testing

### Unit Test Example

```python
import pytest
import redis.asyncio as aioredis
from gleitzeit.core.ports import PortManager

@pytest.mark.asyncio
async def test_port_allocation():
    redis = await aioredis.from_url("redis://localhost:6379")
    port_manager = PortManager(redis_client=redis)

    # Test allocation
    port = await port_manager.get_service_port('api')
    assert port >= 8000

    # Test conflict detection
    conflicts = await port_manager.check_port_conflicts()
    assert len(conflicts) == 0

    # Cleanup
    await port_manager.cleanup()
    await redis.close()
```

### Integration Test

```python
# Start multiple instances and verify port allocation
async def test_multi_instance():
    # Start instance 1
    port1 = await start_instance("test-1", port_offset=0)
    assert port1 == 8000

    # Start instance 2 - should get different port
    port2 = await start_instance("test-2", port_offset=0)
    assert port2 == 8001  # Next available
```

## Troubleshooting

### Common Issues

#### Port Already in Use
```
ERROR: Port 8000 locked by instance xyz
```
**Solution**: The port is allocated to another instance. Either stop that instance or use a different port offset.

#### Redis Connection Failed
```
ERROR: Could not connect to Redis at localhost:6379
```
**Solution**: Ensure Redis is running and accessible.

#### TTL Expired Unexpectedly
```
WARNING: Port allocation expired for service api
```
**Solution**: Check that the TTL refresh task is running. May indicate the service crashed.

### Debug Commands

```bash
# Check allocated ports in Redis
redis-cli KEYS "port:allocated:*"

# View port allocation details
redis-cli GET "port:allocated:machine-1:8000"

# Check instance ports
redis-cli KEYS "port:instance:*"

# View machine port set
redis-cli SMEMBERS "machine:machine-1:ports"
```

## Performance Considerations

### Redis Operations
- Port allocation: 2-3 Redis calls (check + allocate)
- TTL refresh: 2 Redis calls every 2 minutes per service
- Conflict check: 1 SCAN operation

### Optimization Tips
1. Increase `refresh_interval` if TTL refresh load is high
2. Use Redis cluster for high-scale deployments
3. Consider port pre-allocation for faster startup

## Future Enhancements

1. **Port Reservation**: Reserve port ranges for specific services
2. **Dynamic Reallocation**: Move services to different ports without restart
3. **Port Pool Management**: Pre-allocate port pools for faster allocation
4. **Metrics Integration**: Export port usage metrics to Prometheus
5. **Health Checks**: Verify port is actually usable before allocation