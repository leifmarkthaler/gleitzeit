# Provider Hub Stateless Design

**Date:** 2025-08-31  
**Purpose:** Design a stateless provider management system to replace the current singleton ProviderHub

## Current State Analysis

### The Problem

The ProviderHub currently uses a singleton pattern that violates stateless principles:

```python
# Current singleton pattern in provider_hub.py
_provider_hub_instance = None

def get_provider_hub() -> 'ProviderHub':
    """Get the singleton ProviderHub instance."""
    global _provider_hub_instance
    if _provider_hub_instance is None:
        _provider_hub_instance = ProviderHub()
    return _provider_hub_instance
```

### Issues with Current Design

1. **Global State:** Single shared instance across all requests/workflows
2. **Scalability Limitation:** Cannot run multiple instances independently
3. **Resource Contention:** All workflows compete for same provider instances
4. **Testing Complexity:** Shared state makes testing difficult
5. **Crash Recovery:** Loss of hub means loss of all provider state

### Current ProviderHub Responsibilities

1. **Provider Registration:** Maintaining registry of available providers
2. **Provider Lifecycle:** Creating, initializing, and shutting down providers
3. **Resource Management:** Managing provider instances and their resources
4. **Provider Discovery:** Finding appropriate provider for task types
5. **Health Monitoring:** Tracking provider health and availability
6. **Load Balancing:** Distributing tasks across provider instances

## Proposed Solution: Provider Pool Pattern

### Design Principles

1. **No Singleton:** Remove global instance completely
2. **Dependency Injection:** Pass provider manager through dependency injection
3. **Stateless Operations:** Each request/workflow gets isolated provider access
4. **Persistence-Based Registry:** Store provider metadata in persistence layer
5. **Resource Pooling:** Pool provider instances for efficiency

### Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   API/Client Layer                   │
│                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  │
│  │  Workflow 1  │  │  Workflow 2  │  │   Task    │  │
│  └──────────────┘  └──────────────┘  └──────────┘  │
└─────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────┐
│              Provider Management Layer               │
│                                                       │
│  ┌────────────────────────────────────────────────┐ │
│  │           ProviderPoolManager                  │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐    │ │
│  │  │  Python  │  │  Shell   │  │  Ollama  │    │ │
│  │  │   Pool   │  │   Pool   │  │   Pool   │    │ │
│  │  └──────────┘  └──────────┘  └──────────┘    │ │
│  └────────────────────────────────────────────────┘ │
│                                                       │
│  ┌────────────────────────────────────────────────┐ │
│  │          ProviderRegistry (Stateless)          │ │
│  └────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────┐
│                  Persistence Layer                   │
│                                                       │
│  ┌────────────────────────────────────────────────┐ │
│  │   Provider Metadata │ Health │ Configuration   │ │
│  └────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

## Detailed Design

### 1. ProviderPoolManager

Replaces the singleton ProviderHub with a pooled approach:

```python
class ProviderPoolManager:
    """
    Manages pools of provider instances.
    Each provider type has its own pool.
    """
    
    def __init__(self, persistence: PersistenceAdapter):
        self.persistence = persistence
        self.provider_pools: Dict[str, ProviderPool] = {}
        
    async def get_provider(self, provider_type: str) -> Provider:
        """Get a provider instance from the appropriate pool."""
        if provider_type not in self.provider_pools:
            self.provider_pools[provider_type] = ProviderPool(
                provider_type=provider_type,
                persistence=self.persistence
            )
        return await self.provider_pools[provider_type].acquire()
        
    async def release_provider(self, provider: Provider):
        """Return provider to its pool."""
        pool = self.provider_pools.get(provider.type)
        if pool:
            await pool.release(provider)
```

### 2. ProviderPool

Individual pool for each provider type:

```python
class ProviderPool:
    """
    Pool for a specific provider type.
    Manages lifecycle and resource allocation.
    """
    
    def __init__(self, provider_type: str, persistence: PersistenceAdapter):
        self.provider_type = provider_type
        self.persistence = persistence
        self.available: List[Provider] = []
        self.in_use: Set[Provider] = set()
        self.max_size = self._get_max_size()
        
    async def acquire(self) -> Provider:
        """Get a provider from the pool."""
        # Try to get from available pool
        if self.available:
            provider = self.available.pop()
            self.in_use.add(provider)
            return provider
            
        # Create new if under limit
        if len(self.in_use) < self.max_size:
            provider = await self._create_provider()
            self.in_use.add(provider)
            return provider
            
        # Wait for available provider
        return await self._wait_for_available()
```

### 3. ProviderRegistry

Stateless registry that uses persistence:

```python
class ProviderRegistry:
    """
    Stateless provider registry.
    All provider metadata stored in persistence.
    """
    
    def __init__(self, persistence: PersistenceAdapter):
        self.persistence = persistence
        
    async def register_provider(self, provider_config: Dict):
        """Register a new provider type."""
        await self.persistence.set(
            f"provider:registry:{provider_config['type']}", 
            provider_config
        )
        
    async def get_provider_config(self, provider_type: str) -> Dict:
        """Get provider configuration from persistence."""
        return await self.persistence.get(f"provider:registry:{provider_type}")
        
    async def list_providers(self) -> List[str]:
        """List all registered provider types."""
        keys = await self.persistence.list_keys("provider:registry:*")
        return [k.split(":")[-1] for k in keys]
```

### 4. Dependency Injection Pattern

For ExecutionEngine and other components:

```python
class ExecutionEngineV2:
    def __init__(self, provider_manager: ProviderPoolManager = None):
        # Accept injected provider manager
        self.provider_manager = provider_manager or self._create_default_manager()
        
    async def execute_task(self, task: Task):
        # Get provider from pool
        provider = await self.provider_manager.get_provider(task.provider_type)
        try:
            result = await provider.execute(task)
        finally:
            # Always return to pool
            await self.provider_manager.release_provider(provider)
```

## Implementation Strategy

### Phase 1: Create New Components (Parallel to Existing)
1. Implement ProviderPoolManager
2. Implement ProviderPool for each provider type
3. Implement ProviderRegistry with persistence
4. Add dependency injection support

### Phase 2: Migration Path
1. Add provider_manager parameter to ExecutionEngine
2. Update TaskExecutor to use pool manager
3. Modify client initialization to inject provider manager
4. Update tests to use new pattern

### Phase 3: Cleanup
1. Mark singleton ProviderHub as deprecated
2. Remove get_provider_hub() function
3. Remove global _provider_hub_instance
4. Update documentation

## Benefits of New Design

### 1. Horizontal Scalability
- Multiple engine instances can run independently
- Each instance has its own provider pools
- No shared state between instances

### 2. Resource Isolation
- Workflows don't compete for same provider instances
- Better resource allocation per workflow
- Isolated failure domains

### 3. Performance
- Connection pooling reduces overhead
- Parallel provider initialization
- Better cache locality

### 4. Reliability
- Provider failure doesn't affect other workflows
- Automatic provider replacement on failure
- Graceful degradation

### 5. Testing
- Easy to mock provider pools
- Isolated test environments
- No shared state cleanup needed

## Configuration Examples

### Provider Pool Configuration
```yaml
providers:
  python:
    pool_size: 10
    max_idle_time: 300
    health_check_interval: 60
    
  shell:
    pool_size: 5
    max_idle_time: 180
    health_check_interval: 30
    
  ollama:
    pool_size: 3
    max_idle_time: 600
    health_check_interval: 120
```

### Deployment Configuration
```yaml
# Development
provider_pools:
  default_size: 2
  max_size: 5
  
# Production
provider_pools:
  default_size: 10
  max_size: 50
  auto_scale: true
```

## Migration Considerations

### Backward Compatibility
1. Keep ProviderHub interface temporarily
2. Implement facade pattern over new pools
3. Gradual migration of components
4. Feature flag for switching implementations

### Risk Mitigation
1. Extensive testing of pool behavior
2. Monitoring of resource usage
3. Gradual rollout with canary deployments
4. Rollback plan if issues arise

## Testing Strategy

### Unit Tests
- Pool acquisition/release logic
- Provider lifecycle management
- Registry persistence operations
- Resource limit enforcement

### Integration Tests
- Multi-workflow provider sharing
- Provider failure recovery
- Pool exhaustion handling
- Cross-component integration

### Performance Tests
- Pool throughput benchmarks
- Resource utilization metrics
- Latency measurements
- Scalability limits

## Monitoring & Observability

### Metrics to Track
1. **Pool Metrics**
   - Available providers per type
   - In-use providers per type
   - Wait time for provider acquisition
   - Provider creation rate

2. **Health Metrics**
   - Provider failure rate
   - Provider initialization time
   - Health check success rate
   - Resource utilization

3. **Performance Metrics**
   - Task execution latency
   - Provider throughput
   - Queue depth
   - Rejection rate

## Open Questions

1. **Provider Warmup**
   - Should providers be pre-warmed on startup?
   - How to handle cold start latency?

2. **Resource Limits**
   - How to enforce global resource limits?
   - Per-workflow vs global pool sizing?

3. **Provider Affinity**
   - Should workflows have provider affinity?
   - How to handle stateful providers (if any)?

4. **Cleanup Strategy**
   - When to destroy idle providers?
   - How to handle long-running tasks?

## Client Pooling Considerations

After analysis, client pooling is **not strictly necessary** because:

1. **Clients are lightweight** - Just configuration and adapter references
2. **The real issue is deeper** - ProviderHub singleton is the bottleneck
3. **Engine pooling is more effective** - Better resource isolation

### Recommended Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Usage Patterns                      │
├─────────────────────────────────────────────────────┤
│ API:     ClientPool → EnginePool → ProviderPools    │
│ Script:  Client → Single Engine → ProviderPools     │
│ Service: Client → EnginePool → ProviderPools        │
└─────────────────────────────────────────────────────┘
```

### Implementation Priority

1. **First:** Fix ProviderHub singleton (highest impact)
2. **Second:** Add optional EnginePool for high concurrency
3. **Third:** Client pooling only where needed (API layer done)

## Next Steps

1. **Review & Feedback**
   - Review design with team
   - Identify potential issues
   - Refine approach based on feedback

2. **Prototype**
   - Build minimal ProviderPoolManager
   - Test pool behavior
   - Benchmark performance

3. **Implementation Plan**
   - Create detailed task breakdown
   - Estimate timeline
   - Identify dependencies

4. **Rollout Strategy**
   - Define success criteria
   - Plan monitoring setup
   - Create rollback procedures

## Conclusion

The provider pool pattern eliminates the singleton anti-pattern while providing better scalability, reliability, and resource management. The design maintains efficiency through pooling while achieving true stateless operation suitable for horizontal scaling.

This approach aligns with the stateless architecture already implemented for the API layer, creating a consistent pattern throughout the Gleitzeit system.

---

*Design Document Created: 2025-08-31*  
*Status: Draft - Ready for Review*