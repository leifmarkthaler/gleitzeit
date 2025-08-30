# Provider-Hub Integration Tests

This directory contains tests that verify the compatibility between the new provider architecture and the existing hub system in Gleitzeit.

## Architecture Overview

Gleitzeit follows a clean separation of concerns between:

### Providers
- Handle protocol execution and JSON-RPC interface
- Implement business logic for specific protocols  
- Generate protocol specifications automatically
- Examples: `PythonProviderV2`, `OllamaProvider`, `HTTPProvider`

### Hubs  
- Manage resources (Docker containers, processes, external services)
- Handle resource lifecycle, health monitoring, and pooling
- Examples: `DockerHub`, `OllamaHub`, `MCPHub`

### Hub Providers
- Combine provider interface with hub management
- Act as providers that internally manage hubs
- Example: `MCPHubProvider` (manages MCP servers via MCPHub)

## Test Files

### `test_basic_hub_compatibility.py`
Tests fundamental compatibility between providers and hubs:

- **Provider Hub Integration**: Providers can accept hub parameters and use them
- **Independence**: Providers work with or without hubs  
- **Protocol Generation**: Works correctly with hub-enabled providers
- **Execution Mode Selection**: Providers choose appropriate execution modes based on available resources
- **Lifecycle Coordination**: Provider and hub initialization/shutdown work together
- **Resource Management**: Hubs can track provider instances as resources

Key test scenarios:
- Provider accepts hub in constructor
- Provider without hub still works normally
- Hub provider pattern (provider managing internal hub)
- Protocol generation includes hub-aware parameters
- Execution mode selection based on hub availability

### `test_provider_hub_integration.py` 
Comprehensive integration tests covering:

- Architecture separation verification
- Resource efficiency with container pooling
- Concurrent execution handling
- Error handling and fallback scenarios  
- Performance considerations

## Running Tests

```bash
# Run all provider-hub integration tests
pytest newtests/hubs/provider/ -v

# Run basic compatibility tests only
pytest newtests/hubs/provider/test_basic_hub_compatibility.py -v

# Run specific test
pytest newtests/hubs/provider/test_basic_hub_compatibility.py::TestBasicHubCompatibility::test_provider_accepts_hub_parameter -v
```

## Compatibility Verification

These tests verify that:

✅ **New providers work with existing hub infrastructure**  
✅ **Protocol auto-generation works in hub contexts**  
✅ **Resource management follows proper separation of concerns**  
✅ **Providers gracefully handle hub availability/unavailability**  
✅ **Hub providers can combine both interfaces effectively**  

## Integration Points

The tests validate key integration points:

1. **Constructor Integration**: Providers accept hub parameters
2. **Initialization Sequence**: Providers initialize with/without hubs  
3. **Protocol Generation**: Includes hub-specific parameters when available
4. **Execution Delegation**: Providers delegate resource operations to hubs
5. **Resource Tracking**: Hubs can track provider instances as resources
6. **Lifecycle Coordination**: Proper startup/shutdown sequences

This ensures the provider-hub architecture maintains clean separation while enabling powerful integration patterns.