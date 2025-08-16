# Provider Architecture Summary

## Unified Provider Architecture

All providers in Gleitzeit now follow a consistent architecture that preserves the original design while adding enhanced capabilities.

## Provider Hierarchy

```
ProtocolProvider (base.py)
├── Direct Providers
│   ├── OllamaProvider
│   ├── OllamaPoolProvider
│   ├── CustomFunctionProvider
│   └── SimpleMCPProvider
│
└── HubProvider (hub_provider.py)
    ├── OllamaProviderStreamlined
    └── PythonProviderStreamlined
```

## Key Consistency Points

### 1. Base Class: ProtocolProvider
All providers inherit from `ProtocolProvider` which defines:
- `handle_request(method: str, params: Dict[str, Any]) -> Any`
- `initialize() -> None`
- `shutdown() -> None`
- `health_check() -> Dict[str, Any]`
- `get_supported_methods() -> List[str]`

### 2. HubProvider Enhancement
`HubProvider` extends `ProtocolProvider` and adds:
- Integrated resource management
- Load balancing across instances
- Health monitoring
- Metrics collection
- Circuit breaker protection

### 3. Consistent Method Signature
**ALL providers now use the same `handle_request` signature:**
```python
async def handle_request(self, method: str, params: Dict[str, Any]) -> Any
```

This ensures compatibility with:
- The registry's `execute_request` method
- The execution engine's provider calls
- The task queue system

## Provider Types

### Basic Providers
- **OllamaProvider**: Single Ollama instance
- **CustomFunctionProvider**: Local Python execution
- **SimpleMCPProvider**: Built-in MCP tools

### Enhanced Providers
- **OllamaPoolProvider**: Multiple Ollama instances with load balancing
- **OllamaProviderStreamlined**: Hub-based with auto-discovery
- **PythonProviderStreamlined**: Hub-based with Docker container management

## How It Works

### 1. Registration Flow
```python
# All providers register the same way
provider = AnyProvider(provider_id="test")
await provider.initialize()
registry.register_provider(provider_id, protocol_id, provider)
```

### 2. Execution Flow
```
Client → Workflow → Task Queue → Execution Engine → Registry → Provider
                                                              ↓
                                                    handle_request(method, params)
                                                              ↓
                                                    Provider-specific logic
                                                              ↓
                                                            Result
```

### 3. Hub Provider Flow
For hub-based providers, `handle_request` internally:
1. Routes to `execute(method, params)`
2. Selects appropriate resource instance
3. Executes on that instance
4. Handles metrics and failover

## Benefits of This Architecture

1. **Consistency**: All providers work the same way with the registry
2. **Flexibility**: Basic or enhanced providers can be used interchangeably
3. **Compatibility**: No breaking changes to existing architecture
4. **Enhancement**: Hub features are additive, not replacements
5. **Simplicity**: One way to handle all providers

## Usage Examples

### Basic Client (unchanged)
```python
from gleitzeit.client import GleitzeitClient

client = GleitzeitClient()
await client.initialize()  # Uses basic providers
result = await client.chat("Hello")
```

### Enhanced Client (with auto-discovery)
```python
from gleitzeit.client.enhanced_client import create_enhanced_client

client = create_enhanced_client(
    auto_discover=True,      # Find available providers
    use_streamlined=True     # Use hub-based providers
)
await client.initialize()    # Auto-configures everything
result = await client.chat("Hello")
```

### Direct Provider Usage
```python
# All providers work the same way
provider = OllamaProviderStreamlined("test")
await provider.initialize()

# Consistent interface
result = await provider.handle_request(
    method="llm/generate",
    params={"prompt": "Hello"}
)
```

## Testing

Run these tests to verify consistency:
```bash
# Test provider consistency
python test_provider_consistency.py

# Test enhanced client
python test_enhanced_client.py

# Test hub integration
python test_hub_integration.py
```

## Conclusion

The provider architecture now has:
- ✅ **One consistent base class** (ProtocolProvider)
- ✅ **One method signature** for handle_request
- ✅ **One registration mechanism** through the registry
- ✅ **Optional enhancements** via HubProvider
- ✅ **Full backward compatibility**
- ✅ **No architecture violations**

All providers work seamlessly with the existing Gleitzeit orchestration system while offering enhanced capabilities when needed.