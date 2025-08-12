"""
Unified MCP + Extension Manager

This module provides a unified interface that combines both native Gleitzeit extensions
and MCP (Model Context Protocol) servers, presenting a seamless API for model routing
and capability management.
"""

import asyncio
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass

from .manager import ExtensionManager
from .mcp_client import MCPClientManager, MCPServerConfig, is_mcp_available
from .exceptions import ExtensionError, ExtensionNotFound


@dataclass
class ProviderInfo:
    """Unified information about a provider (extension or MCP server)"""
    name: str
    type: str  # "extension" or "mcp"
    description: str
    models: List[str]
    capabilities: List[str]
    connected: bool
    loaded: bool = False
    health_status: Dict[str, Any] = None


class UnifiedProviderManager:
    """
    Unified manager for both native extensions and MCP servers
    
    Provides a single interface for:
    - Model routing (find provider for a model)
    - Capability discovery (find providers with specific capabilities)  
    - Lifecycle management (load, start, stop providers)
    - Health monitoring
    """
    
    def __init__(self):
        self.extension_manager = ExtensionManager()
        self.mcp_manager = MCPClientManager() if is_mcp_available() else None
        self._model_routing_cache: Dict[str, str] = {}
    
    def attach_to_cluster(self, cluster) -> None:
        """Attach to Gleitzeit cluster"""
        self.extension_manager.attach_to_cluster(cluster)
        print("🔌 Unified provider manager attached to cluster")
    
    # === Extension Management ===
    
    def discover_extensions(self, paths: Optional[List[str]] = None) -> List[str]:
        """Discover native extensions"""
        return self.extension_manager.discover_extensions(paths)
    
    def load_extension(self, name: str, **config) -> Any:
        """Load a native extension"""
        return self.extension_manager.load_extension(name, **config)
    
    async def start_extension(self, name: str) -> None:
        """Start a native extension"""
        await self.extension_manager.start_extension(name)
    
    async def stop_extension(self, name: str) -> None:
        """Stop a native extension"""
        await self.extension_manager.stop_extension(name)
    
    # === MCP Management ===
    
    def add_mcp_server(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        models: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
        description: str = ""
    ) -> None:
        """Add an MCP server configuration"""
        if not self.mcp_manager:
            raise ExtensionError("MCP not available. Install with: pip install 'mcp[cli]'")
        
        self.mcp_manager.add_server(
            name=name,
            command=command,
            args=args,
            env=env,
            models=models,
            capabilities=capabilities,
            description=description
        )
        
        # Clear routing cache since we added a new provider
        self._model_routing_cache.clear()
    
    def load_mcp_servers_from_file(self, config_file: str) -> None:
        """Load MCP server configurations from file"""
        if not self.mcp_manager:
            raise ExtensionError("MCP not available")
        
        self.mcp_manager.load_servers_from_file(config_file)
        self._model_routing_cache.clear()
    
    async def connect_mcp_server(self, name: str) -> bool:
        """Connect to an MCP server"""
        if not self.mcp_manager:
            return False
        
        return await self.mcp_manager.connect_server(name)
    
    async def disconnect_mcp_server(self, name: str) -> None:
        """Disconnect from an MCP server"""
        if self.mcp_manager:
            await self.mcp_manager.disconnect_server(name)
    
    # === Unified Interface ===
    
    def get_all_providers(self) -> Dict[str, ProviderInfo]:
        """Get information about all providers (extensions + MCP servers)"""
        providers = {}
        
        # Add native extensions
        for name, ext_info in self.extension_manager.list_available().items():
            loaded = self.extension_manager.is_loaded(name)
            
            # Get health status if loaded
            health_status = None
            if loaded:
                try:
                    info = self.extension_manager.get_extension_info(name)
                    health_status = info.get('health', {})
                except Exception:
                    pass
            
            providers[name] = ProviderInfo(
                name=name,
                type="extension",
                description=ext_info.meta.description,
                models=[m.get('name', 'unknown') for m in ext_info.meta.models],
                capabilities=ext_info.meta.capabilities,
                connected=loaded,  # For extensions, loaded == connected
                loaded=loaded,
                health_status=health_status
            )
        
        # Add MCP servers
        if self.mcp_manager:
            for name, server_config in self.mcp_manager.servers.items():
                connected = (
                    name in self.mcp_manager.connections and 
                    self.mcp_manager.connections[name].connected
                )
                
                providers[name] = ProviderInfo(
                    name=name,
                    type="mcp",
                    description=server_config.description,
                    models=server_config.models,
                    capabilities=server_config.capabilities,
                    connected=connected,
                    loaded=connected,  # For MCP servers, connected == loaded
                    health_status={"healthy": connected} if connected else None
                )
        
        return providers
    
    def get_available_models(self) -> Dict[str, Dict[str, Any]]:
        """Get all available models from all providers"""
        models = {}
        
        # Models from native extensions
        for name, provider in self.get_all_providers().items():
            for model_name in provider.models:
                models[model_name] = {
                    "provider": name,
                    "provider_type": provider.type,
                    "capabilities": provider.capabilities,
                    "connected": provider.connected
                }
        
        return models
    
    def find_provider_for_model(self, model: str) -> Optional[Dict[str, Any]]:
        """
        Find which provider (extension or MCP server) supports a model
        
        Returns:
            Dictionary with provider information, or None if not found
        """
        # Check cache first
        if model in self._model_routing_cache:
            cached_provider = self._model_routing_cache[model]
            providers = self.get_all_providers()
            if cached_provider in providers:
                provider = providers[cached_provider]
                return {
                    "name": provider.name,
                    "type": provider.type,
                    "connected": provider.connected
                }
        
        # Search all providers
        providers = self.get_all_providers()
        for provider_name, provider in providers.items():
            if model in provider.models:
                # Cache the result
                self._model_routing_cache[model] = provider_name
                
                return {
                    "name": provider.name,
                    "type": provider.type,
                    "connected": provider.connected
                }
        
        return None
    
    def find_providers_by_capability(self, capability: str) -> List[Dict[str, Any]]:
        """Find all providers that support a specific capability"""
        matching_providers = []
        
        for provider in self.get_all_providers().values():
            if capability in provider.capabilities:
                matching_providers.append({
                    "name": provider.name,
                    "type": provider.type,
                    "connected": provider.connected,
                    "models": provider.models
                })
        
        return matching_providers
    
    # === Unified Operations ===
    
    async def start_all_providers(self) -> Dict[str, bool]:
        """Start all providers (extensions + MCP servers)"""
        results = {}
        
        print("🚀 Starting all providers...")
        
        # Start native extensions
        try:
            await self.extension_manager.start_all_extensions()
            for name in self.extension_manager.list_loaded():
                results[name] = True
        except Exception as e:
            print(f"❌ Error starting extensions: {e}")
        
        # Connect MCP servers
        if self.mcp_manager:
            try:
                mcp_results = await self.mcp_manager.connect_all_servers()
                results.update(mcp_results)
            except Exception as e:
                print(f"❌ Error connecting MCP servers: {e}")
        
        started_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        print(f"✅ Started {started_count}/{total_count} providers")
        
        return results
    
    async def stop_all_providers(self) -> None:
        """Stop all providers (extensions + MCP servers)"""
        print("🛑 Stopping all providers...")
        
        # Stop native extensions
        try:
            await self.extension_manager.stop_all_extensions()
        except Exception as e:
            print(f"⚠️ Error stopping extensions: {e}")
        
        # Disconnect MCP servers
        if self.mcp_manager:
            try:
                await self.mcp_manager.disconnect_all_servers()
            except Exception as e:
                print(f"⚠️ Error disconnecting MCP servers: {e}")
        
        print("✅ All providers stopped")
    
    async def call_provider(
        self, 
        provider_name: str, 
        method: str, 
        *args, 
        **kwargs
    ) -> Any:
        """
        Call a method on a provider (extension or MCP server)
        
        Args:
            provider_name: Name of provider
            method: Method/tool name to call
            *args, **kwargs: Arguments to pass
            
        Returns:
            Result from the provider
        """
        providers = self.get_all_providers()
        if provider_name not in providers:
            raise ExtensionNotFound(f"Provider '{provider_name}' not found")
        
        provider = providers[provider_name]
        
        if not provider.connected:
            raise ExtensionError(f"Provider '{provider_name}' not connected")
        
        if provider.type == "extension":
            # Call native extension method
            extension_instance = self.extension_manager.loaded_extensions.get(provider_name)
            if not extension_instance:
                raise ExtensionError(f"Extension '{provider_name}' not loaded")
            
            if not hasattr(extension_instance, method):
                raise ExtensionError(f"Extension '{provider_name}' does not have method '{method}'")
            
            method_func = getattr(extension_instance, method)
            if asyncio.iscoroutinefunction(method_func):
                return await method_func(*args, **kwargs)
            else:
                return method_func(*args, **kwargs)
        
        elif provider.type == "mcp":
            # Call MCP server tool
            if not self.mcp_manager:
                raise ExtensionError("MCP manager not available")
            
            # Convert args/kwargs to MCP arguments format
            arguments = kwargs.copy()
            if args:
                # If positional args provided, need to map them somehow
                # This is a simple approach - could be more sophisticated
                for i, arg in enumerate(args):
                    arguments[f"arg_{i}"] = arg
            
            return await self.mcp_manager.call_tool(provider_name, method, arguments)
        
        else:
            raise ExtensionError(f"Unknown provider type: {provider.type}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive summary of all providers"""
        providers = self.get_all_providers()
        models = self.get_available_models()
        
        extension_count = sum(1 for p in providers.values() if p.type == "extension")
        mcp_count = sum(1 for p in providers.values() if p.type == "mcp")
        connected_count = sum(1 for p in providers.values() if p.connected)
        
        return {
            "total_providers": len(providers),
            "extension_providers": extension_count,
            "mcp_providers": mcp_count,
            "connected_providers": connected_count,
            "total_models": len(models),
            "providers": {name: {
                "type": p.type,
                "description": p.description,
                "models": p.models,
                "capabilities": p.capabilities,
                "connected": p.connected
            } for name, p in providers.items()},
            "models": models
        }
    
    # === Context Manager Support ===
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.start_all_providers()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.stop_all_providers()


# Convenience functions for backward compatibility
def create_unified_manager() -> UnifiedProviderManager:
    """Create a unified provider manager"""
    return UnifiedProviderManager()


def setup_standard_llm_providers(manager: UnifiedProviderManager) -> None:
    """Set up standard LLM providers using MCP where available"""
    if manager.mcp_manager:
        from .mcp_client import create_standard_llm_servers
        
        print("📡 Setting up standard LLM providers via MCP...")
        
        servers = create_standard_llm_servers()
        for server_config in servers.values():
            try:
                manager.add_mcp_server(**server_config)
                print(f"  ✅ Added MCP server: {server_config['name']}")
            except Exception as e:
                print(f"  ⚠️ Failed to add MCP server {server_config['name']}: {e}")
    else:
        print("⚠️ MCP not available, skipping standard LLM provider setup")
        print("   Install with: pip install 'mcp[cli]'")