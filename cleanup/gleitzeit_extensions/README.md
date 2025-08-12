# Gleitzeit Extensions

A clean, flexible extension system for Gleitzeit that supports both decorator-based and config-based extension definitions.

## Overview

The extension system allows you to easily integrate external LLM providers (like OpenAI, Claude, etc.) and custom services with your Gleitzeit cluster while keeping the core library minimal and focused.

## Features

- **Dual Definition Styles**: Choose between decorator-based (code-first) or config-based (YAML) extensions
- **Automatic Discovery**: Extensions are automatically discovered from filesystem paths
- **Dependency Management**: Automatic validation of Python package dependencies
- **Configuration System**: Flexible configuration with environment variable support
- **Lifecycle Management**: Full lifecycle support (load, start, stop, unload)
- **Model Routing**: Automatic routing of requests to appropriate extensions based on model names
- **Health Monitoring**: Built-in health checks for loaded extensions

## Quick Start

### Installation

```bash
# The extension system is included with gleitzeit_cluster
pip install gleitzeit_cluster
```

### Basic Usage

```python
from gleitzeit_extensions import ExtensionManager
from gleitzeit_extensions.helpers import create_cluster_with_extensions

# Method 1: Direct extension manager usage
manager = ExtensionManager()
manager.discover_extensions(["./extensions"])
manager.load_extension("openai", api_key="your-key")
await manager.start_all_extensions()

# Method 2: Integrated with cluster  
cluster, ext_manager = create_cluster_with_extensions(
    search_paths=["./extensions"],
    extensions=["openai", "claude"],
    extension_configs={
        "openai": {"api_key": "your-openai-key"},
        "claude": {"api_key": "your-claude-key"}
    }
)
```

## Extension Definition Methods

### 1. Decorator-Based Extensions (Code-First)

Create a Python file with decorated classes:

```python
from gleitzeit_extensions.decorators import (
    extension, requires, model, capability, config_field
)

@extension(name="my-provider", description="My LLM provider", version="1.0.0")
@requires("requests>=2.0", "some-llm-sdk>=1.0")
@model("my-model", capabilities=["text", "vision"], max_tokens=4096)
@capability("streaming", "function_calling")
@config_field("api_key", required=True, env_var="MY_PROVIDER_API_KEY")
@config_field("timeout", field_type="integer", default=60)
class MyProviderExtension:
    def __init__(self, api_key: str, timeout: int = 60, **kwargs):
        self.api_key = api_key
        self.timeout = timeout
    
    async def setup(self):
        # Initialize your provider client
        pass
    
    async def start(self):
        # Start your service (e.g., Socket.IO handlers)
        pass
    
    async def stop(self):
        # Clean up resources
        pass
    
    def health_check(self):
        return {"healthy": True, "provider": "my-provider"}
```

### 2. Config-Based Extensions (YAML)

Create an `extension.yaml` file:

```yaml
name: my-provider
description: My LLM provider integration
version: 1.0.0
author: Your Name

models:
  - name: my-model
    capabilities: [text, vision]
    max_tokens: 4096
    cost_per_token: 0.00001

capabilities: [streaming, function_calling]

dependencies:
  packages:
    - requests>=2.0
    - some-llm-sdk>=1.0

config:
  api_key:
    type: string
    required: true
    env_var: MY_PROVIDER_API_KEY
    description: API key for the provider
  
  timeout:
    type: integer
    default: 60
    min: 10
    max: 300
    description: Request timeout in seconds

service:
  class_path: service.MyProviderService
```

Then create a `service.py` file:

```python
from gleitzeit_extensions.config_loader import ConfigBasedExtension

class MyProviderService(ConfigBasedExtension):
    def __init__(self, config):
        super().__init__(config)
        # Access config via self.config
    
    async def setup(self):
        # Initialize your provider
        pass
    
    # Implement other methods...
```

## Directory Structure

### Decorator-based extensions
```
extensions/
├── openai_extension.py           # Single-file extension
└── custom_provider/              # Package-based extension
    ├── __init__.py
    └── extension.py
```

### Config-based extensions
```
extensions/
├── claude_extension/
│   ├── extension.yaml            # Configuration
│   └── service.py                # Implementation
└── other_provider/
    ├── extension.yaml
    ├── service.py
    └── utils.py                   # Additional modules
```

## Configuration

### Environment Variables

Extensions automatically support environment variables:

```python
# Decorator-based
@config_field("api_key", env_var="OPENAI_API_KEY")

# Config-based (YAML)
config:
  api_key:
    env_var: OPENAI_API_KEY
```

### Runtime Configuration

```python
# Load with specific configuration
manager.load_extension("openai", api_key="key", timeout=30)

# Or use environment variables
os.environ["OPENAI_API_KEY"] = "your-key"
manager.load_extension("openai")  # Uses env var
```

## Extension Discovery

Extensions are discovered from specified search paths:

```python
manager = ExtensionManager()

# Discover from default paths
manager.discover_extensions()  # Uses ["extensions/"]

# Discover from custom paths
manager.discover_extensions([
    "./custom_extensions", 
    "./third_party_extensions",
    "/opt/gleitzeit/extensions"
])
```

## Model Routing

The extension system provides automatic model routing:

```python
# Find which extension provides a model
provider = manager.find_extension_for_model("gpt-4")  # Returns "openai"

# Get all available models
from gleitzeit_extensions.helpers import get_available_models
models = get_available_models(manager)
# Returns: {"gpt-4": {"extension": "openai", "capabilities": ["text"]}}

# Route through cluster
cluster = GleitzeitCluster()
cluster.set_extension_manager(manager)
provider = await cluster.find_provider_for_model("gpt-4")
```

## Health Monitoring

Extensions can provide health status:

```python
# Check specific extension
info = manager.get_extension_info("openai")
health = info.get("health", {})

# Generate summary report
from gleitzeit_extensions.helpers import create_extension_summary_report
report = create_extension_summary_report(manager)
print(report)
```

## Error Handling

The extension system provides comprehensive error handling:

- `ExtensionNotFound`: Extension not registered
- `ExtensionLoadError`: Failed to load extension
- `ExtensionConfigError`: Configuration validation failed
- `ExtensionDependencyError`: Missing dependencies
- `ExtensionValidationError`: Extension structure invalid

## Examples

See the `examples/extensions/` directory for complete examples:

- `openai_extension.py` - Decorator-based OpenAI integration
- `claude_extension/` - Config-based Claude integration  
- `extension_usage_demo.py` - Usage demonstrations

## API Reference

### ExtensionManager

Main extension manager class:

```python
manager = ExtensionManager(cluster=None)

# Discovery and registration
manager.discover_extensions(paths=None) -> List[str]
manager.list_available() -> Dict[str, ExtensionInfo]

# Loading and lifecycle
manager.load_extension(name, **config) -> Any
manager.start_extension(name) -> None
manager.stop_extension(name) -> None
manager.unload_extension(name) -> None

# Batch operations
manager.start_all_extensions() -> None  
manager.stop_all_extensions() -> None

# Information and utilities
manager.get_extension_info(name) -> Dict[str, Any]
manager.find_extension_for_model(model) -> Optional[str]
manager.get_summary() -> Dict[str, Any]
```

### Helper Functions

```python
# Cluster integration
create_cluster_with_extensions(**kwargs) -> Tuple[cluster, manager]
start_cluster_with_extensions(cluster, manager) -> None
stop_cluster_with_extensions(cluster, manager) -> None

# Utilities
get_available_models(manager) -> Dict[str, Any]
get_extensions_by_capability(manager, capability) -> List[str]
validate_all_dependencies(manager) -> Dict[str, Dict[str, Any]]
create_extension_summary_report(manager) -> str
```

## Best Practices

1. **Use environment variables** for sensitive configuration like API keys
2. **Implement health checks** for monitoring extension status
3. **Handle errors gracefully** in extension methods
4. **Document your extensions** with clear descriptions and examples
5. **Version your extensions** for compatibility tracking
6. **Test dependencies** before distributing extensions
7. **Use semantic versioning** for extension versions

## Contributing

When creating new extensions:

1. Follow the established patterns (decorator or config-based)
2. Include comprehensive error handling
3. Provide health check implementation
4. Document configuration options
5. Include usage examples
6. Test with various configurations

## License

This extension system is part of the Gleitzeit project and follows the same licensing terms.