# Stateless Resource Management Design

## Problem
The current ResourceManager design has stateful components that conflict with horizontal scaling requirements.

## Solution: Stateless Resource Client + External Resource Service

### Architecture

```
┌─────────────────────────────────────────────────┐
│              Gleitzeit Workers                   │
│            (Stateless, Scalable)                 │
├─────────────────────────────────────────────────┤
│  Each worker has:                                │
│  - StatelessResourceClient (no state)            │
│  - Providers with resource client                │
│  - Execution happens with leased resources       │
└────────────────────┬────────────────────────────┘
                     │
                HTTP/gRPC
                     │
┌────────────────────▼────────────────────────────┐
│           Resource Service                       │
│         (Stateful, Single/HA)                    │
├─────────────────────────────────────────────────┤
│  - Owns all resource hubs                        │
│  - Manages resource allocation                   │
│  - Tracks leases with TTL                        │
│  - Handles resource discovery                    │
│  - Load balances across resources                │
└────────────────────┬────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│OllamaHub │   │DockerHub │   │LocalHub  │
└──────────┘   └──────────┘   └──────────┘
```

### Stateless Resource Client

```python
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import aiohttp
from dataclasses import dataclass

@dataclass
class ResourceLease:
    """Lease for an allocated resource"""
    lease_id: str
    resource_id: str
    protocol: str
    endpoint: str
    capabilities: Dict[str, Any]
    expires_at: datetime
    metadata: Dict[str, Any]

class StatelessResourceClient:
    """
    Stateless client for resource allocation.
    Each worker instance has one, but it holds no state.
    """
    
    def __init__(self, resource_service_url: str, worker_id: Optional[str] = None):
        self.service_url = resource_service_url
        self.worker_id = worker_id or generate_worker_id()
        # No state! Just configuration
    
    async def allocate_resource(
        self, 
        protocol: str, 
        requirements: Dict[str, Any],
        lease_duration: int = 60  # seconds
    ) -> ResourceLease:
        """
        Allocate a resource with a lease.
        Completely stateless - each call is independent.
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.service_url}/allocate",
                json={
                    "protocol": protocol,
                    "requirements": requirements,
                    "lease_duration": lease_duration,
                    "worker_id": self.worker_id
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return ResourceLease(
                        lease_id=data["lease_id"],
                        resource_id=data["resource_id"],
                        protocol=protocol,
                        endpoint=data["endpoint"],
                        capabilities=data.get("capabilities", {}),
                        expires_at=datetime.fromisoformat(data["expires_at"]),
                        metadata=data.get("metadata", {})
                    )
                else:
                    raise ResourceAllocationError(await response.text())
    
    async def release_resource(self, lease: ResourceLease) -> bool:
        """
        Release a leased resource.
        Stateless - just sends the lease ID.
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.service_url}/release",
                json={
                    "lease_id": lease.lease_id,
                    "worker_id": self.worker_id
                }
            ) as response:
                return response.status == 200
    
    async def renew_lease(self, lease: ResourceLease, extension: int = 60) -> ResourceLease:
        """
        Renew a resource lease.
        Returns updated lease with new expiration.
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.service_url}/renew",
                json={
                    "lease_id": lease.lease_id,
                    "extension": extension,
                    "worker_id": self.worker_id
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    lease.expires_at = datetime.fromisoformat(data["expires_at"])
                    return lease
                else:
                    raise LeaseRenewalError(await response.text())
    
    async def get_resource_status(self) -> Dict[str, Any]:
        """
        Get current resource availability.
        Read-only, stateless query.
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.service_url}/status") as response:
                return await response.json()
```

### Stateless Execution Backend

```python
class StatelessExecutionBackend:
    """
    Execution backend that uses stateless resource client.
    No persistent state between executions.
    """
    
    def __init__(self, resource_client: StatelessResourceClient):
        self.resource_client = resource_client
        # No state! Just configuration
    
    async def execute_with_resources(
        self, 
        protocol: str, 
        method: str, 
        params: Dict[str, Any]
    ) -> Any:
        """
        Execute with leased resources.
        Each execution is completely independent.
        """
        # Allocate resource with lease
        lease = await self.resource_client.allocate_resource(
            protocol=protocol,
            requirements=self._get_requirements(method, params),
            lease_duration=120  # 2 minutes for execution
        )
        
        try:
            # Execute using leased resource
            result = await self._execute_on_resource(
                lease.endpoint,
                method,
                params
            )
            return result
            
        finally:
            # Always release the lease
            await self.resource_client.release_resource(lease)
    
    async def _execute_on_resource(
        self,
        endpoint: str,
        method: str,
        params: Dict[str, Any]
    ) -> Any:
        """Execute on a specific resource endpoint"""
        # Implementation specific to protocol
        pass
```

### Provider Integration

```python
class StatelessOllamaProvider(ProtocolProvider):
    """
    Provider that uses stateless resource client.
    No state between requests.
    """
    
    def __init__(self, resource_client: StatelessResourceClient, **kwargs):
        super().__init__(**kwargs)
        self.resource_client = resource_client
        # No persistent connections or state
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Any:
        """
        Execute method with leased resources.
        Completely stateless execution.
        """
        # Get resource for this execution only
        lease = await self.resource_client.allocate_resource(
            protocol="llm/v1",
            requirements={"model": params.get("model", "llama3.2")},
            lease_duration=60
        )
        
        try:
            # Use resource for this execution
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{lease.endpoint}/api/generate",
                    json=params
                ) as response:
                    return await response.json()
        finally:
            # Release immediately after use
            await self.resource_client.release_resource(lease)
```

## Benefits for Horizontal Scaling

### 1. **Zero Coordination Between Workers**
- Each worker operates independently
- No shared state between workers
- Resources allocated per-request

### 2. **Elastic Scaling**
```yaml
# Kubernetes example
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-workers
spec:
  replicas: 10  # Scale to any number
  template:
    spec:
      containers:
      - name: worker
        env:
        - name: RESOURCE_SERVICE_URL
          value: "http://resource-service:8080"
        # Each pod is completely stateless
```

### 3. **Resource Efficiency**
- Resources released immediately after use
- No idle resource holding
- Automatic lease expiration prevents leaks

### 4. **Fault Tolerance**
- Worker crashes don't leak resources (leases expire)
- Resource service can be made HA
- No worker-specific state to recover

## Implementation with Current Architecture

### Option 1: Minimal Changes
Keep ResourceManager but make it a client to external service:

```python
class RemoteResourceManager:
    """ResourceManager that delegates to external service"""
    
    def __init__(self, service_url: str):
        self.client = StatelessResourceClient(service_url)
    
    async def allocate_resource(self, protocol: str, requirements: dict):
        # Delegate to stateless client
        lease = await self.client.allocate_resource(protocol, requirements)
        return lease  # Return lease instead of resource
```

### Option 2: Full Stateless
Replace ResourceManager with StatelessResourceClient everywhere:

```python
# In ProviderPool
async def _create_provider(self):
    # Create provider with resource client
    resource_client = StatelessResourceClient(
        self.resource_service_url
    )
    
    instance = factory.create_provider(
        self.provider_class,
        resource_client=resource_client,  # Pass client instead of manager
        **kwargs
    )
```

## Configuration for Different Environments

### Development (Single Machine)
```python
# Embedded resource service
resource_service = EmbeddedResourceService()
await resource_service.start(port=8080)

# Local client
client = StatelessResourceClient("http://localhost:8080")
```

### Production (Kubernetes)
```yaml
# Resource service as StatefulSet
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: resource-service
spec:
  replicas: 1  # Or 3 for HA with consensus
  
# Workers as Deployment
apiVersion: apps/v1  
kind: Deployment
metadata:
  name: gleitzeit-workers
spec:
  replicas: 50  # Scale as needed
```

### Hybrid (Multiple Machines)
```python
# Central resource service
RESOURCE_SERVICE_URL = "http://resource-manager.internal:8080"

# Workers on different machines all use same service
worker1 = StatelessResourceClient(RESOURCE_SERVICE_URL)
worker2 = StatelessResourceClient(RESOURCE_SERVICE_URL)
# ... worker N
```

## Summary

The stateless resource management design:
1. **Maintains explicit resource visibility** - Resources are still first-class citizens
2. **Enables true horizontal scaling** - Workers have no state
3. **Preserves the benefits** - Central management, monitoring, configuration
4. **Adds scalability** - Lease-based allocation, automatic cleanup, fault tolerance

The key change: **Transform ResourceManager from a stateful component to a stateless client of an external resource service.**