"""
MCP Integration Helper for Gleitzeit V4

Provides utilities for easily integrating MCP servers into Gleitzeit workflows.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from gleitzeit.providers.mcp_provider import MCPProvider, create_mcp_provider
from gleitzeit.core.protocol import ProtocolSpec, MethodSpec
from gleitzeit.registry import ProtocolProviderRegistry

logger = logging.getLogger(__name__)


class MCPIntegration:
    """Helper class for integrating MCP servers with Gleitzeit"""
    
    def __init__(self, registry: ProtocolProviderRegistry):
        self.registry = registry
        self.mcp_providers: Dict[str, MCPProvider] = {}
    
    async def add_mcp_server(self, config: Dict[str, Any]) -> MCPProvider:
        """
        Add an MCP server to Gleitzeit
        
        Args:
            config: MCP server configuration
            
        Returns:
            The created MCP provider
            
        Example:
            await integration.add_mcp_server({
                "provider_id": "filesystem-mcp",
                "name": "filesystem", 
                "description": "Filesystem operations",
                "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
                "args": ["/home/user/documents"]
            })
        """
        provider = create_mcp_provider(config)
        
        # Initialize the MCP provider
        await provider.initialize()
        
        # Create protocol spec based on MCP capabilities
        protocol_spec = self._create_protocol_from_mcp(provider)
        
        # Register protocol and provider
        self.registry.register_protocol(protocol_spec)
        self.registry.register_provider(
            provider.provider_id,
            provider.protocol_id,
            provider
        )
        
        self.mcp_providers[provider.provider_id] = provider
        
        logger.info(f"Successfully integrated MCP server: {provider.name}")
        logger.info(f"Available tools: {list(provider.tools.keys())}")
        logger.info(f"Available resources: {list(provider.resources.keys())}")
        logger.info(f"Available prompts: {list(provider.prompts.keys())}")
        
        return provider
    
    async def remove_mcp_server(self, provider_id: str):
        """Remove an MCP server from Gleitzeit"""
        if provider_id in self.mcp_providers:
            provider = self.mcp_providers[provider_id]
            
            # Unregister from registry
            self.registry.unregister_provider(provider_id)
            
            # Shutdown MCP provider
            await provider.shutdown()
            
            del self.mcp_providers[provider_id]
            logger.info(f"Removed MCP server: {provider.name}")
    
    async def list_mcp_servers(self) -> List[Dict[str, Any]]:
        """List all registered MCP servers"""
        servers = []
        
        for provider_id, provider in self.mcp_providers.items():
            health = await provider.health_check()
            
            servers.append({
                "provider_id": provider_id,
                "name": provider.name,
                "protocol_id": provider.protocol_id,
                "description": provider.description,
                "status": health["status"],
                "capabilities": provider.capabilities,
                "tools": list(provider.tools.keys()),
                "resources": list(provider.resources.keys()),
                "prompts": list(provider.prompts.keys())
            })
        
        return servers
    
    def _create_protocol_from_mcp(self, provider: MCPProvider) -> ProtocolSpec:
        """Create Gleitzeit protocol spec from MCP provider capabilities"""
        methods = {}
        
        # Add server info methods
        methods["server_info"] = MethodSpec(
            name="server_info",
            description="Get MCP server information and capabilities"
        )
        methods["list_tools"] = MethodSpec(
            name="list_tools", 
            description="List available MCP tools"
        )
        methods["list_resources"] = MethodSpec(
            name="list_resources",
            description="List available MCP resources"
        )
        methods["list_prompts"] = MethodSpec(
            name="list_prompts",
            description="List available MCP prompts"
        )
        
        # Add tool methods
        for tool_name, tool_info in provider.tools.items():
            method_name = f"tool.{tool_name}"
            methods[method_name] = MethodSpec(
                name=method_name,
                description=tool_info.get("description", f"Execute tool: {tool_name}")
            )
        
        # Add resource methods
        for resource_uri, resource_info in provider.resources.items():
            method_name = f"resource.{resource_uri}"
            methods[method_name] = MethodSpec(
                name=method_name,
                description=resource_info.get("description", f"Get resource: {resource_uri}")
            )
        
        # Add prompt methods
        for prompt_name, prompt_info in provider.prompts.items():
            method_name = f"prompt.{prompt_name}"
            methods[method_name] = MethodSpec(
                name=method_name,
                description=prompt_info.get("description", f"Get prompt: {prompt_name}")
            )
        
        return ProtocolSpec(
            name=provider.server_config.get("name", "mcp"),
            version="v1",
            description=f"MCP Integration: {provider.description}",
            methods=methods
        )
    
    async def shutdown_all(self):
        """Shutdown all MCP servers"""
        for provider_id in list(self.mcp_providers.keys()):
            await self.remove_mcp_server(provider_id)


# Predefined MCP server configurations
COMMON_MCP_SERVERS = {
    "filesystem": {
        "provider_id": "filesystem-mcp",
        "name": "filesystem",
        "description": "File system operations",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
        "args": []  # Add directory paths as needed
    },
    
    "sqlite": {
        "provider_id": "sqlite-mcp",
        "name": "sqlite",
        "description": "SQLite database operations",
        "command": ["npx", "-y", "@modelcontextprotocol/server-sqlite"],
        "args": []  # Add database paths as needed
    },
    
    "github": {
        "provider_id": "github-mcp",
        "name": "github",
        "description": "GitHub API operations",
        "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
        "args": [],
        "env": {
            # "GITHUB_PERSONAL_ACCESS_TOKEN": "your_token_here"
        }
    },
    
    "postgres": {
        "provider_id": "postgres-mcp",
        "name": "postgres",
        "description": "PostgreSQL database operations", 
        "command": ["npx", "-y", "@modelcontextprotocol/server-postgres"],
        "args": [],
        "env": {
            # "POSTGRES_CONNECTION_STRING": "postgresql://user:pass@host:port/db"
        }
    },
    
    "brave-search": {
        "provider_id": "brave-search-mcp",
        "name": "brave-search",
        "description": "Brave Search API",
        "command": ["npx", "-y", "@modelcontextprotocol/server-brave-search"],
        "args": [],
        "env": {
            # "BRAVE_API_KEY": "your_api_key_here"
        }
    },
    
    "puppeteer": {
        "provider_id": "puppeteer-mcp",
        "name": "puppeteer",
        "description": "Web browser automation",
        "command": ["npx", "-y", "@modelcontextprotocol/server-puppeteer"],
        "args": []
    }
}


async def create_mcp_integration(
    registry: ProtocolProviderRegistry,
    servers_config: Optional[List[Dict[str, Any]]] = None
) -> MCPIntegration:
    """
    Create MCP integration with optional server configurations
    
    Args:
        registry: Gleitzeit provider registry
        servers_config: List of MCP server configurations to add
        
    Returns:
        MCPIntegration instance
        
    Example:
        integration = await create_mcp_integration(registry, [
            {
                "provider_id": "my-filesystem",
                "name": "filesystem",
                "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
                "args": ["/home/user/documents"]
            }
        ])
    """
    integration = MCPIntegration(registry)
    
    if servers_config:
        for config in servers_config:
            try:
                await integration.add_mcp_server(config)
            except Exception as e:
                logger.error(f"Failed to add MCP server {config.get('provider_id')}: {e}")
    
    return integration


def get_common_mcp_config(server_name: str, **overrides) -> Dict[str, Any]:
    """
    Get configuration for common MCP servers with optional overrides
    
    Args:
        server_name: Name of the common server (filesystem, sqlite, etc.)
        **overrides: Configuration values to override
        
    Returns:
        MCP server configuration
        
    Example:
        config = get_common_mcp_config("filesystem", 
                                      provider_id="my-fs",
                                      args=["/path/to/directory"])
    """
    if server_name not in COMMON_MCP_SERVERS:
        available = list(COMMON_MCP_SERVERS.keys())
        raise ValueError(f"Unknown MCP server: {server_name}. Available: {available}")
    
    config = COMMON_MCP_SERVERS[server_name].copy()
    config.update(overrides)
    
    return config