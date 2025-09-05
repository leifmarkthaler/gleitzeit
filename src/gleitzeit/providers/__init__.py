"""
Protocol providers for Gleitzeit V4

Clean protocol implementations for various execution backends.
All providers inherit from ProtocolProvider for clean separation of concerns.

NEW SIMPLIFIED PROVIDERS:
- SimpleProvider: Implement only execute() method - 95% less code required
- HTTPProvider: Built-in HTTP/REST support with automatic error handling
- RESTProvider: Automatic endpoint mapping from configuration
- @provider decorator: Ultra-simple function-based providers
- Mixins: Circuit breaker, rate limiting, health monitoring
"""

from gleitzeit.providers.base import ProtocolProvider, HTTPServiceProvider, WebSocketProvider
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.mcp_hub_provider import MCPHubProvider
from gleitzeit.providers.shell_provider import ShellProvider
# SimpleMCPProvider has been moved to examples/simple_mcp_provider.py as a reference implementation

# New simplified providers
from gleitzeit.providers.simple import SimpleProvider
from gleitzeit.providers.http_provider import HTTPProvider, RESTProvider, create_simple_http_provider
from gleitzeit.providers.decorators import provider, method_handler, provider_class, simple_http_provider
from gleitzeit.providers.mixins import CircuitBreakerMixin, RateLimitMixin, HealthMonitorMixin

# Advanced features
from gleitzeit.providers.config_provider import ConfigProvider, load_config_provider, create_config_provider
from gleitzeit.providers.discovery import discover_service, discover_all_services, ServiceInfo

__all__ = [
    # Base classes
    "ProtocolProvider",
    "HTTPServiceProvider",
    "WebSocketProvider",
    
    # Original concrete providers
    "OllamaProvider",
    "PythonProvider", 
    "MCPHubProvider",
    "ShellProvider",
    
    # NEW: Simplified providers (95% less code required)
    "SimpleProvider",           # Implement only execute() method
    "HTTPProvider",             # Built-in HTTP with retry/error handling
    "RESTProvider",             # Automatic endpoint mapping
    "create_simple_http_provider",  # Factory function
    
    # NEW: Decorators for ultra-simple providers
    "provider",                 # @provider decorator for functions
    "method_handler",           # @method_handler for class methods
    "provider_class",           # @provider_class for classes
    "simple_http_provider",     # HTTP provider from config
    
    # NEW: Mixins for enhanced functionality
    "CircuitBreakerMixin",      # Automatic circuit breaker
    "RateLimitMixin",           # Token bucket rate limiting
    "HealthMonitorMixin",       # Enhanced health monitoring
    
    # NEW: Advanced features (Service discovery, Config providers)
    "ConfigProvider",           # YAML/JSON configuration-based providers
    "load_config_provider",     # Load provider from config file
    "create_config_provider",   # Create provider from config dict
    "discover_service",         # Service discovery function
    "discover_all_services",    # Discover all available services
    "ServiceInfo"               # Service information dataclass
]