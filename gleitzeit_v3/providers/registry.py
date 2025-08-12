"""
Provider Registry for Gleitzeit V3

This module provides automatic provider discovery and registration,
making it easy to add new providers without modifying core files.
"""

import importlib
import logging
import pkgutil
from typing import Dict, List, Type, Optional, Any
from pathlib import Path
import inspect
from .base import BaseProvider

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Automatic provider discovery and registration system.
    
    Features:
    - Auto-discovers providers in the providers directory
    - Validates provider implementations
    - Provides configuration management
    - Handles provider lifecycle
    """
    
    def __init__(self):
        self._providers: Dict[str, Type[BaseProvider]] = {}
        self._provider_configs: Dict[str, Dict[str, Any]] = {}
        self._discovered = False
    
    def discover_providers(self, providers_package: str = "gleitzeit_v3.providers") -> None:
        """
        Automatically discover all providers in the providers package.
        
        Args:
            providers_package: Python package path to search for providers
        """
        if self._discovered:
            return
            
        logger.info(f"🔍 Discovering providers in {providers_package}...")
        
        try:
            # Import the providers package
            package = importlib.import_module(providers_package)
            package_path = Path(package.__path__[0])
            
            # Walk through all Python files in the providers directory
            for importer, modname, ispkg in pkgutil.iter_modules(package.__path__):
                if modname in ['base', 'registry', '__init__']:
                    continue  # Skip base classes and registry
                
                full_module_name = f"{providers_package}.{modname}"
                
                try:
                    # Import the module
                    module = importlib.import_module(full_module_name)
                    
                    # Find provider classes in the module
                    self._discover_providers_in_module(module, modname)
                    
                except Exception as e:
                    logger.warning(f"Failed to import provider module {full_module_name}: {e}")
            
            self._discovered = True
            logger.info(f"✅ Discovered {len(self._providers)} providers: {list(self._providers.keys())}")
            
        except Exception as e:
            logger.error(f"Failed to discover providers: {e}")
    
    def _discover_providers_in_module(self, module: Any, module_name: str) -> None:
        """
        Discover provider classes within a specific module.
        
        Args:
            module: The imported module object
            module_name: Name of the module (for logging)
        """
        for name, obj in inspect.getmembers(module):
            # Check if it's a class that inherits from BaseProvider
            if (inspect.isclass(obj) and 
                issubclass(obj, BaseProvider) and 
                obj is not BaseProvider):
                
                # Validate the provider implementation
                if self._validate_provider_class(obj, name):
                    # Use the class name as the provider type
                    provider_type = self._get_provider_type(obj, name)
                    
                    self._providers[provider_type] = obj
                    logger.info(f"   📦 Registered provider: {provider_type} ({name})")
    
    def _validate_provider_class(self, provider_class: Type[BaseProvider], class_name: str) -> bool:
        """
        Validate that a provider class is properly implemented.
        
        Args:
            provider_class: The provider class to validate
            class_name: Name of the class (for logging)
            
        Returns:
            True if valid, False otherwise
        """
        required_methods = ['execute_task', 'health_check']
        
        for method_name in required_methods:
            if not hasattr(provider_class, method_name):
                logger.warning(f"Provider {class_name} missing required method: {method_name}")
                return False
            
            method = getattr(provider_class, method_name)
            if not inspect.iscoroutinefunction(method):
                logger.warning(f"Provider {class_name}.{method_name} must be async")
                return False
        
        return True
    
    def _get_provider_type(self, provider_class: Type[BaseProvider], class_name: str) -> str:
        """
        Determine the provider type name from the class.
        
        Args:
            provider_class: The provider class
            class_name: Name of the class
            
        Returns:
            Provider type string
        """
        # Try to get from class attribute first
        if hasattr(provider_class, 'PROVIDER_TYPE'):
            return provider_class.PROVIDER_TYPE
        
        # Convert class name to snake_case type
        # e.g., WebSearchProvider -> web_search
        import re
        name = re.sub('Provider$', '', class_name)  # Remove 'Provider' suffix
        name = re.sub('([A-Z]+)', r'_\1', name).lower().strip('_')
        return name
    
    def register_provider(self, provider_type: str, provider_class: Type[BaseProvider]) -> None:
        """
        Manually register a provider class.
        
        Args:
            provider_type: Unique type identifier for the provider
            provider_class: The provider class to register
        """
        if not self._validate_provider_class(provider_class, provider_class.__name__):
            raise ValueError(f"Invalid provider class: {provider_class.__name__}")
        
        self._providers[provider_type] = provider_class
        logger.info(f"📦 Manually registered provider: {provider_type}")
    
    def get_provider_class(self, provider_type: str) -> Optional[Type[BaseProvider]]:
        """
        Get a provider class by type.
        
        Args:
            provider_type: The provider type to look up
            
        Returns:
            Provider class or None if not found
        """
        return self._providers.get(provider_type)
    
    def list_providers(self) -> List[str]:
        """
        List all registered provider types.
        
        Returns:
            List of provider type strings
        """
        return list(self._providers.keys())
    
    def create_provider(
        self, 
        provider_type: str, 
        provider_id: str, 
        server_url: str,
        config: Optional[Dict[str, Any]] = None
    ) -> Optional[BaseProvider]:
        """
        Create an instance of a provider.
        
        Args:
            provider_type: Type of provider to create
            provider_id: Unique ID for this provider instance
            server_url: URL of the central server
            config: Optional configuration parameters
            
        Returns:
            Provider instance or None if type not found
        """
        provider_class = self.get_provider_class(provider_type)
        if not provider_class:
            logger.error(f"Unknown provider type: {provider_type}")
            return None
        
        try:
            # Get the constructor signature
            sig = inspect.signature(provider_class.__init__)
            params = {}
            
            # Add standard parameters if they exist
            if 'provider_id' in sig.parameters:
                params['provider_id'] = provider_id
            if 'server_url' in sig.parameters:
                params['server_url'] = server_url
            
            # Add any additional config parameters
            if config:
                for key, value in config.items():
                    if key in sig.parameters:
                        params[key] = value
            
            # Create the provider instance
            provider = provider_class(**params)
            logger.info(f"✅ Created provider: {provider_type} ({provider_id})")
            return provider
            
        except Exception as e:
            logger.error(f"Failed to create provider {provider_type}: {e}")
            return None
    
    def get_provider_info(self, provider_type: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a provider type.
        
        Args:
            provider_type: The provider type to get info for
            
        Returns:
            Provider information dictionary or None
        """
        provider_class = self.get_provider_class(provider_type)
        if not provider_class:
            return None
        
        # Extract information from the class
        info = {
            'type': provider_type,
            'class_name': provider_class.__name__,
            'module': provider_class.__module__,
            'doc': provider_class.__doc__ or "No description available"
        }
        
        # Try to get supported functions if available
        try:
            # This would need to be determined from the class or instance
            # For now, we'll leave it as unknown
            info['supported_functions'] = getattr(provider_class, 'SUPPORTED_FUNCTIONS', ['unknown'])
        except:
            info['supported_functions'] = ['unknown']
        
        return info


# Global registry instance
_registry = ProviderRegistry()


def get_registry() -> ProviderRegistry:
    """Get the global provider registry instance."""
    return _registry


def discover_providers() -> None:
    """Discover all available providers."""
    _registry.discover_providers()


def register_provider(provider_type: str, provider_class: Type[BaseProvider]) -> None:
    """Register a provider class."""
    _registry.register_provider(provider_type, provider_class)


def create_provider(
    provider_type: str, 
    provider_id: str, 
    server_url: str,
    config: Optional[Dict[str, Any]] = None
) -> Optional[BaseProvider]:
    """Create a provider instance."""
    return _registry.create_provider(provider_type, provider_id, server_url, config)


def list_providers() -> List[str]:
    """List all available provider types."""
    return _registry.list_providers()


def get_provider_info(provider_type: str) -> Optional[Dict[str, Any]]:
    """Get information about a provider type."""
    return _registry.get_provider_info(provider_type)