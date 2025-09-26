# API Server Multi-Machine Support

## Overview

The Gleitzeit API server (`src/gleitzeit/api/main.py`) has been enhanced with multi-machine deployment support, enabling distributed workflow orchestration across multiple servers. This document describes the API server changes and how they integrate with the broader multi-machine architecture.

## Key Changes to API Server

### Instance Initialization

The API server now automatically initializes its instance identity from environment variables set by the CLI:

```python
# In lifespan function
instance_name = os.environ.get('GLEITZEIT_INSTANCE_NAME')
instance_role = os.environ.get('GLEITZEIT_INSTANCE_ROLE', 'standalone')
if instance_name:
    initialize_instance(instance_name, instance_role)
```

This ensures the API server has proper identity for:
- Service registration in Redis
- Machine-aware operations
- Service discovery functionality

### Environment Variables

The API server receives these environment variables from the CLI:

| Variable | Description | Example |
|----------|-------------|---------|
| `GLEITZEIT_INSTANCE_ID` | Unique instance identifier | `multi-ma-c4ca6a8f` |
| `GLEITZEIT_INSTANCE_NAME` | Human-readable instance name | `multi-machine-test` |
| `GLEITZEIT_INSTANCE_ROLE` | Instance role | `standalone` |
| `GLEITZEIT_DEPLOYMENT_ID` | Combined machine:instance ID | `server1:multi-ma-c4ca6a8f` |
| `GLEITZEIT_REDIS_NAMESPACE` | Redis namespace for instance | `gleitzeit:multi-ma-c4ca6a8f` |

### Discovery API Integration

The API server now includes the discovery router providing REST endpoints for multi-machine operations:

```python
from .discovery import router as discovery_router
app.include_router(discovery_router, tags=["discovery"])
```

## Discovery API Endpoints

### Get Current Instance
```http
GET /discovery/instance/current
```

Returns detailed information about the current API server instance:

```json
{
  "instance_id": "multi-ma-c4ca6a8f",
  "instance_name": "multi-machine-test",
  "role": "standalone",
  "deployment_id": "Leifs-MacBook-Air-5556da9e:multi-ma-c4ca6a8f",
  "machine": {
    "machine_id": "Leifs-MacBook-Air-5556da9e",
    "hostname": "Leifs-MacBook-Air.local",
    "primary_ip": "10.23.224.33",
    "datacenter": "default",
    "rack": "default",
    "network_zone": "default"
  },
  "capabilities": {
    "cpu_count": 8,
    "memory_gb": 16.0,
    "platform": "macOS-14.5-arm64-arm-64bit"
  },
  "metadata": {
    "environment": "development",
    "region": "default",
    "zone": "default",
    "cluster": "default"
  }
}
```

### Discover Services
```http
GET /discovery/services/{service_type}
```

Find all instances of a service type across machines:

```json
{
  "services": [
    {
      "instance_id": "multi-ma-c4ca6a8f",
      "machine_id": "Leifs-MacBook-Air-5556da9e",
      "machine_ip": "10.23.224.33",
      "port": 8000,
      "url": "http://10.23.224.33:8000",
      "can_communicate": true
    }
  ],
  "count": 1
}
```

Query parameters:
- `nearest_only`: Return only the nearest/preferred instance

### Discover Machines
```http
GET /discovery/machines
```

List all registered machines in the deployment:

```json
{
  "machines": [
    {
      "machine_id": "Leifs-MacBook-Air-5556da9e",
      "hostname": "Leifs-MacBook-Air.local",
      "primary_ip": "10.23.224.33",
      "datacenter": "default",
      "rack": "default",
      "network_zone": "default",
      "instances": ["multi-ma-c4ca6a8f"],
      "instance_count": 1
    }
  ],
  "count": 1
}
```

Query parameters:
- `datacenter`: Filter by datacenter
- `rack`: Filter by rack
- `zone`: Filter by network zone

### Get Topology
```http
GET /discovery/topology
```

Get hierarchical deployment topology:

```json
{
  "total_machines": 1,
  "total_instances": 3,
  "datacenters": {
    "us-west-1": {
      "racks": {
        "rack-42": {
          "machines": {
            "server1": {
              "hostname": "server1.example.com",
              "ip": "192.168.1.10",
              "instances": ["prod-1", "prod-2"],
              "instance_count": 2
            }
          }
        }
      }
    }
  }
}
```

### Service Health
```http
GET /discovery/health/{service_type}
```

Check health of all instances of a service type:

```json
{
  "service_type": "api",
  "total_instances": 3,
  "healthy_instances": 3,
  "instances": [
    {
      "instance_id": "multi-ma-c4ca6a8f",
      "machine_id": "server1",
      "url": "http://192.168.1.10:8000",
      "healthy": true,
      "reachable": true
    }
  ],
  "overall_health": "healthy"
}
```

## CORS Configuration

The API server automatically configures CORS to allow cross-origin requests from UI instances:

```python
# CORS origins are computed from serve configuration
if cors_config.get('use_serve_config', True):
    # Adds API and UI URLs from configuration
    allowed_origins.extend([
        f"http://{api_host}:{api_port}",
        f"http://{ui_host}:{ui_port}"
    ])
```

## Security Middleware

The API server maintains all security features in multi-machine deployments:

- **Rate Limiting**: Per-instance rate limits
- **Request Tracking**: Tracks requests with instance context
- **Audit Logging**: Logs include instance and machine information
- **IP Whitelisting**: Can be configured per deployment

## Lifecycle Management

### Startup Sequence

1. Load configuration from `gleitzeit.yaml`
2. Initialize instance from environment variables
3. Connect to Redis
4. Initialize client connection pool
5. Register discovery service
6. Start security middleware
7. Begin serving requests

### Shutdown Sequence

1. Stop accepting new requests
2. Complete in-flight requests
3. Close client connection pool
4. Disconnect from Redis
5. Clean shutdown

## Configuration

The API server reads multi-machine configuration from `gleitzeit.yaml`:

```yaml
# Deployment configuration
deployment:
  datacenter: ${GLEITZEIT_DATACENTER:-default}
  rack: ${GLEITZEIT_RACK:-default}
  network_zone: ${GLEITZEIT_NETWORK_ZONE:-default}

  # Instance metadata
  environment: ${GLEITZEIT_ENVIRONMENT:-development}
  region: ${GLEITZEIT_REGION:-default}
  zone: ${GLEITZEIT_ZONE:-default}
  cluster: ${GLEITZEIT_CLUSTER:-default}

  # Network tags for communication control
  network_tags:
    - ${GLEITZEIT_ENVIRONMENT:-development}-network

# Service discovery
discovery:
  enabled: true
  cache_ttl: 60  # Cache discovery results
  prefer_local: true  # Prefer same-machine services
```

## Integration with ProcessManager

The API server integrates with the ProcessManager for:

- Machine registration
- Service registration
- Port allocation
- Discovery operations

This happens automatically when started via the CLI `serve` command.

## Error Handling

The API server handles multi-machine specific errors:

- **Instance Not Initialized**: Returns 500 if instance identity not set
- **Service Not Found**: Returns 404 if no services match criteria
- **Machine Unreachable**: Marks services as unreachable in discovery
- **Network Tag Mismatch**: Filters out services that can't communicate

## Usage Examples

### Starting API Server with Multi-Machine Support

```bash
# Start with specific instance name
gleitzeit serve --instance-name "api-prod-1"

# With datacenter configuration
export GLEITZEIT_DATACENTER="us-west-1"
export GLEITZEIT_RACK="rack-42"
gleitzeit serve --instance-name "api-west-1"
```

### Using Discovery API from Client

```python
import requests

# Get current instance info
response = requests.get("http://localhost:8000/discovery/instance/current")
instance = response.json()
print(f"Running on {instance['machine']['hostname']}")

# Find all API services
response = requests.get("http://localhost:8000/discovery/services/api")
apis = response.json()
for api in apis['services']:
    print(f"API at {api['url']} on {api['machine_id']}")

# Get deployment topology
response = requests.get("http://localhost:8000/discovery/topology")
topology = response.json()
print(f"Total machines: {topology['total_machines']}")
print(f"Total instances: {topology['total_instances']}")
```

## Best Practices

1. **Always Name Instances**: Use meaningful instance names for easy identification
2. **Set Location Metadata**: Configure datacenter/rack/zone for optimal service selection
3. **Use Network Tags**: Control which instances can communicate
4. **Monitor Discovery**: Check discovery endpoints to verify deployment health
5. **Cache Discovery Results**: Use appropriate caching for discovery queries

## Troubleshooting

### Instance Not Initialized

If discovery endpoints return "Instance not initialized":

1. Check environment variables are set
2. Verify instance initialization in startup logs
3. Ensure started via CLI `serve` command

### Services Not Discoverable

If services don't appear in discovery:

1. Check Redis connectivity
2. Verify machine registration in Redis
3. Check network tags match
4. Verify service registration completed

### Port Conflicts

If API server fails to start due to port conflicts:

1. Check Redis port allocations
2. Use `--restart` flag to clean old allocations
3. Verify no manual processes on ports

## Migration Notes

### From Single-Machine to Multi-Machine

1. No code changes required in API server
2. Set appropriate environment variables
3. Configure network topology in `gleitzeit.yaml`
4. Update client code to use discovery API

### Backward Compatibility

The API server maintains full backward compatibility:
- Works without instance initialization (single-machine mode)
- Discovery endpoints gracefully handle missing instance
- All existing endpoints function unchanged