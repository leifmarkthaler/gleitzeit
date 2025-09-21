# Stateless Provider Registry Architecture

## Overview

The Stateless Provider Registry is a distributed, persistence-backed system for managing protocol providers across multiple Gleitzeit instances. It enables horizontal scaling by allowing any instance to discover providers registered by other instances without maintaining local state.

## Key Components

### 1. StatelessProtocolRegistry (`src/gleitzeit/registry_stateless.py`)

The core registry that discovers providers dynamically from:
- **Persistence layer** (primary): Redis-backed distributed registry
- **Local PoolingAdapter** (fallback): Local pooled providers
- **Local ProviderHub** (fallback): Hub-based providers (e.g., Ollama)

### 2. Provider Registration

Providers are registered in persistence when initialized:
- **Key format**: `provider:registry:protocol:{protocol_id}`
- **Protocol set**: `provider:registry:protocols` (set of all available protocols)
- **Instance tracking**: `provider:registry:instance:{instance_id}:protocol:{protocol_id}`

### 3. Provider Lifecycle Management

#### Registration Flow
1. SystemManager starts and initializes providers
2. Each provider is registered in persistence with metadata:
   - `provider_id`: Unique identifier
   - `instance_id`: Instance that owns this provider
   - `capabilities`: List of supported methods
   - `hub_based`: Whether it's a hub-based provider
3. TTL is set to 5 minutes to handle stale registrations

#### Heartbeat Mechanism
- `_provider_heartbeat_loop()` runs every 2 minutes
- Refreshes all provider registrations to prevent TTL expiration
- Ensures active providers remain discoverable

#### Deregistration Flow
1. During graceful shutdown, `_shutdown_providers()` is called
2. Each provider is explicitly deregistered from persistence
3. Provider is removed from protocol set if no other instances have it
4. Heartbeat tasks are cancelled

## Architecture Benefits

### 1. True Stateless Operation
- No in-memory provider storage
- All provider discovery through persistence
- Any instance can discover any provider

### 2. Horizontal Scalability
- Multiple instances share the same provider registry
- New instances discover existing providers immediately
- Load balancing across provider instances

### 3. Fault Tolerance
- Automatic cleanup of dead providers (TTL expiration)
- Fallback to local providers if persistence unavailable
- No single point of failure

### 4. Dynamic Provider Management
- Providers can be added/removed at runtime
- Changes are immediately visible to all instances
- No restart required for provider updates

## Implementation Details

### Provider Discovery Process

```python
def is_protocol_registered(self, protocol_id: str) -> bool:
    # 1. Check persistence (distributed registry)
    if self.persistence:
        key = f"provider:registry:protocol:{protocol_id}"
        if exists(key):
            return True
    
    # 2. Fallback to local sources
    if self.pooling_adapter and protocol_id in self.pooling_adapter._registered_protocols:
        return True
    
    if self.provider_hub and protocol_id in self.provider_hub.providers:
        return True
    
    return False
```

### Provider Registration in SystemManager

```python
# When registering a provider
await pooling_adapter.register_provider(provider_id, protocol_id, provider_instance)

# Also register in persistence for distributed discovery
await self.registry.register_provider_in_persistence(
    protocol_id,
    {
        "provider_id": provider_id,
        "instance_id": self.instance_id,
        "capabilities": ["method1", "method2"]
    }
)
```

### Workflow Validation

WorkflowLoaderV2 uses the stateless registry to validate protocols:
1. Receives workflow with protocol requirements
2. Queries StatelessProtocolRegistry for availability
3. Registry checks persistence and local sources
4. Validation passes if provider is found anywhere

## Configuration

### TTL Settings
- **Provider TTL**: 5 minutes (configurable)
- **Heartbeat interval**: 2 minutes (must be < TTL)
- **Stale component timeout**: 120 seconds

### Persistence Keys

| Key Pattern | Description | TTL |
|------------|-------------|-----|
| `provider:registry:protocol:{protocol_id}` | Provider registration | 5 min |
| `provider:registry:protocols` | Set of all protocols | None |
| `provider:registry:instance:{instance_id}:protocol:{protocol_id}` | Instance-specific tracking | 5 min |

## Deployment Considerations

### Single Instance Mode
- Providers registered locally and in persistence
- No heartbeat needed (optional)
- Simple deregistration on shutdown

### Multi-Instance Mode
- Each instance registers its providers
- Heartbeat maintains registrations
- Instance-specific deregistration
- Protocol remains available if other instances have it

### High Availability
- Multiple instances can provide same protocol
- Load balancing across provider instances
- Automatic failover on instance failure
- No coordinator required

## Error Handling

### Registration Failures
- Log error but continue operation
- Fallback to local provider if available
- Retry on next heartbeat

### Persistence Unavailable
- Fall back to local provider sources
- Continue operation with reduced functionality
- Log warnings for monitoring

### Stale Providers
- Automatic cleanup via TTL
- Manual cleanup via deregistration
- Health checks for provider liveness

## Monitoring and Observability

### Key Metrics
- Provider registration count
- Heartbeat success rate
- TTL expiration events
- Provider discovery latency
- Fallback usage frequency

### Log Events
- Provider registration/deregistration
- Heartbeat refreshes
- Discovery failures
- TTL expirations
- Fallback activations

## Future Enhancements

### 1. Provider Health Checks
- Active health monitoring
- Automatic deregistration of unhealthy providers
- Circuit breaker pattern

### 2. Provider Versioning
- Support multiple versions of same protocol
- Version-aware routing
- Graceful version migrations

### 3. Provider Capacity Management
- Track provider load/capacity
- Intelligent routing based on capacity
- Auto-scaling triggers

### 4. Enhanced Multi-Tenancy
- Tenant-specific provider isolation
- Priority-based provider allocation
- Resource quotas per tenant

## Example Usage

### Starting a Server with Providers

```bash
# Server automatically registers providers in persistence
PYTHONDONTWRITEBYTECODE=1 gleitzeit serve --port 8000

# Providers registered:
# - python/v1 (Python executor)
# - shell/v1 (Shell executor)  
# - llm/v1 (Ollama, if available)
```

### Checking Registered Providers

```bash
# View all registered protocols
redis-cli smembers "provider:registry:protocols"

# Check specific provider details
redis-cli get "provider:registry:protocol:python/v1"

# Check TTL
redis-cli ttl "provider:registry:protocol:python/v1"
```

### Running Workflows

```yaml
# Workflow can use any registered provider
name: "Mixed Provider Workflow"
tasks:
  - name: "llm_task"
    protocol: "llm/v1"  # Discovered from persistence
    method: "llm/chat"
    
  - name: "python_task"  
    protocol: "python/v1"  # Available from any instance
    method: "python/execute"
```

## Troubleshooting

### Providers Not Found
1. Check Redis connectivity
2. Verify provider registration in logs
3. Check TTL hasn't expired
4. Ensure heartbeat is running

### Stale Providers
1. Check instance shutdown was graceful
2. Verify deregistration in logs
3. Wait for TTL expiration
4. Manually remove if needed

### Performance Issues
1. Check Redis latency
2. Verify local fallback is working
3. Monitor heartbeat frequency
4. Check for registration storms

## Conclusion

The Stateless Provider Registry enables true horizontal scaling for Gleitzeit by:
- Eliminating local provider state
- Enabling cross-instance provider discovery
- Providing automatic lifecycle management
- Ensuring high availability and fault tolerance

This architecture supports everything from single-instance development to multi-instance production deployments without code changes.