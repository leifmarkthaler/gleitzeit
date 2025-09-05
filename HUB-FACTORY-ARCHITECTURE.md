# Hub Factory Architecture - Implementation Plan

## Problem Statement

Current architecture has a layering issue:
- **ProviderHub** creates providers directly (including OllamaProvider)
- **OllamaProvider** needs its own OllamaHub for resource management
- **ProviderPool** should handle pooling but doesn't integrate protocol hubs
- No unified layer for different execution environments (Ollama, Docker, Shell, HTTP)

## Proposed Architecture

```
┌─────────────────────────────────────────────────────┐
│                   ProviderHub                        │
│         (Top-level orchestrator/coordinator)         │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│                  HubFactory                          │
│      (Creates and manages protocol-specific hubs)    │
└────────────────────────┬─────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  OllamaHub   │ │  DockerHub   │ │  ShellHub    │
│ (LLM/v1)     │ │ (docker/v1)  │ │ (shell/v1)   │
└──────────────┘ └──────────────┘ └──────────────┘
        │                │                │
        ▼                ▼                ▼
┌─────────────────────────────────────────────────────┐
│                 ProviderPool                         │
│          (Pools providers, uses HubFactory)          │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│                ProviderFactory                       │
│         (Validates and creates providers)            │
└──────────────────────────────────────────────────────┘
```

## Component Responsibilities

### 1. **HubFactory** (New Component)
- **Purpose**: Unified layer for protocol-specific execution environments
- **Responsibilities**:
  - Creates protocol-specific hubs (OllamaHub, DockerHub, ShellHub, HTTPHub)
  - Manages hub lifecycle
  - Provides resource allocation interface
  - Registry of protocol → hub mappings
  
### 2. **Protocol Hubs** (Enhanced)
- **OllamaHub**: Manages Ollama instances, model loading, resource allocation
- **DockerHub**: Manages containers, images, volumes
- **ShellHub**: Manages local processes, sandboxing, resource limits
- **HTTPHub**: Manages connection pools, rate limiting, endpoint health
- **Note**: Python and MCP protocols don't need resource hubs (direct execution)

### 3. **ProviderPool** (Refactored)
- **Purpose**: Pool providers and integrate with protocol hubs
- **Changes**:
  - Remove direct provider instantiation
  - Use HubFactory to get protocol-specific resources
  - Pool providers with their associated hub resources
  - Handle resource allocation/release through HubFactory

### 4. **ProviderHub** (Simplified)
- **Purpose**: Top-level orchestrator
- **Changes**:
  - No longer creates providers directly
  - Uses ProviderPool which uses HubFactory
  - Focuses on request routing and orchestration

## Implementation Steps

### Phase 1: Create HubFactory
- [x] Create `HubFactory` class with protocol registry
- [x] Implement `ShellHub` and `HTTPHub` 
- [x] Add resource allocation/release methods
- [ ] Add tests for HubFactory

### Phase 2: Refactor ProviderPool
- [ ] Update ProviderPool to use HubFactory
- [ ] Remove direct provider creation
- [ ] Add hub resource integration
- [ ] Update `_create_provider()` to allocate hub resources
- [ ] Update `_destroy_provider()` to release hub resources

### Phase 3: Update Provider Classes
- [ ] Update OllamaProvider to use hub from pool
- [ ] Update PythonProvider for direct execution
- [ ] Update ShellProvider to use ShellHub
- [ ] Add HTTPProvider for HTTP endpoints

### Phase 4: Simplify ProviderHub
- [ ] Remove direct provider creation logic
- [ ] Use ProviderPool with HubFactory
- [ ] Update initialization flow
- [ ] Clean up redundant code

### Phase 5: Integration
- [ ] Update SimpleProviderHub to use new architecture
- [ ] Update embedded hub in NativeAdapter
- [ ] Test end-to-end workflow execution
- [ ] Update startup audit documentation

## Benefits

1. **Clean Separation of Concerns**
   - HubFactory manages protocol-specific resources
   - ProviderPool handles provider lifecycle
   - ProviderHub focuses on orchestration

2. **Eliminates Circular Dependencies**
   - OllamaProvider no longer needs to create OllamaHub
   - Resources are managed at the appropriate layer

3. **Unified Resource Management**
   - All protocols go through HubFactory
   - Consistent resource allocation/release
   - Better monitoring and control

4. **Extensibility**
   - Easy to add new protocols
   - Register custom hub implementations
   - Protocol-specific optimizations

## Configuration Example

```python
# Initialize HubFactory with specific protocols
hub_factory = HubFactory(persistence=redis_backend)
await hub_factory.initialize(protocols=[
    ProtocolType.LLM,      # Creates OllamaHub
    ProtocolType.DOCKER,   # Creates DockerHub
    ProtocolType.SHELL,    # Creates ShellHub
    ProtocolType.HTTP,     # Creates HTTPHub
])

# ProviderPool uses HubFactory
pool = ProviderPool(
    provider_type="ollama",
    provider_class=OllamaProvider,
    hub_factory=hub_factory,  # Pass hub factory
    min_size=1,
    max_size=10
)

# Provider gets hub resource from pool
provider = await pool.acquire()
# provider.hub_resource contains allocated Ollama instance
```

## Migration Path

1. **Backward Compatibility**
   - Keep existing interfaces working
   - Add deprecation warnings
   - Provide migration guide

2. **Gradual Rollout**
   - Start with new providers using HubFactory
   - Migrate existing providers one by one
   - Test thoroughly at each step

3. **Feature Flags**
   - `enable_hub_factory`: Use new architecture
   - `legacy_mode`: Fall back to old behavior
   - Remove flags after stable

## Testing Strategy

1. **Unit Tests**
   - HubFactory creation and protocol registration
   - Individual hub resource allocation
   - ProviderPool with hub integration

2. **Integration Tests**
   - End-to-end workflow with all protocols
   - Resource allocation under load
   - Failover and recovery scenarios

3. **Performance Tests**
   - Resource allocation latency
   - Pool efficiency with hub resources
   - Concurrent request handling

## Open Questions

1. **Resource Metrics**: How to collect metrics across all hubs?
2. **Priority Allocation**: Should some protocols get priority?
3. **Cross-Protocol Resources**: Can a provider use multiple hubs?
4. **Hub Discovery**: Should hubs auto-discover resources?
5. **Persistence**: What hub state should be persisted?

## Next Steps

1. Review and refine this architecture
2. Implement Phase 1 (HubFactory) - DONE
3. Create proof-of-concept with one protocol
4. Gather feedback and iterate
5. Full implementation following phases 2-5