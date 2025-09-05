"""
Configuration Manager for centralized configuration management.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, Set, Callable, List
from dataclasses import dataclass, field
from datetime import datetime

import yaml

from ..persistence.unified_persistence import UnifiedPersistenceAdapter
from ..core.events import GleitzeitEvent as Event, EventType
from ..events.stateless_bus import StatelessEventBus
from ..core.errors import (
    ConfigValidationError, SystemManagerError, PersistenceError,
    ConfigurationError
)
from .models import ServiceType


logger = logging.getLogger(__name__)


@dataclass
class ConfigValue:
    """Configuration value with metadata."""
    key: str
    value: Any
    version: int = 1
    updated_at: datetime = field(default_factory=datetime.utcnow)
    updated_by: str = "system"
    description: Optional[str] = None
    validation_schema: Optional[Dict] = None
    

class ConfigurationManager:
    """
    Centralized configuration management for all system components.
    
    Features:
    - Hierarchical configuration
    - Dynamic hot-reload
    - Configuration validation
    - Version tracking
    - Environment-specific overrides
    - Secret management integration
    """
    
    def __init__(
        self,
        persistence: UnifiedPersistenceAdapter,
        event_bus: Optional[StatelessEventBus] = None,
        config_dir: Optional[Path] = None,
        environment: str = "development",
        watch_interval: int = 30,
        enable_hot_reload: bool = True,
    ):
        """
        Initialize the ConfigurationManager.
        
        Args:
            persistence: Persistence adapter
            event_bus: Event bus for config change events
            config_dir: Directory for config files
            environment: Current environment (dev, staging, prod)
            watch_interval: Seconds between config file checks
            enable_hot_reload: Enable automatic config reload
        """
        self.persistence = persistence
        self.event_bus = event_bus
        self.config_dir = config_dir or Path.home() / ".gleitzeit" / "config"
        self.environment = environment
        self.watch_interval = watch_interval
        self.enable_hot_reload = enable_hot_reload
        
        # Configuration storage
        self._configs: Dict[str, ConfigValue] = {}
        self._component_configs: Dict[str, Dict[str, Any]] = {}
        
        # Watchers for config changes
        self._watchers: Dict[str, Set[Callable]] = {}
        
        # Validation schemas
        self._schemas: Dict[str, Dict] = {}
        
        # Background tasks
        self._watch_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Config file tracking
        self._file_mtimes: Dict[Path, float] = {}
        
    async def initialize(self):
        """Initialize the configuration manager."""
        logger.info(f"Initializing ConfigurationManager for environment: {self.environment}")
        
        # Create config directory if it doesn't exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Load configuration files
        await self._load_config_files()
        
        # Load configs from persistence
        await self._load_configs_from_persistence()
        
        # Register default schemas
        self._register_default_schemas()
        
        # Start file watcher if enabled
        if self.enable_hot_reload:
            self._running = True
            self._watch_task = asyncio.create_task(self._watch_config_files())
            
        # Register event handlers
        if self.event_bus:
            await self._register_event_handlers()
            
        logger.info("ConfigurationManager initialized")
        
    async def shutdown(self):
        """Shutdown the configuration manager."""
        logger.info("Shutting down ConfigurationManager")
        
        self._running = False
        
        # Cancel watch task
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
                
        logger.info("ConfigurationManager shutdown complete")
        
    async def get_config(
        self,
        key: str,
        default: Any = None,
        component: Optional[str] = None
    ) -> Any:
        """
        Get configuration value.
        
        Args:
            key: Configuration key (supports dot notation)
            default: Default value if key not found
            component: Optional component name for scoped config
            
        Returns:
            Configuration value
        """
        # Check component-specific config first
        if component and component in self._component_configs:
            value = self._get_nested_value(self._component_configs[component], key)
            if value is not None:
                return value
                
        # Check global config
        if key in self._configs:
            return self._configs[key].value
            
        # Check nested keys
        value = self._get_nested_value(self._configs, key)
        if value is not None:
            return value
            
        return default
        
    async def set_config(
        self,
        key: str,
        value: Any,
        component: Optional[str] = None,
        persist: bool = True,
        notify: bool = True,
        validation_schema: Optional[Dict] = None
    ) -> bool:
        """
        Set configuration value.
        
        Args:
            key: Configuration key
            value: Configuration value
            component: Optional component name for scoped config
            persist: Whether to persist the change
            notify: Whether to notify watchers
            validation_schema: Optional validation schema
            
        Returns:
            True if successful
        """
        try:
            # Validate if schema exists
            if validation_schema or key in self._schemas:
                schema = validation_schema or self._schemas[key]
                if not self._validate_config(value, schema):
                    logger.error(f"Configuration validation failed for {key}")
                    return False
                    
            # Create config value
            config_value = ConfigValue(
                key=key,
                value=value,
                version=self._get_next_version(key),
                validation_schema=validation_schema
            )
            
            # Store configuration
            if component:
                if component not in self._component_configs:
                    self._component_configs[component] = {}
                self._set_nested_value(self._component_configs[component], key, value)
            else:
                self._configs[key] = config_value
                
            # Persist if requested
            if persist:
                await self._persist_config(key, config_value, component)
                
            # Notify watchers
            if notify:
                await self._notify_watchers(key, value, component)
                
            # Emit event
            if self.event_bus:
                await self.event_bus.emit(Event(
                    event_type=EventType.CONFIG_CHANGED,
                    data={
                        "key": key,
                        "value": value,
                        "component": component,
                        "version": config_value.version,
                    }
                ))
                
            logger.info(f"Configuration updated: {key} = {value}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set config {key}: {e}")
            return False
            
    async def get_component_config(self, component: str) -> Dict[str, Any]:
        """
        Get all configuration for a component.
        
        Args:
            component: Component name
            
        Returns:
            Component configuration dictionary
        """
        # Merge global and component-specific configs
        config = {}
        
        # Add relevant global configs
        for key, config_value in self._configs.items():
            if not key.startswith("_"):  # Skip private configs
                config[key] = config_value.value
                
        # Override with component-specific configs
        if component in self._component_configs:
            config.update(self._component_configs[component])
            
        return config
        
    async def reload_config(self, component: Optional[str] = None) -> bool:
        """
        Reload configuration from files and persistence.
        
        Args:
            component: Optional component to reload config for
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"Reloading configuration{f' for {component}' if component else ''}")
            
            # Reload from files
            await self._load_config_files(component)
            
            # Reload from persistence
            await self._load_configs_from_persistence(component)
            
            # Notify watchers
            if component:
                for key, value in self._component_configs.get(component, {}).items():
                    await self._notify_watchers(key, value, component)
            else:
                for key, config_value in self._configs.items():
                    await self._notify_watchers(key, config_value.value, None)
                    
            logger.info("Configuration reloaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reload configuration: {e}")
            return False
            
    async def watch_config(
        self,
        key: str,
        callback: Callable,
        component: Optional[str] = None
    ):
        """
        Watch for configuration changes.
        
        Args:
            key: Configuration key to watch
            callback: Callback function(key, old_value, new_value)
            component: Optional component filter
        """
        watch_key = f"{component}:{key}" if component else key
        
        if watch_key not in self._watchers:
            self._watchers[watch_key] = set()
            
        self._watchers[watch_key].add(callback)
        logger.debug(f"Added watcher for config: {watch_key}")
        
    async def unwatch_config(
        self,
        key: str,
        callback: Callable,
        component: Optional[str] = None
    ):
        """
        Stop watching configuration changes.
        
        Args:
            key: Configuration key
            callback: Callback to remove
            component: Optional component filter
        """
        watch_key = f"{component}:{key}" if component else key
        
        if watch_key in self._watchers:
            self._watchers[watch_key].discard(callback)
            if not self._watchers[watch_key]:
                del self._watchers[watch_key]
                
    async def export_config(
        self,
        component: Optional[str] = None,
        format: str = "yaml"
    ) -> str:
        """
        Export configuration to string.
        
        Args:
            component: Optional component to export
            format: Export format (yaml, json)
            
        Returns:
            Configuration as string
        """
        if component:
            config = await self.get_component_config(component)
        else:
            config = {k: v.value for k, v in self._configs.items()}
            
        if format == "json":
            return json.dumps(config, indent=2, default=str)
        else:
            return yaml.dump(config, default_flow_style=False)
            
    async def import_config(
        self,
        config_str: str,
        component: Optional[str] = None,
        format: str = "yaml"
    ) -> bool:
        """
        Import configuration from string.
        
        Args:
            config_str: Configuration string
            component: Optional component to import for
            format: Import format (yaml, json)
            
        Returns:
            True if successful
        """
        try:
            if format == "json":
                config = json.loads(config_str)
            else:
                config = yaml.safe_load(config_str)
                
            for key, value in config.items():
                await self.set_config(key, value, component)
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to import configuration: {e}")
            return False
            
    # Private methods
    
    def _register_default_schemas(self):
        """Register default validation schemas."""
        
        # Provider configuration schema
        self._schemas["provider"] = {
            "type": "object",
            "properties": {
                "max_concurrent": {"type": "integer", "minimum": 1},
                "timeout": {"type": "number", "minimum": 0},
                "retry_attempts": {"type": "integer", "minimum": 0},
            }
        }
        
        # Hub configuration schema
        self._schemas["hub"] = {
            "type": "object",
            "properties": {
                "max_instances": {"type": "integer", "minimum": 1},
                "auto_discover": {"type": "boolean"},
                "health_check_interval": {"type": "integer", "minimum": 1},
            }
        }
        
    def _validate_config(self, value: Any, schema: Dict) -> bool:
        """Validate configuration against schema."""
        # Simple validation - in production would use jsonschema
        try:
            if "type" in schema:
                expected_type = schema["type"]
                if expected_type == "integer" and not isinstance(value, int):
                    return False
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    return False
                elif expected_type == "boolean" and not isinstance(value, bool):
                    return False
                elif expected_type == "string" and not isinstance(value, str):
                    return False
                elif expected_type == "object" and not isinstance(value, dict):
                    return False
                    
            if "minimum" in schema and isinstance(value, (int, float)):
                if value < schema["minimum"]:
                    return False
                    
            if "maximum" in schema and isinstance(value, (int, float)):
                if value > schema["maximum"]:
                    return False
                    
            return True
            
        except Exception as e:
            logger.error(f"Validation error: {e}")
            return False
            
    def _get_nested_value(self, config: Dict, key: str) -> Any:
        """Get value from nested dictionary using dot notation."""
        keys = key.split(".")
        value = config
        
        for k in keys:
            if isinstance(value, dict):
                if k in value:
                    value = value[k]
                elif k in value and isinstance(value[k], ConfigValue):
                    value = value[k].value
                else:
                    return None
            else:
                return None
                
        return value
        
    def _set_nested_value(self, config: Dict, key: str, value: Any):
        """Set value in nested dictionary using dot notation."""
        keys = key.split(".")
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
            
        config[keys[-1]] = value
        
    def _get_next_version(self, key: str) -> int:
        """Get next version number for a config key."""
        if key in self._configs:
            return self._configs[key].version + 1
        return 1
        
    async def _load_config_files(self, component: Optional[str] = None):
        """Load configuration from files."""
        try:
            # Load base config
            base_config_file = self.config_dir / "config.yaml"
            if base_config_file.exists():
                with open(base_config_file) as f:
                    base_config = yaml.safe_load(f) or {}
                    
                for key, value in base_config.items():
                    await self.set_config(key, value, None, persist=False, notify=False)
                    
                self._file_mtimes[base_config_file] = base_config_file.stat().st_mtime
                
            # Load environment-specific config
            env_config_file = self.config_dir / f"config.{self.environment}.yaml"
            if env_config_file.exists():
                with open(env_config_file) as f:
                    env_config = yaml.safe_load(f) or {}
                    
                for key, value in env_config.items():
                    await self.set_config(key, value, None, persist=False, notify=False)
                    
                self._file_mtimes[env_config_file] = env_config_file.stat().st_mtime
                
            # Load component-specific configs
            if component:
                component_file = self.config_dir / f"{component}.yaml"
                if component_file.exists():
                    with open(component_file) as f:
                        component_config = yaml.safe_load(f) or {}
                        
                    for key, value in component_config.items():
                        await self.set_config(key, value, component, persist=False, notify=False)
                        
                    self._file_mtimes[component_file] = component_file.stat().st_mtime
                    
        except Exception as e:
            logger.error(f"Failed to load config files: {e}")
            
    async def _load_configs_from_persistence(self, component: Optional[str] = None):
        """Load configuration from persistence."""
        try:
            pattern = f"config:{component}:*" if component else "config:*"
            keys = await self.persistence.keys(pattern)
            
            for key in keys:
                data = await self.persistence.get(key)
                if data:
                    config_value = ConfigValue(**data)
                    
                    # Parse component from key
                    parts = key.split(":", 2)
                    if len(parts) == 3:
                        _, comp, config_key = parts
                        if comp and comp != "global":
                            if comp not in self._component_configs:
                                self._component_configs[comp] = {}
                            self._component_configs[comp][config_key] = config_value.value
                        else:
                            self._configs[config_key] = config_value
                    elif len(parts) == 2:
                        _, config_key = parts
                        self._configs[config_key] = config_value
                        
            logger.info(f"Loaded {len(keys)} configs from persistence")
            
        except Exception as e:
            logger.error(f"Failed to load configs from persistence: {e}")
            
    async def _persist_config(
        self,
        key: str,
        config_value: ConfigValue,
        component: Optional[str] = None
    ):
        """Persist configuration to storage."""
        try:
            persist_key = f"config:{component}:{key}" if component else f"config:{key}"
            await self.persistence.set(persist_key, config_value.__dict__)
        except Exception as e:
            logger.error(f"Failed to persist config {key}: {e}")
            
    async def _watch_config_files(self):
        """Watch configuration files for changes."""
        while self._running:
            try:
                await asyncio.sleep(self.watch_interval)
                
                # Check for file changes
                for file_path, old_mtime in list(self._file_mtimes.items()):
                    if file_path.exists():
                        new_mtime = file_path.stat().st_mtime
                        if new_mtime > old_mtime:
                            logger.info(f"Config file changed: {file_path}")
                            
                            # Determine component from filename
                            component = None
                            if file_path.stem not in ["config", f"config.{self.environment}"]:
                                component = file_path.stem
                                
                            # Reload config
                            await self.reload_config(component)
                            self._file_mtimes[file_path] = new_mtime
                            
            except Exception as e:
                logger.error(f"Error in config file watcher: {e}")
                
    async def _notify_watchers(
        self,
        key: str,
        new_value: Any,
        component: Optional[str] = None
    ):
        """Notify configuration watchers."""
        # Get old value
        old_value = None
        if component and component in self._component_configs:
            old_value = self._get_nested_value(self._component_configs[component], key)
        elif key in self._configs:
            old_value = self._configs[key].value
            
        # Notify exact key watchers
        watch_key = f"{component}:{key}" if component else key
        if watch_key in self._watchers:
            for callback in self._watchers[watch_key]:
                try:
                    await callback(key, old_value, new_value)
                except Exception as e:
                    logger.error(f"Error in config watcher callback: {e}")
                    
        # Notify wildcard watchers
        wildcard_key = f"{component}:*" if component else "*"
        if wildcard_key in self._watchers:
            for callback in self._watchers[wildcard_key]:
                try:
                    await callback(key, old_value, new_value)
                except Exception as e:
                    logger.error(f"Error in wildcard config watcher: {e}")
                    
    async def _register_event_handlers(self):
        """Register event handlers for configuration events."""
        # Could handle service registration events to auto-configure
        pass