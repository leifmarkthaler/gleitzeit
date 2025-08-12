"""
Config-Based Extension Loader

Loads and instantiates extensions defined via YAML configuration files.
"""

import asyncio
import importlib
import os
from pathlib import Path
from typing import Dict, Any, Optional

from .registry import ExtensionInfo, ConfigExtensionMeta
from .exceptions import ExtensionLoadError, ExtensionConfigError


class ConfigExtensionLoader:
    """Loads config-based extensions"""
    
    def __init__(self):
        self._loaded_classes = {}
    
    def load_extension(self, info: ExtensionInfo, runtime_config: Dict[str, Any]) -> Any:
        """
        Load a config-based extension
        
        Args:
            info: Extension info from registry
            runtime_config: Runtime configuration provided by user
            
        Returns:
            Loaded extension instance
        """
        if info.type != "config":
            raise ExtensionLoadError(info.name, "Not a config-based extension")
        
        meta = info.meta
        if not isinstance(meta, ConfigExtensionMeta):
            raise ExtensionLoadError(info.name, "Invalid config extension metadata")
        
        # Merge configuration
        merged_config = self._merge_configuration(meta, runtime_config)
        
        # Validate configuration
        self._validate_configuration(info.name, meta.config_schema, merged_config)
        
        # Load extension class
        extension_class = self._load_extension_class(info.name, meta)
        
        # Instantiate extension
        try:
            instance = extension_class(merged_config)
            return instance
        except Exception as e:
            raise ExtensionLoadError(info.name, f"Failed to instantiate: {e}")
    
    def _merge_configuration(self, meta: ConfigExtensionMeta, runtime_config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge runtime config with defaults and environment variables"""
        merged = {}
        
        # Start with defaults from schema
        for field_name, field_info in meta.config_schema.items():
            if 'default' in field_info:
                merged[field_name] = field_info['default']
        
        # Override with environment variables
        for field_name, field_info in meta.config_schema.items():
            env_var = field_info.get('env_var')
            if env_var and env_var in os.environ:
                value = os.environ[env_var]
                # Convert based on field type
                field_type = field_info.get('type', 'string')
                if field_type == 'integer':
                    try:
                        value = int(value)
                    except ValueError:
                        raise ExtensionConfigError(meta.name, f"Invalid integer value for {field_name}: {value}")
                elif field_type == 'boolean':
                    value = value.lower() in ('true', '1', 'yes', 'on')
                elif field_type == 'list':
                    value = [item.strip() for item in value.split(',')]
                
                merged[field_name] = value
        
        # Override with runtime config
        merged.update(runtime_config)
        
        return merged
    
    def _validate_configuration(self, extension_name: str, schema: Dict[str, Any], config: Dict[str, Any]) -> None:
        """Validate configuration against schema"""
        errors = []
        
        for field_name, field_info in schema.items():
            # Check required fields
            if field_info.get('required', False) and field_name not in config:
                errors.append(f"Required field '{field_name}' missing")
                continue
            
            if field_name not in config:
                continue
            
            value = config[field_name]
            field_type = field_info.get('type', 'string')
            
            # Type validation
            if field_type == 'string' and not isinstance(value, str):
                errors.append(f"Field '{field_name}' must be a string")
            elif field_type == 'integer' and not isinstance(value, int):
                errors.append(f"Field '{field_name}' must be an integer")
            elif field_type == 'boolean' and not isinstance(value, bool):
                errors.append(f"Field '{field_name}' must be a boolean")
            elif field_type == 'list' and not isinstance(value, list):
                errors.append(f"Field '{field_name}' must be a list")
            
            # Range validation for integers
            if field_type == 'integer' and isinstance(value, int):
                if 'min' in field_info and value < field_info['min']:
                    errors.append(f"Field '{field_name}' must be >= {field_info['min']}")
                if 'max' in field_info and value > field_info['max']:
                    errors.append(f"Field '{field_name}' must be <= {field_info['max']}")
        
        if errors:
            raise ExtensionConfigError(extension_name, '; '.join(errors))
    
    def _load_extension_class(self, extension_name: str, meta: ConfigExtensionMeta) -> type:
        """Load the extension class from service configuration"""
        service_config = meta.service_config
        if not service_config:
            raise ExtensionLoadError(extension_name, "No service configuration found")
        
        class_path = service_config.get('class_path')
        if not class_path:
            # Try to infer from extension structure
            class_path = f"extensions.{extension_name}.service.{extension_name.title()}Service"
        
        try:
            # Parse class path
            if '.' in class_path:
                module_path, class_name = class_path.rsplit('.', 1)
            else:
                raise ExtensionLoadError(extension_name, f"Invalid class path: {class_path}")
            
            # Load module
            try:
                module = importlib.import_module(module_path)
            except ImportError as e:
                # Try relative import from extension directory
                if meta.config_file:
                    ext_dir = Path(meta.config_file).parent
                    service_file = ext_dir / "service.py"
                    if service_file.exists():
                        return self._load_class_from_file(service_file, class_name)
                raise ExtensionLoadError(extension_name, f"Cannot import module {module_path}: {e}")
            
            # Get class
            if not hasattr(module, class_name):
                raise ExtensionLoadError(extension_name, f"Class {class_name} not found in {module_path}")
            
            extension_class = getattr(module, class_name)
            
            # Cache for reuse
            self._loaded_classes[extension_name] = extension_class
            
            return extension_class
            
        except Exception as e:
            raise ExtensionLoadError(extension_name, f"Failed to load extension class: {e}")
    
    def _load_class_from_file(self, service_file: Path, class_name: str) -> type:
        """Load extension class directly from Python file"""
        import importlib.util
        import sys
        
        module_name = f"extension_service_{service_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, service_file)
        if not spec or not spec.loader:
            raise ImportError(f"Cannot load spec from {service_file}")
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        
        if not hasattr(module, class_name):
            raise ImportError(f"Class {class_name} not found in {service_file}")
        
        return getattr(module, class_name)


class ConfigBasedExtension:
    """Base class for config-based extensions"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.name = config.get('name', 'unknown')
        self._service_task: Optional[asyncio.Task] = None
    
    async def setup(self) -> None:
        """Initialize extension - override in subclasses"""
        pass
    
    async def start(self) -> None:
        """Start extension service - override in subclasses"""
        pass
    
    async def stop(self) -> None:
        """Stop extension service - override in subclasses"""
        if self._service_task:
            self._service_task.cancel()
            try:
                await self._service_task
            except asyncio.CancelledError:
                pass
    
    def health_check(self) -> Dict[str, Any]:
        """Check extension health - override in subclasses"""
        return {'healthy': True, 'provider': self.name}
    
    def get_models(self) -> list[str]:
        """Get supported models - override in subclasses"""
        return []
    
    def get_capabilities(self) -> list[str]:
        """Get supported capabilities - override in subclasses"""
        return []