"""
Extension Registry

Central registry for both decorator-based and config-based extensions.
Maintains metadata and provides lookup capabilities.
"""

import os
import yaml
import importlib
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import ExtensionNotFound, ExtensionConfigError, ExtensionValidationError
from .decorators import ExtensionMeta, is_extension, get_extension_meta


@dataclass
class ConfigExtensionMeta:
    """Metadata for config-based extensions"""
    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    models: List[Dict[str, Any]] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)
    service_config: Dict[str, Any] = field(default_factory=dict)
    config_file: Optional[str] = None


@dataclass
class ExtensionInfo:
    """Unified extension information"""
    name: str
    type: str  # "decorator" or "config"
    meta: Union[ExtensionMeta, ConfigExtensionMeta]
    extension_class: Optional[type] = None
    config_file: Optional[str] = None
    loaded: bool = False
    instance: Optional[Any] = None


class ExtensionRegistry:
    """Central registry for all extension types"""
    
    def __init__(self):
        self._extensions: Dict[str, ExtensionInfo] = {}
        self._loaded_instances: Dict[str, Any] = {}
    
    def register_decorator(self, extension_cls: type) -> None:
        """Register a decorator-based extension class"""
        if not is_extension(extension_cls):
            raise ExtensionValidationError(
                extension_cls.__name__,
                ["Class is not marked with @extension decorator"]
            )
        
        meta = get_extension_meta(extension_cls)
        if not meta:
            raise ExtensionValidationError(
                extension_cls.__name__,
                ["Extension metadata not found"]
            )
        
        info = ExtensionInfo(
            name=meta.name,
            type="decorator",
            meta=meta,
            extension_class=extension_cls
        )
        
        self._extensions[meta.name] = info
        print(f"📋 Registered decorator extension: {meta.name}")
    
    def register_config(self, config_file: str) -> None:
        """Register a config-based extension"""
        config_path = Path(config_file)
        if not config_path.exists():
            raise ExtensionConfigError("config", f"Config file not found: {config_file}")
        
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ExtensionConfigError("config", f"Invalid YAML: {e}")
        
        # Validate required fields
        required_fields = ['name', 'description']
        for field in required_fields:
            if field not in config:
                raise ExtensionConfigError("config", f"Missing required field: {field}")
        
        # Extract models
        models = []
        for model_config in config.get('models', []):
            if isinstance(model_config, dict):
                models.append(model_config)
            else:
                models.append({"name": model_config})
        
        # Extract dependencies 
        dependencies = []
        deps_config = config.get('dependencies', {})
        if isinstance(deps_config, dict):
            packages = deps_config.get('packages', [])
            dependencies.extend(packages)
        elif isinstance(deps_config, list):
            dependencies.extend(deps_config)
        
        # Create metadata
        meta = ConfigExtensionMeta(
            name=config['name'],
            description=config.get('description', ''),
            version=config.get('version', '1.0.0'),
            author=config.get('author', ''),
            models=models,
            capabilities=config.get('capabilities', []),
            dependencies=dependencies,
            config_schema=config.get('config', {}),
            service_config=config.get('service', {}),
            config_file=str(config_path)
        )
        
        info = ExtensionInfo(
            name=meta.name,
            type="config", 
            meta=meta,
            config_file=str(config_path)
        )
        
        self._extensions[meta.name] = info
        print(f"📋 Registered config extension: {meta.name}")
    
    def get_extension(self, name: str) -> ExtensionInfo:
        """Get extension info by name"""
        if name not in self._extensions:
            raise ExtensionNotFound(name)
        return self._extensions[name]
    
    def has_extension(self, name: str) -> bool:
        """Check if extension is registered"""
        return name in self._extensions
    
    def list_extensions(self) -> Dict[str, ExtensionInfo]:
        """Get all registered extensions"""
        return self._extensions.copy()
    
    def list_by_type(self, extension_type: str) -> Dict[str, ExtensionInfo]:
        """Get extensions by type (decorator or config)"""
        return {
            name: info for name, info in self._extensions.items()
            if info.type == extension_type
        }
    
    def list_by_capability(self, capability: str) -> Dict[str, ExtensionInfo]:
        """Get extensions that support a specific capability"""
        matching = {}
        for name, info in self._extensions.items():
            if capability in info.meta.capabilities:
                matching[name] = info
        return matching
    
    def get_models(self, extension_name: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Get models supported by extensions"""
        if extension_name:
            info = self.get_extension(extension_name)
            return {extension_name: info.meta.models}
        
        models = {}
        for name, info in self._extensions.items():
            if info.meta.models:
                models[name] = info.meta.models
        return models
    
    def find_extension_for_model(self, model_name: str) -> Optional[str]:
        """Find which extension supports a specific model"""
        for ext_name, info in self._extensions.items():
            for model in info.meta.models:
                if model.get('name') == model_name:
                    return ext_name
        return None
    
    def validate_dependencies(self, extension_name: str) -> tuple[bool, List[str]]:
        """Check if extension dependencies are satisfied"""
        info = self.get_extension(extension_name)
        missing = []
        
        for dep in info.meta.dependencies:
            try:
                # Simple check - try to import the package
                pkg_name = dep.split('>=')[0].split('==')[0].split('[')[0]
                importlib.import_module(pkg_name)
            except ImportError:
                missing.append(dep)
        
        return len(missing) == 0, missing
    
    def get_extension_summary(self) -> Dict[str, Any]:
        """Get summary of all extensions"""
        summary = {
            'total': len(self._extensions),
            'by_type': {
                'decorator': len(self.list_by_type('decorator')),
                'config': len(self.list_by_type('config'))
            },
            'extensions': {}
        }
        
        for name, info in self._extensions.items():
            summary['extensions'][name] = {
                'type': info.type,
                'version': info.meta.version,
                'models': [m.get('name', 'unknown') for m in info.meta.models],
                'capabilities': info.meta.capabilities,
                'loaded': info.loaded
            }
        
        return summary
    
    def clear(self) -> None:
        """Clear all registered extensions"""
        self._extensions.clear()
        self._loaded_instances.clear()
    
    def remove_extension(self, name: str) -> None:
        """Remove extension from registry"""
        if name in self._extensions:
            del self._extensions[name]
        if name in self._loaded_instances:
            del self._loaded_instances[name]


# Global registry instance
global_registry = ExtensionRegistry()


def get_global_registry() -> ExtensionRegistry:
    """Get the global extension registry"""
    return global_registry


def register_extension_class(extension_cls: type) -> None:
    """Register extension class with global registry"""
    global_registry.register_decorator(extension_cls)


def register_extension_config(config_file: str) -> None:
    """Register extension config with global registry"""  
    global_registry.register_config(config_file)


def find_extension_for_model(model_name: str) -> Optional[str]:
    """Find extension that supports a model (convenience function)"""
    return global_registry.find_extension_for_model(model_name)