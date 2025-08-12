"""
Extension Manager

Main extension manager that handles loading, starting, and coordinating extensions
with the core Gleitzeit cluster.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

from .registry import ExtensionRegistry, ExtensionInfo, global_registry
from .discovery import ExtensionDiscovery
from .config_loader import ConfigExtensionLoader
from .exceptions import (
    ExtensionError, ExtensionNotFound, ExtensionLoadError, 
    ExtensionDependencyError, ExtensionConfigError
)


class ExtensionManager:
    """
    Main extension manager for Gleitzeit
    
    Handles discovery, loading, configuration, and lifecycle management
    of both decorator-based and config-based extensions.
    """
    
    def __init__(self, cluster=None):
        self.cluster = cluster
        self.registry = global_registry
        self.discovery = ExtensionDiscovery()
        self.config_loader = ConfigExtensionLoader()
        self.loaded_extensions: Dict[str, Any] = {}
        self.running_services: List[Any] = []
        self._auto_discover_paths = ["extensions/"]
    
    def attach_to_cluster(self, cluster) -> None:
        """Attach extension manager to Gleitzeit cluster"""
        self.cluster = cluster
        if hasattr(cluster, 'set_extension_manager'):
            cluster.set_extension_manager(self)
        print(f"🔌 Extension manager attached to cluster")
    
    def discover_extensions(self, paths: Optional[List[str]] = None) -> List[str]:
        """
        Discover available extensions in filesystem
        
        Args:
            paths: Directories to search for extensions
            
        Returns:
            List of discovered extension names
        """
        search_paths = paths or self._auto_discover_paths
        discovered = self.discovery.discover_all(search_paths)
        
        print(f"🔍 Discovered {len(discovered)} extensions:")
        for info in discovered:
            print(f"   - {info.name} ({info.type})")
            
        return [info.name for info in discovered]
    
    def list_available(self) -> Dict[str, ExtensionInfo]:
        """List all available (registered) extensions"""
        return self.registry.list_extensions()
    
    def list_loaded(self) -> Dict[str, Any]:
        """List currently loaded extensions"""
        return self.loaded_extensions.copy()
    
    def is_loaded(self, name: str) -> bool:
        """Check if extension is loaded"""
        return name in self.loaded_extensions
    
    def load_extension(self, name: str, **config) -> Any:
        """
        Load an extension with configuration
        
        Args:
            name: Extension name to load
            **config: Extension configuration parameters
            
        Returns:
            Loaded extension instance
        """
        if self.is_loaded(name):
            print(f"⚠️  Extension '{name}' already loaded")
            return self.loaded_extensions[name]
        
        # Get extension info from registry
        try:
            info = self.registry.get_extension(name)
        except ExtensionNotFound:
            # Try to discover if not found
            self.discover_extensions()
            info = self.registry.get_extension(name)
        
        print(f"🔄 Loading extension: {name}")
        
        # Validate dependencies
        deps_ok, missing = self.registry.validate_dependencies(name)
        if not deps_ok:
            raise ExtensionDependencyError(name, missing)
        
        # Load based on type
        try:
            if info.type == "decorator":
                instance = self._load_decorator_extension(info, config)
            elif info.type == "config":
                instance = self._load_config_extension(info, config)
            else:
                raise ExtensionLoadError(name, f"Unknown extension type: {info.type}")
            
            # Store loaded instance
            self.loaded_extensions[name] = instance
            info.loaded = True
            info.instance = instance
            
            print(f"✅ Loaded extension: {name}")
            return instance
            
        except Exception as e:
            raise ExtensionLoadError(name, str(e))
    
    def _load_decorator_extension(self, info: ExtensionInfo, config: Dict[str, Any]) -> Any:
        """Load decorator-based extension"""
        extension_cls = info.extension_class
        if not extension_cls:
            raise ExtensionLoadError(info.name, "Extension class not found")
        
        # Merge environment variables with provided config
        merged_config = self._merge_config_with_env(info.meta.config_schema, config)
        
        # Validate required config
        self._validate_extension_config(info.name, info.meta.config_schema, merged_config)
        
        # Instantiate extension
        instance = extension_cls(**merged_config)
        
        return instance
    
    def _load_config_extension(self, info: ExtensionInfo, config: Dict[str, Any]) -> Any:
        """Load config-based extension"""
        return self.config_loader.load_extension(info, config)
    
    def _merge_config_with_env(self, schema: Dict[str, Any], provided_config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge provided config with environment variables"""
        merged = provided_config.copy()
        
        for field_name, field_info in schema.items():
            if field_name not in merged:
                # Check environment variable
                env_var = field_info.get('env_var')
                if env_var and env_var in os.environ:
                    merged[field_name] = os.environ[env_var]
                elif 'default' in field_info:
                    merged[field_name] = field_info['default']
        
        return merged
    
    def _validate_extension_config(self, name: str, schema: Dict[str, Any], config: Dict[str, Any]) -> None:
        """Validate extension configuration against schema"""
        errors = []
        
        for field_name, field_info in schema.items():
            if field_info.get('required', False) and field_name not in config:
                errors.append(f"Required field '{field_name}' missing")
        
        if errors:
            raise ExtensionConfigError(name, '; '.join(errors))
    
    async def start_extension(self, name: str) -> None:
        """Start a loaded extension"""
        if name not in self.loaded_extensions:
            raise ExtensionError(f"Extension '{name}' not loaded")
        
        instance = self.loaded_extensions[name]
        
        try:
            print(f"🚀 Starting extension: {name}")
            
            # Call setup if available
            if hasattr(instance, 'setup') and callable(instance.setup):
                if asyncio.iscoroutinefunction(instance.setup):
                    await instance.setup()
                else:
                    instance.setup()
            
            # Start service if available
            if hasattr(instance, 'start') and callable(instance.start):
                if asyncio.iscoroutinefunction(instance.start):
                    task = asyncio.create_task(instance.start())
                    self.running_services.append((name, instance, task))
                else:
                    instance.start()
            
            print(f"✅ Started extension: {name}")
            
        except Exception as e:
            raise ExtensionError(f"Failed to start extension '{name}': {e}")
    
    async def stop_extension(self, name: str) -> None:
        """Stop a running extension"""
        if name not in self.loaded_extensions:
            return
        
        instance = self.loaded_extensions[name]
        
        try:
            print(f"🛑 Stopping extension: {name}")
            
            # Stop service if running
            for service_name, service_instance, task in self.running_services[:]:
                if service_name == name:
                    if hasattr(service_instance, 'stop') and callable(service_instance.stop):
                        if asyncio.iscoroutinefunction(service_instance.stop):
                            await service_instance.stop()
                        else:
                            service_instance.stop()
                    task.cancel()
                    self.running_services.remove((service_name, service_instance, task))
            
            print(f"✅ Stopped extension: {name}")
            
        except Exception as e:
            print(f"⚠️ Error stopping extension '{name}': {e}")
    
    def unload_extension(self, name: str) -> None:
        """Unload an extension"""
        if name in self.loaded_extensions:
            del self.loaded_extensions[name]
        
        # Update registry
        try:
            info = self.registry.get_extension(name)
            info.loaded = False
            info.instance = None
        except ExtensionNotFound:
            pass
        
        print(f"📤 Unloaded extension: {name}")
    
    async def start_all_extensions(self) -> None:
        """Start all loaded extensions"""
        print(f"🚀 Starting {len(self.loaded_extensions)} extensions...")
        
        for name in self.loaded_extensions:
            try:
                await self.start_extension(name)
            except Exception as e:
                print(f"❌ Failed to start extension '{name}': {e}")
        
        print(f"✅ Started {len(self.running_services)} extension services")
    
    async def stop_all_extensions(self) -> None:
        """Stop all running extensions"""
        print(f"🛑 Stopping {len(self.running_services)} extension services...")
        
        for name in list(self.loaded_extensions.keys()):
            await self.stop_extension(name)
        
        self.running_services.clear()
        print("✅ All extensions stopped")
    
    def get_extension_info(self, name: str) -> Dict[str, Any]:
        """Get detailed information about an extension"""
        try:
            info = self.registry.get_extension(name)
            
            result = {
                'name': info.name,
                'type': info.type,
                'version': info.meta.version,
                'description': info.meta.description,
                'author': info.meta.author,
                'models': info.meta.models,
                'capabilities': info.meta.capabilities,
                'dependencies': info.meta.dependencies,
                'loaded': info.loaded,
                'running': name in [s[0] for s in self.running_services]
            }
            
            if info.loaded and info.instance:
                # Add runtime information
                instance = info.instance
                if hasattr(instance, 'health_check'):
                    try:
                        if asyncio.iscoroutinefunction(instance.health_check):
                            # Can't await here, just note it's available
                            result['health_check_available'] = True
                        else:
                            result['health'] = instance.health_check()
                    except Exception:
                        result['health'] = {'healthy': False, 'error': 'Health check failed'}
            
            return result
            
        except ExtensionNotFound:
            return {'name': name, 'found': False}
    
    def get_models_for_extension(self, name: str) -> List[Dict[str, Any]]:
        """Get models supported by a specific extension"""
        try:
            info = self.registry.get_extension(name)
            return info.meta.models
        except ExtensionNotFound:
            return []
    
    def find_extension_for_model(self, model_name: str) -> Optional[str]:
        """Find which extension supports a specific model"""
        return self.registry.find_extension_for_model(model_name)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of extension manager state"""
        return {
            'available_extensions': len(self.registry.list_extensions()),
            'loaded_extensions': len(self.loaded_extensions),
            'running_services': len(self.running_services),
            'extensions': self.registry.get_extension_summary()
        }


# Auto-discovery helper
def auto_discover_and_load_extensions(search_paths: Optional[List[str]] = None) -> ExtensionManager:
    """
    Convenience function to create extension manager and auto-discover extensions
    
    Args:
        search_paths: Paths to search for extensions
        
    Returns:
        Configured extension manager
    """
    manager = ExtensionManager()
    manager.discover_extensions(search_paths)
    return manager