"""
Protocol providers for Gleitzeit V4

Clean protocol implementations for various execution backends.
All providers inherit from ProtocolProvider for clean separation of concerns.
"""

from gleitzeit.providers.base import ProtocolProvider, HTTPServiceProvider, WebSocketProvider
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.providers.python_provider import PythonProvider
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider

__all__ = [
    # Base classes
    "ProtocolProvider",
    "HTTPServiceProvider",
    "WebSocketProvider",
    # Concrete providers
    "OllamaProvider",
    "PythonProvider", 
    "SimpleMCPProvider"
]