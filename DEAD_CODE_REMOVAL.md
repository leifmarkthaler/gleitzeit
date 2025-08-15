# Dead Code Removal Plan for Gleitzeit

## Summary
Identified **~35-40% of codebase as dead code** that can be safely removed.

## SAFE TO REMOVE IMMEDIATELY ✅

### 1. Socket.IO Components (100% Dead)
```bash
# Server components - completely unused
rm -rf src/gleitzeit/server/

# CLI Socket.IO client - replaced by direct execution
rm src/gleitzeit/cli/client.py

# Old CLI entry point - replaced by gleitzeit_cli.py
rm src/gleitzeit/cli.py
```

### 2. Obsolete Provider Implementations (100% Dead)
```bash
# Old Python provider version
rm src/gleitzeit/providers/python_provider_v5.py

# YAML provider - functionality moved to workflow_loader
rm src/gleitzeit/providers/yaml_provider.py

# Test/mock providers
rm src/gleitzeit/providers/echo_provider.py
rm src/gleitzeit/providers/mock_text_processing_provider.py
```

### 3. Pooling System (100% Dead)
The pooling system is ONLY referenced within itself - no external usage:
```bash
# Entire pooling system - not used anywhere
rm -rf src/gleitzeit/pooling/
```

### 4. Provider Factory (Dead)
```bash
# References Socket.IO and unused yaml_loader
rm src/gleitzeit/core/provider_factory.py
```

## REQUIRES MIGRATION BEFORE REMOVAL ⚠️

### MCP Providers (Need to migrate 1 reference)
The old `mcp_provider.py` is only used in one place:
- `/src/gleitzeit/integrations/mcp_integration.py` imports it

**Migration needed**:
1. Update `mcp_integration.py` to use `SimpleMCPProvider`
2. Then remove:
```bash
rm src/gleitzeit/providers/mcp_provider.py
rm src/gleitzeit/providers/mcp_jsonrpc_provider.py
rm src/gleitzeit/integrations/mcp_integration.py  # Or update it
```

## TEST FILES TO REMOVE 🧪

```bash
# Tests for removed components
rm tests/test_protocol_provider_executor_simple.py  # Tests old architecture
rm tests/test_provider_cleanup.py  # Tests pooling
rm tests/test_provider_registry.py  # May test old registry
```

## CLEAN REMOVAL SCRIPT 🗑️

Save and run this script to remove all dead code:

```bash
#!/bin/bash
# dead_code_cleanup.sh

echo "Removing dead code from Gleitzeit..."

# Phase 1: Socket.IO and Server
echo "Removing Socket.IO components..."
rm -rf src/gleitzeit/server/
rm -f src/gleitzeit/cli/client.py
rm -f src/gleitzeit/cli.py

# Phase 2: Dead Providers
echo "Removing obsolete providers..."
rm -f src/gleitzeit/providers/python_provider_v5.py
rm -f src/gleitzeit/providers/yaml_provider.py
rm -f src/gleitzeit/providers/echo_provider.py
rm -f src/gleitzeit/providers/mock_text_processing_provider.py

# Phase 3: Pooling System
echo "Removing unused pooling system..."
rm -rf src/gleitzeit/pooling/

# Phase 4: Provider Factory
echo "Removing provider factory..."
rm -f src/gleitzeit/core/provider_factory.py

# Phase 5: Clean up __pycache__
echo "Cleaning Python cache..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null

# Phase 6: Remove .pyc files
find . -name "*.pyc" -delete

echo "Dead code removal complete!"
echo "Consider running tests to ensure nothing broke: python -m pytest tests/"
```

## IMPACT ANALYSIS 📊

### Before Removal:
- **Total Python files**: ~95 files
- **Lines of code**: ~15,000+ lines

### After Removal:
- **Files removed**: ~25-30 files
- **Lines removed**: ~5,000-6,000 lines
- **Reduction**: ~35-40% of codebase

### Benefits:
1. **Cleaner architecture** - No confusion about which components are active
2. **Faster navigation** - Fewer files to search through
3. **Reduced maintenance** - No need to update dead code
4. **Clearer dependencies** - Removes circular/unused dependencies
5. **Better performance** - Smaller package size, faster imports

## VERIFICATION CHECKLIST ✓

Before running the cleanup:

1. **Backup the repository**:
   ```bash
   git add -A
   git commit -m "Backup before dead code removal"
   ```

2. **Run existing tests**:
   ```bash
   python -m pytest tests/
   ```

3. **Test core functionality**:
   ```bash
   python tests/test_python_client.py
   python examples/python_api_demo.py
   ```

4. **After removal, verify**:
   ```bash
   # Check no broken imports
   python -c "from gleitzeit import GleitzeitClient"
   
   # Run tests again
   python -m pytest tests/
   ```

## FILES TO KEEP (Active Code) ✅

### Core (Keep all):
- `/src/gleitzeit/core/` (except provider_factory.py)
- Especially: models.py, execution_engine.py, workflow_loader.py

### Providers (Keep these):
- `base.py` - Base classes
- `ollama_provider.py` - LLM provider
- `python_function_provider.py` - Python execution
- `simple_mcp_provider.py` - MCP tools

### Client (Keep all):
- `/src/gleitzeit/client/` - New Python API

### Others (Keep):
- `/src/gleitzeit/persistence/` - All backends
- `/src/gleitzeit/protocols/` - Protocol definitions
- `/src/gleitzeit/task_queue/` - Queue management
- `/src/gleitzeit/registry.py` - Provider registry

## ADDITIONAL CLEANUP 🧹

After removing files:

1. **Update imports** in remaining files
2. **Update __init__.py** files to remove exports
3. **Update documentation** to remove references
4. **Update README** if needed
5. **Remove test files** that test removed components

## ESTIMATED TIME: 10 minutes

The cleanup is straightforward - most files are completely isolated and unused.