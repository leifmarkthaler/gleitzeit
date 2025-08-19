# Provider ID Naming Convention

## Overview
Provider IDs in Gleitzeit follow a consistent naming pattern to identify their source component and avoid conflicts.

## Naming Pattern

```
<component-prefix>-<provider-type>-provider
```

### Component Prefixes

| Component | Prefix | Example |
|-----------|--------|---------|
| CLI | `cli` | `cli-python-provider` |
| API | `api` | `api-ollama-provider` |
| Client (Native) | (none) | `python-provider` |
| Custom/User | `custom` | `custom-rag-provider` |

### Provider Types

Standard provider types:
- `python` - Python code execution
- `ollama` - LLM operations via Ollama
- `mcp` - Model Context Protocol tools
- `template` - Template-based workflows
- `instructor` - Structured output (experimental)
- `rag` - Retrieval Augmented Generation (experimental)

## Why Different Prefixes?

Having different prefixes helps with:

1. **Debugging**: Immediately identify which component created a provider
2. **Isolation**: Prevent ID conflicts when multiple components run together
3. **Monitoring**: Track provider usage by component
4. **Testing**: Run tests in parallel without conflicts

## Examples

### CLI Providers
```python
PythonProvider("cli-python-provider")
OllamaProvider("cli-ollama-provider")
SimpleMCPProvider("cli-mcp-provider")
TemplateProvider("cli-template-provider")
```

### API Providers
```python
PythonProvider("api-python-provider")
OllamaProvider("api-ollama-provider")
SimpleMCPProvider("api-mcp-provider")
TemplateProvider("api-template-provider")
```

### Client Providers (Native Mode)
```python
PythonProvider("python-provider")
OllamaProvider("ollama-provider")
SimpleMCPProvider("mcp-provider")
TemplateProvider("template-provider")
```

## Impact on Functionality

**Important**: The provider ID prefix does NOT affect:
- Protocol compatibility
- Method execution
- Resource allocation
- Task routing

The ExecutionEngine routes tasks based on protocol ID (e.g., `python/v1`), not provider ID.

## Custom Providers

When creating custom providers:

```python
# In a standalone script
MyCustomProvider("custom-ml-provider")

# In a plugin
MyPluginProvider("plugin-transform-provider")

# In tests
TestProvider("test-mock-provider")
```

## Migration Note

If you have existing code that references specific provider IDs:
- The IDs are internal and shouldn't be hardcoded
- Use protocol IDs for task routing (e.g., `llm/v1`, `python/v1`)
- Provider IDs are mainly for logging and debugging