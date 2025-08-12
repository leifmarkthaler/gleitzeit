# Gleitzeit Hybrid Extension System

A powerful, flexible extension system that combines both **native Python extensions** and **MCP (Model Context Protocol) servers** in a unified interface.

## 🎯 Overview

The hybrid approach gives you the best of both worlds:

- **Native Extensions**: Fast, direct Python integration for Gleitzeit-specific functionality
- **MCP Servers**: Standard protocol for LLM providers and external tools
- **Unified Interface**: Seamless access to both types through a single API

## 🚀 Quick Start

### Basic Usage

```python
from gleitzeit_extensions import UnifiedProviderManager, is_mcp_available

# Create unified manager
manager = UnifiedProviderManager()

# Discover native extensions
manager.discover_extensions(["./extensions"])

# Add MCP servers (if MCP is available)
if is_mcp_available():
    manager.add_mcp_server(
        name="openai",
        command="mcp-server-openai",
        env={"OPENAI_API_KEY": "your-key"},
        models=["gpt-4", "gpt-3.5-turbo"]
    )

# Start everything
async with manager:
    # Find provider for any model
    provider = manager.find_provider_for_model("gpt-4")
    print(f"gpt-4 provided by: {provider}")
```

### Integrated with Cluster

```python
from gleitzeit_extensions.helpers import create_cluster_with_unified_providers

# Create cluster with unified provider support
cluster, manager = create_cluster_with_unified_providers(
    extension_paths=["./extensions"],
    setup_standard_mcp=True,  # Auto-setup OpenAI, Claude, Ollama via MCP
    extensions=["custom-workflow-optimizer"],  # Load native extensions
    mcp_config_file="mcp_servers.json"  # Load MCP config
)

# Use through cluster
provider = await cluster.find_provider_for_model("gpt-4")
result = await cluster.call_model_provider("gpt-4", "generate_text", "Hello!")
```

## 🏗️ Architecture

### Two Extension Types

**1. Native Extensions (Python)**
- Direct Python integration
- Fast execution, shared state
- Best for: Gleitzeit-specific logic, performance-critical code
- Definition: Decorators or config files

**2. MCP Servers (Protocol)**  
- Process isolation, language agnostic
- Standard protocol, ecosystem compatibility
- Best for: LLM providers, external tools, standard integrations
- Definition: MCP server executables

### Unified Manager

The `UnifiedProviderManager` provides a single interface:

```python
# Works with both native extensions and MCP servers
models = manager.get_available_models()
provider = manager.find_provider_for_model("gpt-4")
result = await manager.call_provider("openai", "generate_text", "Hello")
```

## 📋 Configuration

### Native Extensions

**Decorator-based:**
```python
@extension(name="custom", description="My custom extension")
@model("custom-model", capabilities=["text"])
class CustomExtension:
    async def generate_text(self, prompt: str) -> str:
        return f"Generated: {prompt}"
```

**Config-based:**
```yaml
# extension.yaml
name: custom
models:
  - name: custom-model
    capabilities: [text]
```

### MCP Servers

**Programmatic:**
```python
manager.add_mcp_server(
    name="openai",
    command="mcp-server-openai",
    models=["gpt-4", "gpt-3.5-turbo"],
    capabilities=["text", "vision"]
)
```

**Configuration File:**
```json
{
  "servers": [
    {
      "name": "openai",
      "command": "mcp-server-openai",
      "env": {"OPENAI_API_KEY": "${OPENAI_API_KEY}"},
      "models": ["gpt-4", "gpt-3.5-turbo"],
      "capabilities": ["text", "vision"]
    }
  ]
}
```

## 🔀 Model Routing

The unified manager automatically routes model requests:

```python
# Finds the right provider automatically
provider_info = manager.find_provider_for_model("gpt-4")
# Returns: {"name": "openai", "type": "mcp", "connected": True}

# Call through unified interface  
result = await manager.call_provider("openai", "generate_text", "Hello")
```

## 🎛️ Standard LLM Providers

Automatically set up standard providers via MCP:

```python
from gleitzeit_extensions import setup_standard_llm_providers

setup_standard_llm_providers(manager)
# Configures: OpenAI, Claude, Ollama MCP servers
```

Sets up:
- **OpenAI**: `gpt-4`, `gpt-3.5-turbo`, `gpt-4o`
- **Anthropic**: `claude-3-opus`, `claude-3-sonnet`, `claude-3-haiku`  
- **Ollama**: `llama3`, `llava`, `codellama`, `mistral`

## 📊 Capabilities

### Unified Discovery

```python
# Get all providers
providers = manager.get_all_providers()

# Find by capability
text_providers = manager.find_providers_by_capability("text")
vision_providers = manager.find_providers_by_capability("vision")

# Get summary
summary = manager.get_summary()
print(f"Total providers: {summary['total_providers']}")
print(f"MCP servers: {summary['mcp_providers']}")  
print(f"Native extensions: {summary['extension_providers']}")
```

### Health Monitoring

```python
providers = manager.get_all_providers()
for name, provider in providers.items():
    print(f"{name}: {'🟢' if provider.connected else '⚫'}")
    if provider.health_status:
        print(f"  Health: {provider.health_status}")
```

## 🔄 Lifecycle Management

### Startup
```python
# Start all providers (extensions + MCP servers)
results = await manager.start_all_providers()

# Check results
for provider, success in results.items():
    print(f"{provider}: {'✅' if success else '❌'}")
```

### Shutdown
```python
# Stop all providers gracefully  
await manager.stop_all_providers()
```

### Context Manager
```python
async with manager:
    # All providers started automatically
    await manager.call_provider("openai", "generate_text", "Hello")
    # All providers stopped automatically on exit
```

## 🛠️ Installation

### Basic (Native Extensions Only)
```bash
# Already included with gleitzeit_cluster
pip install gleitzeit_cluster
```

### With MCP Support
```bash
# Add MCP protocol support
pip install "mcp[cli]"

# Install MCP servers
npm install -g mcp-server-openai
npm install -g mcp-server-anthropic  
npm install -g mcp-server-ollama
```

## 📚 Examples

### Complete Hybrid Setup

```python
import asyncio
from gleitzeit_extensions.helpers import (
    create_cluster_with_unified_providers,
    start_cluster_with_unified_providers,
    stop_cluster_with_unified_providers
)

async def main():
    # Create cluster with both extension types
    cluster, manager = create_cluster_with_unified_providers(
        # Native extensions
        extension_paths=["./custom_extensions"],
        extensions=["workflow-optimizer", "custom-scheduler"],
        extension_configs={
            "workflow-optimizer": {"max_workers": 10}
        },
        
        # MCP servers
        setup_standard_mcp=True,
        mcp_config_file="mcp_servers.json",
        
        # Cluster config
        enable_real_execution=True
    )
    
    try:
        # Start everything
        await start_cluster_with_unified_providers(cluster, manager)
        
        # Use unified model routing
        models = await cluster.get_available_extension_models()
        print(f"Available models: {list(models.keys())}")
        
        # Call any model through unified interface
        result = await cluster.call_model_provider(
            model="gpt-4",
            method="generate_text", 
            prompt="Explain the hybrid extension system"
        )
        print(result)
        
    finally:
        await stop_cluster_with_unified_providers(cluster, manager)

asyncio.run(main())
```

### Custom MCP Server Integration

```python
# Add custom MCP server
manager.add_mcp_server(
    name="custom-llm",
    command="python",
    args=["./custom_mcp_server.py"],
    env={"API_KEY": "your-key"},
    models=["custom-model-v1", "custom-model-v2"],
    capabilities=["text", "custom-processing"],
    description="Custom LLM provider"
)

# Connect and use
await manager.connect_mcp_server("custom-llm")
result = await manager.call_provider("custom-llm", "custom_process", data="input")
```

## 🔧 Best Practices

### When to Use Each Type

**Use Native Extensions for:**
- Gleitzeit-specific workflow logic
- Performance-critical operations
- Deep cluster integration needs
- Shared state requirements

**Use MCP Servers for:**
- LLM provider integrations
- External tool integrations
- Language-agnostic components
- Process isolation requirements

### Configuration Best Practices

1. **Environment Variables**: Use for sensitive data
   ```python
   env={"API_KEY": "${MY_API_KEY}"}
   ```

2. **Configuration Files**: Use for complex setups
   ```python
   manager.load_mcp_servers_from_file("production_mcp.json")
   ```

3. **Health Checks**: Monitor provider status
   ```python
   summary = manager.get_summary()
   if summary["connected_providers"] < summary["total_providers"]:
       # Handle disconnected providers
   ```

4. **Graceful Degradation**: Handle missing MCP
   ```python
   if is_mcp_available():
       setup_standard_llm_providers(manager)
   else:
       print("MCP not available, using native extensions only")
   ```

## 🚨 Error Handling

The unified system provides comprehensive error handling:

```python
try:
    await manager.call_provider("openai", "generate_text", "Hello")
except ExtensionNotFound:
    print("Provider not configured")
except ExtensionError as e:
    print(f"Provider error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## 🔮 Migration Path

### From Native-Only
```python
# Old way
from gleitzeit_extensions import ExtensionManager
manager = ExtensionManager()

# New way - fully backward compatible
from gleitzeit_extensions import UnifiedProviderManager  
manager = UnifiedProviderManager()
# All ExtensionManager methods still work!
```

### Adding MCP
```python
# Existing setup
manager = UnifiedProviderManager()
manager.discover_extensions(["./extensions"])

# Add MCP gradually
if is_mcp_available():
    setup_standard_llm_providers(manager)  # Add OpenAI, Claude via MCP
    # Native extensions and MCP servers coexist seamlessly
```

## 📖 API Reference

### UnifiedProviderManager

**Core Methods:**
- `get_all_providers() -> Dict[str, ProviderInfo]`
- `find_provider_for_model(model: str) -> Optional[Dict]`
- `find_providers_by_capability(capability: str) -> List[Dict]`
- `call_provider(name: str, method: str, *args, **kwargs) -> Any`

**Native Extension Methods:**
- `discover_extensions(paths: List[str]) -> List[str]`
- `load_extension(name: str, **config) -> Any`
- `start_extension(name: str) -> None`
- `stop_extension(name: str) -> None`

**MCP Server Methods:**
- `add_mcp_server(name: str, command: str, ...) -> None`
- `load_mcp_servers_from_file(config_file: str) -> None`
- `connect_mcp_server(name: str) -> bool`
- `disconnect_mcp_server(name: str) -> None`

**Lifecycle Methods:**
- `start_all_providers() -> Dict[str, bool]`
- `stop_all_providers() -> None`

### Helper Functions

```python
from gleitzeit_extensions.helpers import (
    create_cluster_with_unified_providers,
    start_cluster_with_unified_providers,
    stop_cluster_with_unified_providers
)
```

## 🎯 Summary

The hybrid extension system provides:

✅ **Unified Interface** - Single API for both native extensions and MCP servers  
✅ **Automatic Routing** - Finds the right provider for any model  
✅ **Graceful Degradation** - Works with or without MCP  
✅ **Standard Compliance** - Uses MCP protocol for interoperability  
✅ **Performance Options** - Choose the right tool for the job  
✅ **Easy Migration** - Fully backward compatible  

This architecture gives you maximum flexibility while maintaining simplicity and standards compliance.