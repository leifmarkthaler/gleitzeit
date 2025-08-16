# Provider to Hub Migration Plan

## Overview
This document outlines the step-by-step migration from redundant provider implementations to the unified hub architecture.

## Phase 1: Extract Common Components (Week 1)

### 1.1 Create Shared Components Module
```bash
mkdir -p src/gleitzeit/common
```

### 1.2 Extract Circuit Breaker
```python
# src/gleitzeit/common/circuit_breaker.py
# Move from ollama_pool.py lines 88-150
# Make it generic for any resource type
```

### 1.3 Extract Metrics Collection
```python
# src/gleitzeit/common/metrics.py
# Merge InstanceMetrics (ollama_pool.py:37-68) with ResourceMetrics (hub/base.py)
# Create unified metrics interface
```

### 1.4 Extract Health Monitoring
```python
# src/gleitzeit/common/health_monitor.py
# Generic health checking interface
# Support for various health check protocols
```

### 1.5 Extract Load Balancer
```python
# src/gleitzeit/common/load_balancer.py
# Move strategies from ollama_pool.py:26-34
# Make strategies generic and extensible
```

## Phase 2: Refactor OllamaPoolProvider (Week 2)

### 2.1 Update Provider to Use Hub
```python
# src/gleitzeit/providers/ollama_pool_provider.py
class OllamaPoolProvider(ProtocolProvider):
    def __init__(self, provider_id: str, hub: Optional[OllamaHub] = None):
        super().__init__(...)
        # Use hub if provided, otherwise create new one
        self.hub = hub or OllamaHub(
            hub_id=f"{provider_id}-hub",
            auto_discover=True
        )
        self.owns_hub = hub is None
```

### 2.2 Delegate Resource Management to Hub
```python
async def execute(self, method: str, params: Dict[str, Any]):
    # Get instance from hub
    instance = await self.hub.get_instance_for_model(
        model_name=params.get('model'),
        strategy=params.get('strategy', 'least_loaded')
    )
    
    # Execute protocol-specific logic
    if method == "llm/generate":
        return await self._execute_generation(instance, params)
    # ... other methods
```

### 2.3 Remove Redundant OllamaPoolManager
- Mark `OllamaPoolManager` as deprecated
- Move unique features (if any) to OllamaHub
- Update all references

## Phase 3: Refactor PythonDockerProvider (Week 2-3)

### 3.1 Update Provider to Use DockerHub
```python
# src/gleitzeit/providers/python_docker_provider.py
class PythonDockerProvider(ProtocolProvider):
    def __init__(self, provider_id: str, hub: Optional[DockerHub] = None):
        super().__init__(...)
        self.hub = hub or DockerHub(
            hub_id=f"{provider_id}-hub"
        )
```

### 3.2 Delegate Container Management
```python
async def _execute_docker(self, code: str, params: Dict):
    # Get container from hub
    config = DockerConfig(
        image=params.get('image', 'python:3.11-slim'),
        memory_limit=params.get('memory_limit', '512m'),
        security_level=params.get('security_level', 'sandboxed')
    )
    
    instance = await self.hub.get_or_create_instance(config)
    
    # Execute Python-specific logic
    result = await self.hub.execute_in_container(
        instance_id=instance.id,
        command=self._prepare_python_command(code)
    )
```

### 3.3 Extract ContainerPool to Hub
- Move `ContainerPool` class to DockerHub
- Remove from DockerExecutor
- Update all pool operations

## Phase 4: Create Compatibility Layer (Week 3)

### 4.1 Provider Adapter Pattern
```python
# src/gleitzeit/providers/adapters.py
class HubProviderAdapter:
    """Adapter to make hub-based providers backward compatible"""
    
    def __init__(self, provider: ProtocolProvider, hub: ResourceHub):
        self.provider = provider
        self.hub = hub
    
    async def execute_legacy(self, request: Dict) -> Dict:
        """Handle legacy API calls"""
        # Map old API to new hub-based implementation
```

### 4.2 Migration Helpers
```python
# src/gleitzeit/migration/helpers.py
def migrate_provider_config(old_config: Dict) -> Dict:
    """Convert old provider config to hub-based config"""
    
def create_provider_with_hub(provider_type: str, config: Dict):
    """Factory for creating providers with appropriate hubs"""
```

## Phase 5: Testing & Validation (Week 4)

### 5.1 Create Integration Tests
```python
# tests/test_provider_hub_integration.py
async def test_ollama_provider_with_hub():
    hub = OllamaHub("test-hub")
    provider = OllamaPoolProvider("test-provider", hub=hub)
    # Test that provider correctly uses hub
    
async def test_backward_compatibility():
    # Test that old API still works
```

### 5.2 Performance Benchmarks
```python
# benchmarks/provider_hub_performance.py
# Compare performance before and after migration
# Ensure no regression in:
# - Response times
# - Resource utilization
# - Concurrent request handling
```

### 5.3 Migration Validation
```python
# tests/test_migration.py
async def test_config_migration():
    old_config = {...}  # Old provider config
    new_config = migrate_provider_config(old_config)
    # Verify equivalent functionality
```

## Phase 6: Gradual Rollout (Week 5)

### 6.1 Feature Flags
```python
# src/gleitzeit/config/features.py
FEATURES = {
    'use_hub_architecture': False,  # Start disabled
    'hub_architecture_providers': [],  # Gradual enable
}
```

### 6.2 Dual-Mode Operation
```python
class OllamaPoolProvider:
    async def execute(self, method, params):
        if FEATURES['use_hub_architecture']:
            return await self._execute_with_hub(method, params)
        else:
            return await self._execute_legacy(method, params)
```

### 6.3 Monitoring & Metrics
- Track performance metrics for both paths
- Monitor error rates
- Collect user feedback

## Phase 7: Deprecation (Week 6+)

### 7.1 Mark Old Components as Deprecated
```python
import warnings

@deprecated("Use OllamaHub instead")
class OllamaPoolManager:
    def __init__(self, *args, **kwargs):
        warnings.warn(
            "OllamaPoolManager is deprecated. Use OllamaHub instead.",
            DeprecationWarning,
            stacklevel=2
        )
```

### 7.2 Update Documentation
- Add migration guides
- Update API documentation
- Provide code examples

### 7.3 Communication Plan
- Announce deprecation timeline
- Provide migration support
- Document breaking changes

## Migration Checklist

### Pre-Migration
- [ ] Backup current configuration
- [ ] Document current API usage
- [ ] Identify all provider dependencies
- [ ] Create rollback plan

### During Migration
- [ ] Extract common components
- [ ] Refactor OllamaPoolProvider
- [ ] Refactor PythonDockerProvider
- [ ] Create compatibility layer
- [ ] Write comprehensive tests
- [ ] Benchmark performance

### Post-Migration
- [ ] Monitor metrics
- [ ] Gather feedback
- [ ] Fix any issues
- [ ] Remove deprecated code (after grace period)

## Risk Mitigation

### Risk 1: Breaking Changes
**Mitigation**: Compatibility layer ensures old API continues working

### Risk 2: Performance Regression
**Mitigation**: Comprehensive benchmarking before rollout

### Risk 3: Resource Leaks
**Mitigation**: Thorough testing of resource lifecycle management

### Risk 4: Complex Migration
**Mitigation**: Gradual rollout with feature flags

## Success Metrics

1. **Code Reduction**: Target 40% reduction in redundant code
2. **Performance**: No more than 5% performance degradation
3. **Reliability**: Error rate < 0.1%
4. **Migration Time**: Complete in 6 weeks
5. **Zero Downtime**: No service interruptions

## Timeline Summary

- **Week 1**: Extract common components
- **Week 2**: Refactor Ollama provider
- **Week 2-3**: Refactor Docker provider
- **Week 3**: Create compatibility layer
- **Week 4**: Testing and validation
- **Week 5**: Gradual rollout
- **Week 6+**: Deprecation and cleanup

## Next Steps

1. Review and approve migration plan
2. Set up feature flags infrastructure
3. Begin Phase 1: Extract common components
4. Create migration tracking dashboard
5. Schedule regular migration sync meetings