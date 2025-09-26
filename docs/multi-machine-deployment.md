# Multi-Machine Deployment for Gleitzeit 0.0.7

## Overview

Gleitzeit 0.0.7 introduces comprehensive multi-machine deployment support, enabling distributed workflow orchestration across multiple servers, datacenters, and network zones. This document covers the architecture, configuration, and usage of multi-machine deployments.

## Architecture

### API Server Changes

The API server (`src/gleitzeit/api/main.py`) has been enhanced to support multi-machine deployments:

1. **Instance Initialization**: Automatically initializes instance identity from environment variables
2. **Discovery API**: New REST endpoints for service discovery and topology management
3. **Environment Integration**: Receives instance metadata from CLI via environment variables

For detailed API server documentation, see [API Server Multi-Machine Support](./api-server-multi-machine.md).

### Core Components

#### 1. Machine Identity (`src/gleitzeit/core/instance.py`)

Each machine is uniquely identified using:
- **Machine ID**: Combination of hostname and hardware fingerprint
- **Hardware Fingerprint**: SHA256 hash of hardware characteristics (MAC addresses, CPU, memory)
- **Network Information**: Primary IP, all IPs, FQDN
- **Location Metadata**: Datacenter, rack, network zone

```python
@dataclass
class MachineInfo:
    machine_id: str              # Unique machine identifier
    machine_fingerprint: str     # Hardware-based fingerprint
    hostname: str                # Network hostname
    fqdn: str                   # Fully qualified domain name
    primary_ip: str             # Primary IP address
    all_ips: List[str]          # All network interfaces
    datacenter: str = "default" # Datacenter identifier
    rack: str = "default"       # Rack location
    network_zone: str = "default" # Network security zone
```

#### 2. Instance Identity

Each Gleitzeit instance has:
- **Instance ID**: Unique identifier for the instance
- **Machine Info**: Complete machine identification
- **Deployment ID**: Combined machine:instance identifier
- **Capabilities**: Hardware and software capabilities
- **Metadata**: Environment, region, zone, tags

#### 3. Service Discovery (`src/gleitzeit/api/discovery.py`)

REST API for discovering services and machines:
- Find services across all machines
- Discover machines by location
- Get deployment topology
- Health checking across instances

## Configuration

### Environment Variables

Configure machine location and network topology:

```bash
# Datacenter/Location
export GLEITZEIT_DATACENTER="us-west-1"
export GLEITZEIT_RACK="rack-42"
export GLEITZEIT_NETWORK_ZONE="production"

# Instance Configuration
export GLEITZEIT_ENVIRONMENT="production"
export GLEITZEIT_REGION="us-west"
export GLEITZEIT_ZONE="us-west-1a"
export GLEITZEIT_CLUSTER="main"
```

### Network Tags

Control which instances can communicate:

```python
# Production instances
metadata.network_tags = {"prod-network"}

# Development instances
metadata.network_tags = {"dev-network"}

# Cross-environment communication
metadata.network_tags = {"prod-network", "dev-network"}
```

## Redis Schema

### Machine Registration

```
machine:registry                           # Set of all machine IDs
machine:{machine_id}:info                 # Machine information
machine:{machine_id}:instances            # Instances on this machine
datacenter:{datacenter}:machines          # Machines in datacenter
rack:{rack}:machines                      # Machines in rack
network_zone:{zone}:machines              # Machines in network zone
```

### Instance Registration

```
instance:registry                         # All instance IDs
instance:{instance_id}:info              # Instance information
instance:{instance_id}:process:{name}    # Process information
```

### Port Management (Machine-Scoped)

```
port:allocated:{machine_id}:{port}       # Port allocation per machine
port:instance:{machine_id}:{instance_id}:{service} # Instance port mapping
machine:{machine_id}:ports               # Set of allocated ports
```

## Service Discovery API

### Endpoints

#### Get Service Instances
```http
GET /discovery/services/{service_type}
```

Find all instances of a service type across machines:

```bash
curl http://localhost:8000/discovery/services/api

# Response
{
  "services": [
    {
      "instance_id": "prod-1-abc123",
      "machine_id": "server1-a1b2c3",
      "machine_ip": "192.168.1.10",
      "port": 8000,
      "url": "http://192.168.1.10:8000",
      "can_communicate": true
    }
  ],
  "count": 1
}
```

#### Get Nearest Service
```http
GET /discovery/services/{service_type}?nearest_only=true
```

Get the nearest/preferred instance based on network topology.

#### Discover Machines
```http
GET /discovery/machines?datacenter=us-west-1
```

Find machines with optional filtering:

```bash
# All machines
curl http://localhost:8000/discovery/machines

# Machines in specific datacenter
curl http://localhost:8000/discovery/machines?datacenter=us-west-1

# Machines in specific rack
curl http://localhost:8000/discovery/machines?rack=rack-42
```

#### Get Topology Map
```http
GET /discovery/topology
```

Get hierarchical deployment topology:

```json
{
  "total_machines": 3,
  "total_instances": 7,
  "datacenters": {
    "us-west-1": {
      "racks": {
        "rack-42": {
          "machines": {
            "server1-a1b2c3": {
              "hostname": "server1",
              "ip": "192.168.1.10",
              "instances": ["prod-1", "prod-2"],
              "instance_count": 2
            }
          },
          "machine_count": 1,
          "instance_count": 2
        }
      },
      "machine_count": 1,
      "instance_count": 2
    }
  }
}
```

#### Service Health
```http
GET /discovery/health/{service_type}
```

Check health of all instances of a service type.

#### Current Instance Info
```http
GET /discovery/instance/current
```

Get detailed information about the current instance.

## Deployment Scenarios

### Single Machine, Multiple Instances

```bash
# Instance 1 - Main API
gleitzeit serve --instance-name "api-main" --port-offset 0

# Instance 2 - Secondary API
gleitzeit serve --instance-name "api-secondary" --port-offset 10
```

### Multi-Machine, Same Datacenter

**Machine A (192.168.1.10)**
```bash
export GLEITZEIT_DATACENTER="us-west-1"
export GLEITZEIT_RACK="rack-42"
gleitzeit serve --instance-name "prod-1"
```

**Machine B (192.168.1.11)**
```bash
export GLEITZEIT_DATACENTER="us-west-1"
export GLEITZEIT_RACK="rack-42"
gleitzeit serve --instance-name "prod-2"
```

### Multi-Datacenter Deployment

**US West Datacenter**
```bash
export GLEITZEIT_DATACENTER="us-west-1"
export GLEITZEIT_NETWORK_ZONE="production"
gleitzeit serve --instance-name "us-west-api"
```

**EU Central Datacenter**
```bash
export GLEITZEIT_DATACENTER="eu-central-1"
export GLEITZEIT_NETWORK_ZONE="production"
gleitzeit serve --instance-name "eu-api"
```

## Service Selection Strategy

The system uses intelligent service selection based on proximity:

1. **Same Machine** (Score: +1000)
   - Prefer services on the same physical machine
   - Lowest latency, no network overhead

2. **Same Rack** (Score: +50)
   - Services in the same rack
   - Low latency, high bandwidth

3. **Same Datacenter** (Score: +100)
   - Services in the same datacenter
   - Moderate latency, good bandwidth

4. **Same Network Zone** (Score: +25)
   - Services in the same security zone
   - Can communicate directly

5. **Network Tags Match** (Score: +10)
   - Services with matching network tags
   - Authorized to communicate

## Machine Registration Process

When an instance starts:

1. **Generate Machine Fingerprint**
   - Collect hardware characteristics
   - Create stable SHA256 hash
   - Combine with hostname for machine_id

2. **Register Machine in Redis**
   ```python
   # Store machine info
   redis.hset(f"machine:{machine_id}:info", machine_info)

   # Add to global registry
   redis.sadd("machine:registry", machine_id)

   # Register by location
   redis.sadd(f"datacenter:{datacenter}:machines", machine_id)
   ```

3. **Register Instance**
   ```python
   # Add to machine's instances
   redis.sadd(f"machine:{machine_id}:instances", instance_id)

   # Store instance info with machine details
   redis.hset(f"instance:{instance_id}:info", instance_info)
   ```

## Port Management

Ports are allocated per-machine to prevent conflicts:

```python
# Port allocation key includes machine_id
port_key = f"port:allocated:{machine_id}:{port}"

# Instance port mapping
instance_port_key = f"port:instance:{machine_id}:{instance_id}:{service}"
```

This allows:
- Same port on different machines
- Automatic conflict resolution
- Machine-local port management

## Monitoring and Observability

### Check Deployment Status

```python
import requests

# Get topology
topology = requests.get("http://localhost:8000/discovery/topology").json()
print(f"Machines: {topology['total_machines']}")
print(f"Instances: {topology['total_instances']}")

# Get API services
apis = requests.get("http://localhost:8000/discovery/services/api").json()
for api in apis['services']:
    print(f"API at {api['url']} on {api['machine_id']}")
```

### Redis Monitoring

```bash
# View all machines
redis-cli SMEMBERS "machine:registry"

# View machine info
redis-cli HGETALL "machine:server1-abc123:info"

# View instances on a machine
redis-cli SMEMBERS "machine:server1-abc123:instances"

# View datacenter machines
redis-cli SMEMBERS "datacenter:us-west-1:machines"
```

## Best Practices

### 1. Machine Naming
- Use descriptive machine IDs
- Include location in hostname
- Example: `prod-api-usw1-001`

### 2. Network Segmentation
- Use network tags for access control
- Separate production and development
- Configure firewall rules based on zones

### 3. Port Management
- Use consistent port offsets
- Reserve port ranges for services
- Document port allocations

### 4. Service Discovery
- Always use discovery API for cross-machine communication
- Cache discovery results appropriately
- Implement retry logic for failed connections

### 5. Monitoring
- Monitor machine registration in Redis
- Track instance distribution across machines
- Alert on unbalanced deployments

## Troubleshooting

### Machine Not Registering

Check environment variables:
```bash
echo $GLEITZEIT_DATACENTER
echo $GLEITZEIT_RACK
echo $GLEITZEIT_NETWORK_ZONE
```

Verify Redis connectivity:
```bash
redis-cli ping
```

### Port Conflicts

Check port allocation:
```bash
redis-cli KEYS "port:allocated:*"
```

Find conflicting instance:
```bash
redis-cli GET "port:allocated:machine-id:8000"
```

### Service Discovery Issues

Test discovery API:
```bash
curl http://localhost:8000/discovery/services/api
curl http://localhost:8000/discovery/machines
```

Check instance registration:
```bash
redis-cli SMEMBERS "service:registry:api"
```

### Network Communication

Verify network tags:
```python
# Check if instances can communicate
instance1_tags = {"prod-network"}
instance2_tags = {"prod-network", "monitoring"}
can_communicate = bool(instance1_tags & instance2_tags)  # True
```

## Migration Guide

### From Single-Machine to Multi-Machine

1. **Update Configuration**
   - Set datacenter/rack environment variables
   - Configure network tags

2. **Update Service Discovery**
   - Replace hardcoded URLs with discovery API
   - Implement nearest-service selection

3. **Test Communication**
   - Verify instances can discover each other
   - Test cross-machine API calls

4. **Monitor Deployment**
   - Check topology map
   - Verify balanced distribution

## Performance Considerations

### Network Latency
- Same machine: < 1ms
- Same rack: 1-5ms
- Same datacenter: 5-10ms
- Cross-datacenter: 20-100ms+

### Service Selection
- Discovery API caches results
- TTL-based cache expiration
- Periodic health checks

### Redis Load
- Machine registration: Once per startup
- Instance heartbeat: Every 30 seconds
- Port TTL refresh: Every 2 minutes

## Security

### Network Isolation
- Use network tags for access control
- Implement firewall rules by zone
- Separate production/development networks

### Authentication
- Service-to-service authentication
- API key per instance
- JWT tokens for cross-machine calls

### Encryption
- TLS for cross-machine communication
- Redis AUTH for coordination
- Encrypted environment variables

## Future Enhancements

1. **Auto-Scaling**
   - Dynamic instance creation based on load
   - Automatic machine provisioning

2. **Load Balancing**
   - Built-in load balancer for services
   - Health-based routing

3. **Geo-Distribution**
   - Cross-region replication
   - Geo-aware service selection

4. **Service Mesh**
   - Integration with Istio/Linkerd
   - Advanced traffic management