"""
Gleitzeit Hybrid Extension System

Combines native Python extensions with MCP (Model Context Protocol) servers
for maximum flexibility and standards compliance.

Key Features:
- Native Extensions: Fast Python integration for Gleitzeit-specific functionality
- MCP Servers: Standard protocol for LLM providers and external tools  
- Unified Interface: Seamless access to both types through single API
- Automatic Routing: Finds the right provider for any model
- Graceful Degradation: Works with or without MCP

Usage Examples:

    # Native Extensions Only
    from gleitzeit_extensions import ExtensionManager
    manager = ExtensionManager()
    manager.discover_extensions(["./extensions"])
    
    # Unified (Native + MCP) - Recommended  
    from gleitzeit_extensions import UnifiedProviderManager, setup_standard_llm_providers
    manager = UnifiedProviderManager()
    manager.discover_extensions(["./extensions"])
    setup_standard_llm_providers(manager)  # Adds OpenAI, Claude via MCP
    
    # Integrated with Cluster
    from gleitzeit_extensions.helpers import create_cluster_with_unified_providers
    cluster, manager = create_cluster_with_unified_providers(
        extension_paths=["./extensions"],
        setup_standard_mcp=True
    )
    
    # Model routing works across both types
    provider = manager.find_provider_for_model("gpt-4")  # Could be native or MCP
    result = await manager.call_provider("openai", "generate_text", "Hello")
"""

from .manager import ExtensionManager
from .decorators import extension, requires, model, capability
from .helpers import create_cluster_with_extensions
from .exceptions import ExtensionError, ExtensionNotFound, ExtensionConfigError
from .mcp_client import MCPClientManager, is_mcp_available
from .mcp_manager import UnifiedProviderManager, create_unified_manager, setup_standard_llm_providers

__version__ = "1.0.0"
__all__ = [
    'ExtensionManager',
    'extension',
    'requires', 
    'model',
    'capability',
    'create_cluster_with_extensions',
    'ExtensionError',
    'ExtensionNotFound',
    'ExtensionConfigError',
    'MCPClientManager',
    'is_mcp_available',
    'UnifiedProviderManager',
    'create_unified_manager',
    'setup_standard_llm_providers'
]