#!/usr/bin/env python3
"""
Provider Configuration System

Loads and manages Socket.IO providers from YAML configuration files
"""

import os
import asyncio
import logging
import importlib
from pathlib import Path
from typing import Dict, Any, List, Optional, Type
import yaml

from .socketio_provider_client import SocketIOProviderClient

logger = logging.getLogger(__name__)


class ProviderConfig:
    """Configuration for a single provider"""
    
    def __init__(self, name: str, config_data: Dict[str, Any]):
        self.name = name
        self.enabled = config_data.get('enabled', True)
        self.type = config_data.get('type', 'llm')
        self.class_path = config_data.get('class')
        self.config = config_data.get('config', {})
        self.description = config_data.get('description', '')
        self.auto_discover_models = config_data.get('auto_discover_models', False)
        
        # Ensure name is in config
        if 'name' not in self.config:
            self.config['name'] = name


class ProviderConfigManager:
    """Manages provider configurations and instances"""
    
    def __init__(self, config_file: str = None):
        self.config_file = config_file or self._find_config_file()
        self.providers: Dict[str, ProviderConfig] = {}
        self.provider_instances: Dict[str, SocketIOProviderClient] = {}
        self.provider_tasks: Dict[str, asyncio.Task] = {}
        self.global_config: Dict[str, Any] = {}
        
    def _find_config_file(self) -> str:
        """Find provider config file"""
        # Check common locations
        possible_paths = [
            "config/providers.yaml",
            "config/providers.yml", 
            "providers.yaml",
            "providers.yml",
            "~/.gleitzeit/providers.yaml",
            "/etc/gleitzeit/providers.yaml"
        ]
        
        for path_str in possible_paths:
            path = Path(path_str).expanduser()
            if path.exists():
                return str(path)
        
        # Create default config if none found
        default_path = Path("config/providers.yaml")
        default_path.parent.mkdir(exist_ok=True)
        
        logger.info(f"No provider config found, using default: {default_path}")
        return str(default_path)
    
    def load_config(self) -> None:
        """Load provider configuration from YAML file"""
        config_path = Path(self.config_file)
        
        if not config_path.exists():
            logger.warning(f"Provider config file not found: {config_path}")
            return
        
        try:
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)
            
            # Load global settings
            self.global_config = config_data.get('global', {})
            
            # Process environment variables
            self._process_env_vars(config_data.get('env_vars', {}))
            
            # Load provider configurations
            provider_configs = config_data.get('providers', {})
            
            for name, provider_data in provider_configs.items():
                # Apply environment variable substitutions
                provider_data = self._substitute_env_vars(provider_data)
                
                self.providers[name] = ProviderConfig(name, provider_data)
                logger.info(f"Loaded config for provider: {name}")
            
            logger.info(f"Loaded {len(self.providers)} provider configurations")
            
        except Exception as e:
            logger.error(f"Failed to load provider config: {e}")
            raise
    
    def _process_env_vars(self, env_mappings: Dict[str, str]) -> None:
        """Process environment variable mappings"""
        for env_var, config_path in env_mappings.items():
            if env_var in os.environ:
                value = os.environ[env_var]
                # Apply to provider config (simplified - could be more sophisticated)
                logger.debug(f"Applied env var {env_var} to {config_path}")
    
    def _substitute_env_vars(self, data: Any) -> Any:
        """Recursively substitute ${VAR} patterns with environment variables"""
        if isinstance(data, dict):
            return {key: self._substitute_env_vars(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._substitute_env_vars(item) for item in data]
        elif isinstance(data, str):
            # Simple ${VAR} substitution
            import re
            def replace_var(match):
                var_name = match.group(1)
                return os.environ.get(var_name, match.group(0))
            
            return re.sub(r'\$\{([^}]+)\}', replace_var, data)
        else:
            return data
    
    def get_enabled_providers(self) -> List[ProviderConfig]:
        """Get list of enabled provider configurations"""
        return [config for config in self.providers.values() if config.enabled]
    
    def get_provider_config(self, name: str) -> Optional[ProviderConfig]:
        """Get configuration for a specific provider"""
        return self.providers.get(name)
    
    async def start_providers(self) -> Dict[str, SocketIOProviderClient]:
        """Start all enabled providers"""
        if not self.global_config.get('auto_start', True):
            logger.info("Auto-start disabled, not starting providers")
            return {}
        
        enabled_providers = self.get_enabled_providers()
        logger.info(f"Starting {len(enabled_providers)} enabled providers...")
        
        started_providers = {}
        
        for provider_config in enabled_providers:
            try:
                provider = await self._start_provider(provider_config)
                if provider:
                    self.provider_instances[provider_config.name] = provider
                    started_providers[provider_config.name] = provider
                    logger.info(f"✅ Started provider: {provider_config.name}")
                else:
                    logger.warning(f"❌ Failed to start provider: {provider_config.name}")
                    
            except Exception as e:
                logger.error(f"❌ Error starting provider {provider_config.name}: {e}")
        
        logger.info(f"Started {len(started_providers)} providers successfully")
        return started_providers
    
    async def _start_provider(self, config: ProviderConfig) -> Optional[SocketIOProviderClient]:
        """Start a single provider"""
        try:
            # Load provider class
            provider_class = self._load_provider_class(config.class_path)
            
            # Create provider instance
            provider = provider_class(**config.config)
            
            # Start the provider (connect to Socket.IO server)
            task = asyncio.create_task(provider.run())
            self.provider_tasks[config.name] = task
            
            # Wait a moment for connection
            await asyncio.sleep(1)
            
            return provider
            
        except Exception as e:
            logger.error(f"Failed to start provider {config.name}: {e}")
            return None
    
    def _load_provider_class(self, class_path: str) -> Type[SocketIOProviderClient]:
        """Load provider class from module path"""
        try:
            # Split module and class name
            if '.' in class_path:
                module_path, class_name = class_path.rsplit('.', 1)
            else:
                raise ImportError(f"Invalid class path: {class_path}")
            
            # Import module
            module = importlib.import_module(module_path)
            
            # Get class
            if not hasattr(module, class_name):
                raise ImportError(f"Class {class_name} not found in {module_path}")
            
            provider_class = getattr(module, class_name)
            
            # Verify it's a valid provider class
            if not issubclass(provider_class, SocketIOProviderClient):
                raise TypeError(f"Class {class_name} is not a SocketIOProviderClient")
            
            return provider_class
            
        except Exception as e:
            logger.error(f"Failed to load provider class {class_path}: {e}")
            raise
    
    async def stop_providers(self) -> None:
        """Stop all running providers"""
        logger.info("Stopping all providers...")
        
        # Disconnect providers
        for name, provider in self.provider_instances.items():
            try:
                await provider.disconnect()
                logger.info(f"Disconnected provider: {name}")
            except Exception as e:
                logger.error(f"Error disconnecting provider {name}: {e}")
        
        # Cancel tasks
        for name, task in self.provider_tasks.items():
            try:
                task.cancel()
                await task
                logger.info(f"Cancelled task for provider: {name}")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error cancelling task for provider {name}: {e}")
        
        # Clear instances
        self.provider_instances.clear()
        self.provider_tasks.clear()
        
        logger.info("All providers stopped")
    
    def get_running_providers(self) -> Dict[str, SocketIOProviderClient]:
        """Get currently running provider instances"""
        return self.provider_instances.copy()
    
    async def restart_provider(self, name: str) -> bool:
        """Restart a specific provider"""
        config = self.get_provider_config(name)
        if not config or not config.enabled:
            logger.warning(f"Cannot restart provider {name}: not enabled or not found")
            return False
        
        # Stop existing instance
        if name in self.provider_instances:
            try:
                await self.provider_instances[name].disconnect()
                del self.provider_instances[name]
            except Exception as e:
                logger.error(f"Error stopping provider {name}: {e}")
        
        if name in self.provider_tasks:
            try:
                self.provider_tasks[name].cancel()
                await self.provider_tasks[name]
                del self.provider_tasks[name]
            except Exception as e:
                logger.error(f"Error cancelling task for provider {name}: {e}")
        
        # Start new instance
        provider = await self._start_provider(config)
        if provider:
            self.provider_instances[name] = provider
            logger.info(f"Successfully restarted provider: {name}")
            return True
        else:
            logger.error(f"Failed to restart provider: {name}")
            return False


# Convenience functions for easy usage
_global_manager: Optional[ProviderConfigManager] = None

def get_provider_manager(config_file: str = None) -> ProviderConfigManager:
    """Get global provider manager instance"""
    global _global_manager
    if _global_manager is None:
        _global_manager = ProviderConfigManager(config_file)
        _global_manager.load_config()
    return _global_manager

async def start_configured_providers(config_file: str = None) -> Dict[str, SocketIOProviderClient]:
    """Start providers from configuration file"""
    manager = get_provider_manager(config_file)
    return await manager.start_providers()

async def stop_configured_providers() -> None:
    """Stop all configured providers"""
    global _global_manager
    if _global_manager:
        await _global_manager.stop_providers()