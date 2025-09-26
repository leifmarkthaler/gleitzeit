"""
Configuration loader for Gleitzeit instances

Handles loading configuration from YAML files with environment variable interpolation.
"""

import os
import re
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Union
import logging

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads and processes configuration files with environment variable support"""

    ENV_VAR_PATTERN = re.compile(r'\$\{([^}:]+)(?::([^}]*))?\}')

    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        """
        Initialize configuration loader.

        Args:
            config_path: Path to configuration file. If not provided,
                        looks for config/instance_config.yaml
        """
        if config_path is None:
            # Try to find config file in standard locations
            config_path = self._find_config_file()

        self.config_path = Path(config_path) if config_path else None
        self.raw_config: Dict[str, Any] = {}
        self.config: Dict[str, Any] = {}

    def _find_config_file(self) -> Optional[Path]:
        """Find configuration file in standard locations"""
        # Check environment variable first
        env_config = os.getenv("GLEITZEIT_CONFIG_PATH")
        if env_config and os.path.exists(env_config):
            return Path(env_config)

        # Standard locations to check
        search_paths = [
            Path.cwd() / "config" / "instance_config.yaml",
            Path.cwd() / "instance_config.yaml",
            Path.home() / ".gleitzeit" / "config.yaml",
            Path("/etc/gleitzeit/config.yaml"),
        ]

        # Also check relative to the module
        module_dir = Path(__file__).parent.parent.parent
        search_paths.append(module_dir / "config" / "instance_config.yaml")

        for path in search_paths:
            if path.exists():
                logger.info(f"Found configuration file at: {path}")
                return path

        logger.warning("No configuration file found, using defaults")
        return None

    def load(self) -> Dict[str, Any]:
        """
        Load and process the configuration file.

        Returns:
            Processed configuration dictionary
        """
        if not self.config_path or not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}, using defaults")
            return self._get_default_config()

        try:
            with open(self.config_path, 'r') as f:
                self.raw_config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load config file: {e}")
            return self._get_default_config()

        # Process the configuration to interpolate environment variables
        self.config = self._process_config(self.raw_config)
        return self.config

    def _process_config(self, config: Any) -> Any:
        """
        Recursively process configuration to interpolate environment variables.

        Args:
            config: Configuration value to process

        Returns:
            Processed configuration
        """
        if isinstance(config, dict):
            return {k: self._process_config(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._process_config(item) for item in config]
        elif isinstance(config, str):
            return self._interpolate_env_vars(config)
        else:
            return config

    def _interpolate_env_vars(self, value: str) -> Any:
        """
        Interpolate environment variables in a string.

        Supports ${VAR_NAME} and ${VAR_NAME:-default_value} syntax.

        Args:
            value: String value to process

        Returns:
            Processed value (may be converted to appropriate type)
        """
        def replace_var(match):
            var_name = match.group(1)
            default_value = match.group(2) if match.group(2) is not None else ""

            env_value = os.getenv(var_name)
            if env_value is not None:
                return env_value
            else:
                return default_value

        # Replace all environment variable references
        result = self.ENV_VAR_PATTERN.sub(replace_var, value)

        # Try to convert to appropriate type
        return self._convert_type(result)

    def _convert_type(self, value: str) -> Any:
        """
        Convert string value to appropriate type.

        Args:
            value: String value to convert

        Returns:
            Converted value
        """
        if not isinstance(value, str):
            return value

        # Empty string or None-like values
        if value.lower() in ('', 'none', 'null'):
            return None

        # Boolean values
        if value.lower() in ('true', 'yes', 'on', '1'):
            return True
        if value.lower() in ('false', 'no', 'off', '0'):
            return False

        # Numeric values
        try:
            if '.' in value:
                return float(value)
            else:
                return int(value)
        except ValueError:
            pass

        # Return as string if no conversion applies
        return value

    def _get_default_config(self) -> Dict[str, Any]:
        """
        Get default configuration when no config file is found.

        Returns:
            Default configuration dictionary
        """
        return {
            "instance": {
                "name": "default",
                "role": "standalone",
                "port_offset": 0,
                "features": {
                    "multi_instance": False,
                    "auto_discovery": True,
                    "metrics": True,
                    "health_checks": True
                }
            },
            "networking": {
                "bind_address": "0.0.0.0",
                "advertise_address": "auto",
                "services": {
                    "api": {
                        "enabled": True,
                        "port": 8000,
                        "workers": 4
                    },
                    "ui": {
                        "enabled": True,
                        "port": 8004
                    },
                    "metrics": {
                        "enabled": True,
                        "port": 9090
                    }
                }
            },
            "redis": {
                "url": "redis://localhost:6379",
                "db": 0,
                "namespace": "gleitzeit:default",
                "pool": {
                    "max_connections": 50,
                    "min_idle": 5,
                    "max_idle": 10
                },
                "retry": {
                    "max_attempts": 3,
                    "backoff_ms": 100
                }
            },
            "clustering": {
                "enabled": False,
                "discovery": "redis",
                "heartbeat": {
                    "interval_seconds": 5,
                    "ttl_seconds": 15
                },
                "peers": []
            },
            "metadata": {
                "environment": "development",
                "region": "default",
                "zone": "default",
                "tags": {},
                "labels": []
            },
            "performance": {
                "process": {
                    "restart_policy": "on-failure",
                    "max_restart_attempts": 3,
                    "restart_backoff_seconds": 5,
                    "health_check_interval": 30
                },
                "limits": {
                    "max_workflows": 1000,
                    "max_tasks_per_workflow": 100,
                    "max_concurrent_tasks": 50
                }
            },
            "logging": {
                "level": "INFO",
                "format": "text",
                "outputs": [
                    {"type": "console", "enabled": True}
                ]
            },
            "monitoring": {
                "prometheus": {
                    "enabled": True,
                    "path": "/metrics"
                },
                "health": {
                    "enabled": True,
                    "path": "/health"
                },
                "readiness": {
                    "enabled": True,
                    "path": "/ready"
                }
            },
            "security": {
                "auth_enabled": False,
                "tls": {
                    "enabled": False,
                    "cert_file": "",
                    "key_file": "",
                    "ca_file": ""
                },
                "api_key": ""
            }
        }

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-separated path.

        Args:
            key_path: Dot-separated path to configuration key (e.g., "redis.url")
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        keys = key_path.split('.')
        value = self.config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def merge_cli_args(self, **kwargs) -> None:
        """
        Merge command-line arguments into configuration.

        CLI arguments take precedence over config file values.

        Args:
            **kwargs: Key-value pairs to merge
        """
        for key, value in kwargs.items():
            if value is not None:
                # Convert underscore to dot notation
                key_path = key.replace('_', '.')
                self._set_nested(self.config, key_path, value)

    def _set_nested(self, config: Dict, key_path: str, value: Any) -> None:
        """
        Set a nested configuration value.

        Args:
            config: Configuration dictionary
            key_path: Dot-separated path to key
            value: Value to set
        """
        keys = key_path.split('.')
        current = config

        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value

    def validate(self) -> bool:
        """
        Validate the loaded configuration.

        Returns:
            True if configuration is valid
        """
        # Basic validation checks
        required_keys = [
            "instance.name",
            "instance.role",
            "redis.url",
            "networking.bind_address"
        ]

        for key_path in required_keys:
            if self.get(key_path) is None:
                logger.error(f"Missing required configuration: {key_path}")
                return False

        # Validate port numbers
        port_offset = self.get("instance.port_offset", 0)
        if not isinstance(port_offset, int) or port_offset < 0:
            logger.error(f"Invalid port_offset: {port_offset}")
            return False

        # Validate role
        valid_roles = ["standalone", "worker", "coordinator", "gateway"]
        role = self.get("instance.role")
        if role not in valid_roles:
            logger.error(f"Invalid instance role: {role}")
            return False

        return True


# Global config instance
_config_loader: Optional[ConfigLoader] = None


def get_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the global configuration.

    Args:
        config_path: Optional path to configuration file

    Returns:
        Configuration dictionary
    """
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader(config_path)
        _config_loader.load()

    return _config_loader.config


def reload_config() -> Dict[str, Any]:
    """
    Reload the configuration from file.

    Returns:
        Updated configuration dictionary
    """
    global _config_loader
    if _config_loader:
        return _config_loader.load()
    else:
        return get_config()