"""
Provider Configuration System

Manages provider settings, enabling/disabling, and configuration parameters.
"""

import json
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
import os

logger = logging.getLogger(__name__)


class ProviderConfig:
    """
    Configuration management for providers.
    
    Features:
    - Load configuration from JSON files
    - Environment variable overrides
    - Provider enable/disable flags
    - Per-provider custom settings
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._get_default_config_path()
        self.config: Dict[str, Any] = self._load_default_config()
        self._load_config()
    
    def _get_default_config_path(self) -> str:
        """Get the default configuration file path."""
        # Look for config in several locations
        possible_paths = [
            os.path.expanduser("~/.gleitzeit/providers.json"),
            "./gleitzeit_providers.json",
            "./config/providers.json"
        ]
        
        for path in possible_paths:
            if Path(path).exists():
                return path
        
        # Return the first path as default location to create
        return possible_paths[0]
    
    def _load_default_config(self) -> Dict[str, Any]:
        """Load default configuration."""
        return {
            "providers": {
                "ollama": {
                    "enabled": True,
                    "auto_discover": True,
                    "config": {
                        "host": "localhost",
                        "port": 11434,
                        "timeout": 30
                    }
                },
                "web_search": {
                    "enabled": True,
                    "auto_discover": True,
                    "config": {
                        "search_engine": "duckduckgo",
                        "max_results": 5,
                        "timeout": 10
                    }
                },
                "mcp": {
                    "enabled": False,  # Requires manual setup
                    "auto_discover": False,
                    "config": {}
                }
            },
            "global": {
                "auto_discover_providers": True,
                "max_concurrent_tasks_default": 5,
                "heartbeat_interval": 30.0,
                "health_check_interval": 60.0
            }
        }
    
    def _load_config(self) -> None:
        """Load configuration from file if it exists."""
        config_file = Path(self.config_path)
        
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    file_config = json.load(f)
                
                # Deep merge with default config
                self._deep_merge(self.config, file_config)
                logger.info(f"📝 Loaded provider config from {self.config_path}")
                
            except Exception as e:
                logger.warning(f"Failed to load provider config from {self.config_path}: {e}")
        else:
            logger.info(f"No provider config found at {self.config_path}, using defaults")
    
    def _deep_merge(self, base: Dict[str, Any], update: Dict[str, Any]) -> None:
        """Deep merge two dictionaries."""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
    
    def save_config(self) -> None:
        """Save current configuration to file."""
        try:
            config_file = Path(self.config_path)
            config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            
            logger.info(f"💾 Saved provider config to {self.config_path}")
            
        except Exception as e:
            logger.error(f"Failed to save provider config: {e}")
    
    def is_provider_enabled(self, provider_type: str) -> bool:
        """Check if a provider is enabled."""
        # Check environment variable override first
        env_var = f"GLEITZEIT_{provider_type.upper()}_ENABLED"
        env_value = os.getenv(env_var)
        if env_value is not None:
            return env_value.lower() in ['true', '1', 'yes', 'on']
        
        # Check configuration file
        provider_config = self.config.get("providers", {}).get(provider_type, {})
        return provider_config.get("enabled", False)
    
    def should_auto_discover(self, provider_type: str) -> bool:
        """Check if a provider should be auto-discovered."""
        provider_config = self.config.get("providers", {}).get(provider_type, {})
        return provider_config.get("auto_discover", True)
    
    def get_provider_config(self, provider_type: str) -> Dict[str, Any]:
        """Get configuration for a specific provider."""
        provider_config = self.config.get("providers", {}).get(provider_type, {})
        return provider_config.get("config", {})
    
    def get_global_config(self, key: str, default: Any = None) -> Any:
        """Get a global configuration value."""
        return self.config.get("global", {}).get(key, default)
    
    def set_provider_enabled(self, provider_type: str, enabled: bool) -> None:
        """Enable or disable a provider."""
        if "providers" not in self.config:
            self.config["providers"] = {}
        if provider_type not in self.config["providers"]:
            self.config["providers"][provider_type] = {}
        
        self.config["providers"][provider_type]["enabled"] = enabled
    
    def set_provider_config(self, provider_type: str, config: Dict[str, Any]) -> None:
        """Set configuration for a provider."""
        if "providers" not in self.config:
            self.config["providers"] = {}
        if provider_type not in self.config["providers"]:
            self.config["providers"][provider_type] = {}
        
        self.config["providers"][provider_type]["config"] = config
    
    def list_enabled_providers(self) -> List[str]:
        """Get list of enabled provider types."""
        enabled = []
        
        for provider_type in self.config.get("providers", {}):
            if self.is_provider_enabled(provider_type):
                enabled.append(provider_type)
        
        return enabled
    
    def get_all_provider_configs(self) -> Dict[str, Dict[str, Any]]:
        """Get configuration for all providers."""
        return self.config.get("providers", {})
    
    def create_default_config_file(self) -> None:
        """Create a default configuration file."""
        if not Path(self.config_path).exists():
            self.save_config()
            print(f"📝 Created default provider configuration at {self.config_path}")
            print("Edit this file to customize provider settings.")


# Global config instance
_config = None


def get_config(config_path: Optional[str] = None) -> ProviderConfig:
    """Get the global provider configuration."""
    global _config
    if _config is None:
        _config = ProviderConfig(config_path)
    return _config


def is_provider_enabled(provider_type: str) -> bool:
    """Check if a provider is enabled."""
    return get_config().is_provider_enabled(provider_type)


def get_provider_config(provider_type: str) -> Dict[str, Any]:
    """Get configuration for a provider."""
    return get_config().get_provider_config(provider_type)