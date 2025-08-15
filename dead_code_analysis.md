# Dead Code Analysis for Gleitzeit

## 1. Socket.IO Related (Can be Removed)

### Server Components (Unused)
- `/src/gleitzeit/server/` - Entire directory
  - `central_server.py` - Socket.IO server implementation
  - `__init__.py` - Exports Socket.IO components
  
**Reason**: The new client API uses embedded execution engine, not Socket.IO server

### CLI Socket.IO Client (Unused)
- `/src/gleitzeit/cli/client.py` - Socket.IO client for CLI
  
**Reason**: Replaced by direct execution in gleitzeit_cli.py

## 2. Duplicate/Obsolete Providers

### Definitely Dead:
- `/src/gleitzeit/providers/python_provider_v5.py` - Old version (v5 suffix indicates iteration)
- `/src/gleitzeit/providers/yaml_provider.py` - Not used anywhere, functionality in workflow_loader
- `/src/gleitzeit/providers/echo_provider.py` - Test provider, replaced by SimpleMCPProvider
- `/src/gleitzeit/providers/mock_text_processing_provider.py` - Mock for testing

### Potentially Dead (Need Verification):
- `/src/gleitzeit/providers/mcp_provider.py` - May be replaced by simple_mcp_provider
- `/src/gleitzeit/providers/mcp_jsonrpc_provider.py` - Likely replaced by simple_mcp_provider

### Active Providers (KEEP):
- `base.py` - Base class, actively used
- `ollama_provider.py` - Main LLM provider
- `python_function_provider.py` - Main Python execution provider  
- `simple_mcp_provider.py` - Main MCP tools provider

## 3. Obsolete Core Components

### Provider Factory (Questionable)
- `/src/gleitzeit/core/provider_factory.py` - References Socket.IO, yaml_loader
  
**Reason**: Not used in current execution flow

### YAML Loader (Potentially Dead)
- `/src/gleitzeit/core/yaml_loader.py` - Check if replaced by workflow_loader

## 4. Pooling System (Potentially Dead)

The entire `/src/gleitzeit/pooling/` directory seems unused:
- `adapter.py`
- `backpressure.py`
- `circuit_breaker.py`
- `manager.py`
- `pool.py`
- `worker.py`

**Reason**: Current implementation doesn't use provider pooling

## 5. Integration Files

- `/src/gleitzeit/integrations/mcp_integration.py` - References old mcp_provider.py

## 6. Old CLI Files

- `/src/gleitzeit/cli.py` - Old CLI entry point (replaced by gleitzeit_cli.py)
- `/src/gleitzeit/main.py` - Old main entry (if exists)

## 7. Test Files (Potentially Obsolete)

In `/tests/`:
- Files testing Socket.IO components
- Files testing removed providers
- Duplicate test files with similar names

## Files Safe to Remove

### High Confidence (Definitely Dead):
```bash
# Socket.IO related
rm -rf src/gleitzeit/server/
rm src/gleitzeit/cli/client.py

# Old providers
rm src/gleitzeit/providers/python_provider_v5.py
rm src/gleitzeit/providers/yaml_provider.py
rm src/gleitzeit/providers/echo_provider.py
rm src/gleitzeit/providers/mock_text_processing_provider.py

# Old CLI
rm src/gleitzeit/cli.py
```

### Medium Confidence (Likely Dead, Need Verification):
```bash
# Pooling system (if not used)
rm -rf src/gleitzeit/pooling/

# Provider factory (if not used)
rm src/gleitzeit/core/provider_factory.py

# Duplicate MCP providers
rm src/gleitzeit/providers/mcp_provider.py
rm src/gleitzeit/providers/mcp_jsonrpc_provider.py

# Integration that uses old provider
rm src/gleitzeit/integrations/mcp_integration.py
```

## Verification Steps

Before removing, verify:

1. **Check imports**: 
```bash
grep -r "from gleitzeit.server" src/
grep -r "import.*SocketIO" src/
grep -r "python_provider_v5" src/
grep -r "yaml_provider" src/
grep -r "echo_provider" src/
grep -r "mock_text_processing" src/
```

2. **Check tests**:
```bash
grep -r "server.central_server" tests/
grep -r "pooling" tests/
```

3. **Check if pooling is used**:
```bash
grep -r "ProviderPool\|PoolManager" src/
```

## Impact Analysis

Removing these files would:
- **Reduce codebase by ~30-40%**
- **Eliminate confusion** about which components are active
- **Simplify maintenance** 
- **Make the architecture clearer**

## Recommended Removal Order

1. **Phase 1** (Safe, immediate):
   - Socket.IO server components
   - Old provider versions (*_v5.py)
   - Mock/test providers
   - Old CLI entry points

2. **Phase 2** (After verification):
   - Pooling system (if unused)
   - Duplicate MCP providers
   - Provider factory

3. **Phase 3** (After testing):
   - Update tests to remove references
   - Clean up imports
   - Update documentation

## Additional Cleanup

### Import Cleanup Needed:
- Remove unused imports in remaining files
- Update `__init__.py` files to not export removed components

### Documentation Updates:
- Remove references to Socket.IO architecture
- Update provider documentation
- Update architecture diagrams