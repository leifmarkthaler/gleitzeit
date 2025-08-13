"""
Extension Discovery System

Automatically finds and registers extensions from the filesystem,
supporting both decorator-based Python extensions and config-based YAML extensions.
"""

import os
import sys
import importlib
import importlib.util
from pathlib import Path
from typing import List, Dict, Any, Optional

from .registry import ExtensionInfo, ConfigExtensionMeta, global_registry
from .decorators import is_extension, get_extension_meta
from .exceptions import ExtensionValidationError


class ExtensionDiscovery:
    """Discovers extensions from filesystem"""
    
    def __init__(self):
        self._discovered_extensions: List[ExtensionInfo] = []
    
    def discover_all(self, search_paths: List[str]) -> List[ExtensionInfo]:
        """
        Discover all extensions in given paths
        
        Args:
            search_paths: List of directory paths to search
            
        Returns:
            List of discovered extension info
        """
        discovered = []
        
        for path in search_paths:
            path_obj = Path(path)
            if not path_obj.exists():
                print(f"⚠️  Extension search path not found: {path}")
                continue
            
            print(f"🔍 Searching for extensions in: {path}")
            
            # Find decorator-based extensions
            decorator_exts = self.discover_decorator_extensions(path)
            discovered.extend(decorator_exts)
            
            # Find config-based extensions  
            config_exts = self.discover_config_extensions(path)
            discovered.extend(config_exts)
        
        # Register discovered extensions
        for info in discovered:
            if info.type == "decorator":
                global_registry.register_decorator(info.extension_class)
            elif info.type == "config":
                global_registry.register_config(info.config_file)
        
        self._discovered_extensions = discovered
        return discovered
    
    def discover_decorator_extensions(self, search_path: str) -> List[ExtensionInfo]:
        """
        Find decorator-based extensions in Python files
        
        Args:
            search_path: Directory to search
            
        Returns:
            List of found decorator extensions
        """
        discovered = []
        search_dir = Path(search_path)
        
        if not search_dir.exists():
            return discovered
        
        # Look for Python files and packages
        for item in search_dir.iterdir():
            if item.is_file() and item.suffix == '.py' and not item.name.startswith('_'):
                # Single Python file
                extensions = self._load_python_file_extensions(item)
                discovered.extend(extensions)
            
            elif item.is_dir() and not item.name.startswith('_'):
                # Python package directory
                init_file = item / '__init__.py'
                if init_file.exists():
                    extensions = self._load_python_package_extensions(item)
                    discovered.extend(extensions)
        
        return discovered
    
    def discover_config_extensions(self, search_path: str) -> List[ExtensionInfo]:
        """
        Find config-based extensions (YAML files)
        
        Args:
            search_path: Directory to search
            
        Returns:
            List of found config extensions
        """
        discovered = []
        search_dir = Path(search_path)
        
        if not search_dir.exists():
            return discovered
        
        # Look for extension.yaml files
        for item in search_dir.rglob("extension.yaml"):
            try:
                info = self._load_config_extension_info(item)
                if info:
                    discovered.append(info)
            except Exception as e:
                print(f"⚠️  Failed to load config extension {item}: {e}")
        
        # Also look for standalone .yaml files that look like extensions
        for item in search_dir.glob("*.yaml"):
            if item.name != "extension.yaml":
                try:
                    info = self._load_config_extension_info(item)
                    if info:
                        discovered.append(info)
                except Exception:
                    # Not an extension config, that's fine
                    pass
        
        return discovered
    
    def _load_python_file_extensions(self, python_file: Path) -> List[ExtensionInfo]:
        """Load extensions from a single Python file"""
        extensions = []
        
        try:
            # Load module from file
            module_name = python_file.stem
            spec = importlib.util.spec_from_file_location(module_name, python_file)
            if not spec or not spec.loader:
                return extensions
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            
            # Look for extension classes in module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and is_extension(attr):
                    meta = get_extension_meta(attr)
                    if meta:
                        info = ExtensionInfo(
                            name=meta.name,
                            type="decorator",
                            meta=meta,
                            extension_class=attr
                        )
                        extensions.append(info)
                        print(f"   📦 Found decorator extension: {meta.name}")
            
        except Exception as e:
            print(f"⚠️  Failed to load Python file {python_file}: {e}")
        
        return extensions
    
    def _load_python_package_extensions(self, package_dir: Path) -> List[ExtensionInfo]:
        """Load extensions from a Python package directory"""
        extensions = []
        
        try:
            # Add package directory to Python path temporarily
            package_parent = str(package_dir.parent)
            if package_parent not in sys.path:
                sys.path.insert(0, package_parent)
                remove_from_path = True
            else:
                remove_from_path = False
            
            try:
                # Import package
                module = importlib.import_module(package_dir.name)
                
                # Look for extension classes
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and is_extension(attr):
                        meta = get_extension_meta(attr)
                        if meta:
                            info = ExtensionInfo(
                                name=meta.name,
                                type="decorator", 
                                meta=meta,
                                extension_class=attr
                            )
                            extensions.append(info)
                            print(f"   📦 Found decorator extension: {meta.name}")
                
                # Also check for __extension__ attribute
                if hasattr(module, '__extension__'):
                    ext_class = module.__extension__
                    if isinstance(ext_class, type) and is_extension(ext_class):
                        meta = get_extension_meta(ext_class)
                        if meta:
                            info = ExtensionInfo(
                                name=meta.name,
                                type="decorator",
                                meta=meta,
                                extension_class=ext_class
                            )
                            extensions.append(info)
                            print(f"   📦 Found __extension__: {meta.name}")
            
            finally:
                if remove_from_path:
                    sys.path.remove(package_parent)
        
        except Exception as e:
            print(f"⚠️  Failed to load package {package_dir}: {e}")
        
        return extensions
    
    def _load_config_extension_info(self, config_file: Path) -> Optional[ExtensionInfo]:
        """Load extension info from YAML config file"""
        try:
            import yaml
            
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            # Check if this looks like an extension config
            if not isinstance(config, dict) or 'name' not in config:
                return None
            
            # Must have required fields
            required_fields = ['name', 'description']
            if not all(field in config for field in required_fields):
                return None
            
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
                config_file=str(config_file)
            )
            
            info = ExtensionInfo(
                name=meta.name,
                type="config",
                meta=meta,
                config_file=str(config_file)
            )
            
            print(f"   📋 Found config extension: {meta.name}")
            return info
            
        except Exception as e:
            # Not a valid extension config
            return None
    
    def get_discovered_extensions(self) -> List[ExtensionInfo]:
        """Get list of discovered extensions from last discovery run"""
        return self._discovered_extensions.copy()
    
    def find_extension_by_name(self, name: str) -> Optional[ExtensionInfo]:
        """Find a discovered extension by name"""
        for info in self._discovered_extensions:
            if info.name == name:
                return info
        return None


def discover_extensions_in_paths(paths: List[str]) -> List[ExtensionInfo]:
    """
    Convenience function to discover extensions in given paths
    
    Args:
        paths: List of directory paths to search
        
    Returns:
        List of discovered extensions
    """
    discovery = ExtensionDiscovery()
    return discovery.discover_all(paths)