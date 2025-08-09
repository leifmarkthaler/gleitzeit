# Gleitzeit MCP (Model Context Protocol) Tutorial

## Table of Contents
1. [Introduction](#introduction)
2. [Installation](#installation)
3. [Basic Concepts](#basic-concepts)
4. [Quick Start](#quick-start)
5. [Configuration Methods](#configuration-methods)
6. [Working with Providers](#working-with-providers)
7. [Model Routing](#model-routing)
8. [Advanced Usage](#advanced-usage)
9. [Best Practices](#best-practices)
10. [Troubleshooting](#troubleshooting)

## Introduction

The Model Context Protocol (MCP) is a standard protocol for communication between AI applications and external tools/services. Gleitzeit's MCP integration allows you to:

- Connect to external LLM providers (OpenAI, Anthropic, Ollama, etc.)
- Access tools and services via standardized protocol
- Combine native Python extensions with MCP servers seamlessly
- Route models automatically to the correct provider

### MCP vs Native Extensions

| Feature | Native Extensions | MCP Servers |
|---------|------------------|-------------|
| **Performance** | Fast (in-process) | Slower (IPC overhead) |
| **Isolation** | Same process | Separate process |
| **Language** | Python only | Any language |
| **Integration** | Direct Python API | Standard protocol |
| **Use Cases** | Gleitzeit-specific logic | LLM providers, external tools |

## Installation

### Prerequisites

```bash
# Install gleitzeit (if not already installed)
pip install gleitzeit

# Install MCP support
pip install 'mcp[cli]'
# or with uv:
uv pip install 'mcp[cli]'
```

### Installing MCP Servers

MCP servers are separate executables that implement specific functionality:

```bash
# Example: Install OpenAI MCP server
npm install -g @modelcontextprotocol/server-openai

# Example: Install filesystem MCP server
npm install -g @modelcontextprotocol/server-filesystem

# Example: Install web search MCP server  
npm install -g @modelcontextprotocol/server-brave-search
```

## Basic Concepts

### UnifiedProviderManager

The `UnifiedProviderManager` is the central component that manages both native extensions and MCP servers:

```python
from gleitzeit_extensions import UnifiedProviderManager, create_unified_manager

# Create the manager
manager = create_unified_manager()
```

### Provider Types

1. **Native Extensions**: Python modules that extend Gleitzeit directly
2. **MCP Servers**: External processes that communicate via MCP protocol

Both types are accessed through the same unified interface.

## Quick Start

### Basic Example

```python
import asyncio
from gleitzeit_extensions import create_unified_manager, is_mcp_available

async def main():
    # Create unified manager
    manager = create_unified_manager()
    
    # Check if MCP is available
    if is_mcp_available():
        print("✅ MCP is available")
        
        # Add an MCP server programmatically
        manager.add_mcp_server(
            name="openai",
            command="mcp-server-openai",
            env={"OPENAI_API_KEY": "your-api-key"},
            models=["gpt-4", "gpt-3.5-turbo"],
            capabilities=["text", "vision", "function_calling"],
            description="OpenAI GPT models"
        )
    else:
        print("❌ MCP not available - install with: pip install 'mcp[cli]'")
    
    # Discover native extensions
    manager.discover_extensions(["path/to/extensions"])
    
    # Start all providers
    await manager.start_all_providers()
    
    # Find provider for a model
    provider = manager.find_provider_for_model("gpt-4")
    if provider:
        print(f"GPT-4 is available via {provider['name']} ({provider['type']})")
    
    # Stop all providers
    await manager.stop_all_providers()

asyncio.run(main())
```

### Using Context Manager

```python
async def main():
    manager = create_unified_manager()
    
    # Configure providers
    manager.add_mcp_server(
        name="ollama",
        command="mcp-server-ollama",
        args=["--host", "localhost:11434"],
        models=["llama3", "codellama"],
        capabilities=["text"]
    )
    
    # Use context manager for automatic cleanup
    async with manager:
        # Providers are automatically started
        providers = manager.get_all_providers()
        print(f"Active providers: {len(providers)}")
        
        # Use providers here...
        
    # Providers are automatically stopped

asyncio.run(main())
```

## Configuration Methods

### Method 1: Programmatic Configuration

```python
from gleitzeit_extensions import create_unified_manager

manager = create_unified_manager()

# Add MCP server with full configuration
manager.add_mcp_server(
    name="custom-llm",
    command="python",
    args=["my_mcp_server.py"],
    env={
        "API_KEY": "secret-key",
        "MODEL_PATH": "/path/to/models"
    },
    working_directory="/app/servers",
    timeout=30,
    models=["model-1", "model-2"],
    capabilities=["text", "streaming"],
    description="Custom LLM server"
)
```

### Method 2: Configuration File

Create a JSON configuration file (`mcp_servers.json`):

```json
{
  "servers": [
    {
      "name": "openai",
      "command": "mcp-server-openai",
      "env": {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}"
      },
      "models": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
      "capabilities": ["text", "vision", "function_calling"],
      "description": "OpenAI GPT models via MCP"
    },
    {
      "name": "filesystem",
      "command": "mcp-server-filesystem",
      "args": ["--read-write", "/workspace"],
      "capabilities": ["file_operations"],
      "description": "File system operations"
    }
  ]
}
```

Load the configuration:

```python
manager = create_unified_manager()
manager.load_mcp_servers_from_file("mcp_servers.json")
```

### Method 3: Standard LLM Providers

Use the built-in helper for common LLM providers:

```python
from gleitzeit_extensions import create_unified_manager, setup_standard_llm_providers

manager = create_unified_manager()

# Automatically configures OpenAI, Anthropic, and Ollama
# Uses environment variables: OPENAI_API_KEY, ANTHROPIC_API_KEY
setup_standard_llm_providers(manager)
```

## Working with Providers

### Listing All Providers

```python
# Get all providers (extensions + MCP servers)
providers = manager.get_all_providers()

for name, provider in providers.items():
    print(f"\n{name} ({provider.type}):")
    print(f"  Description: {provider.description}")
    print(f"  Models: {', '.join(provider.models)}")
    print(f"  Capabilities: {', '.join(provider.capabilities)}")
    print(f"  Connected: {'✅' if provider.connected else '❌'}")
```

### Finding Providers by Capability

```python
# Find all providers that support vision
vision_providers = manager.find_providers_by_capability("vision")

for provider in vision_providers:
    print(f"{provider['name']} supports vision")
    print(f"  Models: {', '.join(provider['models'])}")
```

### Getting Available Models

```python
# Get all available models from all providers
models = manager.get_available_models()

for model_name, model_info in models.items():
    print(f"{model_name}:")
    print(f"  Provider: {model_info['provider']}")
    print(f"  Type: {model_info['provider_type']}")
    print(f"  Connected: {model_info['connected']}")
```

## Model Routing

### Automatic Model Routing

```python
# Find which provider handles a specific model
provider_info = manager.find_provider_for_model("gpt-4")

if provider_info:
    print(f"Model: gpt-4")
    print(f"Provider: {provider_info['name']}")
    print(f"Type: {provider_info['type']}")
    print(f"Connected: {provider_info['connected']}")
else:
    print("No provider found for gpt-4")
```

### Calling Provider Methods

```python
# Call a method on a provider (works for both extensions and MCP)
async def use_provider():
    # For native extensions
    result = await manager.call_provider(
        "my_extension",
        "process_text",
        text="Hello world"
    )
    
    # For MCP servers (tools)
    result = await manager.call_provider(
        "filesystem",
        "read_file",
        path="/tmp/data.txt"
    )
    
    return result
```

## Advanced Usage

### Integration with Gleitzeit Cluster

```python
from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_extensions import create_unified_manager, setup_standard_llm_providers

async def cluster_example():
    # Create cluster
    cluster = GleitzeitCluster(
        enable_real_execution=True,
        auto_start_services=False
    )
    
    # Create and configure unified manager
    manager = create_unified_manager()
    manager.discover_extensions(["./extensions"])
    setup_standard_llm_providers(manager)
    
    # Attach to cluster
    cluster.set_unified_provider_manager(manager)
    
    # Use cluster with unified provider support
    async with cluster:
        # Find provider through cluster
        provider = await cluster.find_provider_for_model("gpt-4")
        
        # Get available models through cluster
        models = await cluster.get_available_extension_models()
        
        # Process with model routing
        result = await cluster.process_with_model(
            "gpt-4",
            "Analyze this text..."
        )
```

### Custom MCP Server Implementation

Create a custom MCP server (`my_mcp_server.py`):

```python
from mcp import Server, Tool
from mcp.server import stdio_server
import asyncio

# Create server
server = Server("custom-server")

# Define tools
@server.tool()
async def process_data(data: str) -> str:
    """Process data with custom logic"""
    return f"Processed: {data.upper()}"

@server.tool()
async def analyze_text(text: str, mode: str = "basic") -> dict:
    """Analyze text with different modes"""
    return {
        "text": text,
        "mode": mode,
        "words": len(text.split()),
        "chars": len(text)
    }

# Run server
if __name__ == "__main__":
    asyncio.run(stdio_server(server))
```

Register and use the custom server:

```python
manager.add_mcp_server(
    name="custom",
    command="python",
    args=["my_mcp_server.py"],
    capabilities=["text_processing", "analysis"]
)

# Connect and use
await manager.connect_mcp_server("custom")
result = await manager.call_provider(
    "custom",
    "analyze_text",
    text="Hello world",
    mode="detailed"
)
```

### Managing Server Lifecycle

```python
# Connect individual servers
success = await manager.connect_mcp_server("openai")
if success:
    print("✅ Connected to OpenAI server")

# Disconnect individual servers
await manager.disconnect_mcp_server("openai")

# Get server status
status = manager.mcp_manager.get_server_status("openai")
print(f"Server: {status['name']}")
print(f"Connected: {status['connected']}")
print(f"Last error: {status.get('last_error', 'None')}")

# Get summary of all MCP servers
summary = manager.mcp_manager.get_summary()
print(f"Total servers: {summary['total_servers']}")
print(f"Connected: {summary['connected_servers']}")
```

### Error Handling

```python
from gleitzeit_extensions.exceptions import ExtensionError, ExtensionNotFound

async def safe_provider_call():
    try:
        # Try to call a provider
        result = await manager.call_provider(
            "my_provider",
            "some_method",
            param="value"
        )
        return result
        
    except ExtensionNotFound as e:
        print(f"Provider not found: {e}")
        
    except ExtensionError as e:
        print(f"Provider error: {e}")
        
    except Exception as e:
        print(f"Unexpected error: {e}")
```

## Best Practices

### 1. Choose the Right Provider Type

**Use Native Extensions for:**
- Gleitzeit-specific business logic
- Performance-critical operations
- Tight integration with cluster state
- Complex Python-based processing

**Use MCP Servers for:**
- LLM provider integrations
- External tool access (databases, APIs)
- Language-agnostic services
- Isolated, reusable components

### 2. Environment Variables

Store sensitive data in environment variables:

```bash
# .env file
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export BRAVE_API_KEY="BSA..."
```

Load in configuration:

```json
{
  "env": {
    "OPENAI_API_KEY": "${OPENAI_API_KEY}"
  }
}
```

### 3. Connection Management

```python
# Always use context managers for automatic cleanup
async with manager:
    # Providers are started
    await do_work()
# Providers are stopped

# Or manage manually with try/finally
try:
    await manager.start_all_providers()
    await do_work()
finally:
    await manager.stop_all_providers()
```

### 4. Caching and Performance

The UnifiedProviderManager includes built-in caching:

```python
# Model routing is cached after first lookup
model1 = manager.find_provider_for_model("gpt-4")  # Searches all providers
model2 = manager.find_provider_for_model("gpt-4")  # Returns cached result

# Clear cache when providers change
manager._model_routing_cache.clear()
```

### 5. Health Monitoring

```python
async def monitor_providers():
    while True:
        providers = manager.get_all_providers()
        
        for name, provider in providers.items():
            if provider.connected and provider.health_status:
                health = provider.health_status
                print(f"{name}: {health.get('status', 'unknown')}")
        
        await asyncio.sleep(30)  # Check every 30 seconds
```

## Troubleshooting

### MCP Not Available

**Problem:** "MCP not available" error

**Solution:**
```bash
# Install MCP with CLI support
pip install 'mcp[cli]'
# or
uv pip install 'mcp[cli]'
```

### MCP Server Connection Failed

**Problem:** "Failed to connect to MCP server"

**Causes and Solutions:**

1. **Server not installed:**
   ```bash
   npm install -g @modelcontextprotocol/server-name
   ```

2. **Wrong command path:**
   ```python
   # Specify full path if needed
   manager.add_mcp_server(
       name="server",
       command="/usr/local/bin/mcp-server-name"
   )
   ```

3. **Missing environment variables:**
   ```python
   import os
   os.environ["API_KEY"] = "your-key"
   ```

### Model Not Found

**Problem:** Model routing returns None

**Solutions:**

1. **Check provider configuration:**
   ```python
   providers = manager.get_all_providers()
   for name, p in providers.items():
       print(f"{name}: {p.models}")
   ```

2. **Ensure provider is connected:**
   ```python
   await manager.start_all_providers()
   ```

3. **Clear routing cache:**
   ```python
   manager._model_routing_cache.clear()
   ```

### Import Errors

**Problem:** Cannot import MCP modules

**Solution:**
```bash
# Check Python environment
which python
python --version

# Install in correct environment
python -m pip install 'mcp[cli]'
```

## Example: Complete Application

Here's a complete example that demonstrates all features:

```python
#!/usr/bin/env python3
"""
Complete MCP + Native Extension Example
"""

import asyncio
import os
from pathlib import Path

from gleitzeit_extensions import (
    create_unified_manager,
    setup_standard_llm_providers,
    is_mcp_available
)

async def main():
    # Setup
    manager = create_unified_manager()
    
    print("🚀 Gleitzeit Unified Provider Demo")
    print("=" * 40)
    
    # 1. Discover native extensions
    print("\n📦 Loading native extensions...")
    extensions_found = manager.discover_extensions(["./extensions"])
    print(f"Found {len(extensions_found)} native extensions")
    
    # 2. Setup MCP if available
    if is_mcp_available():
        print("\n📡 Setting up MCP servers...")
        
        # Add standard LLM providers
        setup_standard_llm_providers(manager)
        
        # Add custom configuration from file
        config_file = Path("mcp_servers.json")
        if config_file.exists():
            manager.load_mcp_servers_from_file(str(config_file))
        
        # Add a custom server programmatically
        if os.getenv("CUSTOM_API_KEY"):
            manager.add_mcp_server(
                name="custom",
                command="custom-mcp-server",
                env={"API_KEY": os.getenv("CUSTOM_API_KEY")},
                models=["custom-model"],
                capabilities=["text", "analysis"]
            )
    else:
        print("\n⚠️  MCP not available")
        print("   Install with: pip install 'mcp[cli]'")
    
    # 3. Start all providers
    print("\n🔌 Starting providers...")
    async with manager:
        results = await manager.start_all_providers()
        connected = sum(1 for success in results.values() if success)
        print(f"Connected: {connected}/{len(results)} providers")
        
        # 4. Show available resources
        print("\n📋 Available Resources:")
        
        # List all providers
        providers = manager.get_all_providers()
        print(f"\nProviders ({len(providers)}):")
        for name, provider in providers.items():
            status = "🟢" if provider.connected else "🔴"
            print(f"  {status} {name} ({provider.type})")
        
        # List all models
        models = manager.get_available_models()
        print(f"\nModels ({len(models)}):")
        for model_name in list(models.keys())[:10]:  # Show first 10
            info = models[model_name]
            print(f"  - {model_name} via {info['provider']}")
        if len(models) > 10:
            print(f"  ... and {len(models) - 10} more")
        
        # 5. Test model routing
        print("\n🎯 Testing Model Routing:")
        test_models = ["gpt-4", "claude-3-opus", "llama3", "custom-model"]
        
        for model in test_models:
            provider = manager.find_provider_for_model(model)
            if provider:
                print(f"  ✅ {model} → {provider['name']}")
            else:
                print(f"  ❌ {model} → not found")
        
        # 6. Test capability search
        print("\n🔍 Testing Capability Search:")
        test_capabilities = ["text", "vision", "function_calling"]
        
        for capability in test_capabilities:
            providers_list = manager.find_providers_by_capability(capability)
            if providers_list:
                names = [p['name'] for p in providers_list]
                print(f"  {capability}: {', '.join(names)}")
            else:
                print(f"  {capability}: none")
        
        # 7. Show summary
        summary = manager.get_summary()
        print("\n📊 Summary:")
        print(f"  Total providers: {summary['total_providers']}")
        print(f"  Extensions: {summary['extension_providers']}")
        print(f"  MCP servers: {summary['mcp_providers']}")
        print(f"  Connected: {summary['connected_providers']}")
        print(f"  Total models: {summary['total_models']}")
        
        print("\n✅ Demo completed successfully!")
    
    # Providers are automatically stopped when exiting context

if __name__ == "__main__":
    asyncio.run(main())
```

## Conclusion

The Gleitzeit MCP integration provides a powerful, unified interface for working with both native Python extensions and external MCP servers. This allows you to:

- Leverage existing MCP ecosystem tools
- Build language-agnostic integrations
- Maintain clean separation of concerns
- Scale your system with external services

For more information:
- [MCP Documentation](https://modelcontextprotocol.io)
- [Gleitzeit Documentation](https://github.com/leifk/gleitzeit)
- [Example Code](https://github.com/leifk/gleitzeit/tree/main/examples)