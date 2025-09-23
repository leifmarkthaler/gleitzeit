"""
Handler package with automatic discovery.

All handler modules in this directory are automatically imported and registered.
This allows for simple addition of new handlers without modifying configuration.
"""

import pkgutil
import importlib
import logging
from typing import Dict, Any, Optional

from .base import BaseHandler
from .registry import HandlerRegistry
from .metrics import HandlerMetrics, MetricSnapshot

logger = logging.getLogger(__name__)

# Export main components
__all__ = [
    'BaseHandler',
    'HandlerRegistry',
    'HandlerMetrics',
    'MetricSnapshot',
    'handler_loader',
    'discover_handlers',
]


def _auto_import_handlers() -> list[str]:
    """
    Import all handler modules to trigger registration.

    Returns:
        List of successfully imported module names
    """
    import gleitzeit.handlers as pkg

    discovered = []
    failed = []

    for loader, module_name, is_pkg in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + '.'):
        # Skip private modules and sub-packages
        if is_pkg or module_name.split('.')[-1].startswith('_'):
            continue

        # Skip non-handler modules
        if module_name.endswith(('.base', '.registry', '.metrics', '.test', '.tests')):
            continue

        try:
            # Import triggers @register decorator
            importlib.import_module(module_name)
            discovered.append(module_name.split('.')[-1])
            logger.debug(f"Imported handler module: {module_name}")

        except ImportError as e:
            failed.append((module_name, str(e)))
            logger.warning(f"Could not import handler module {module_name}: {e}")

        except Exception as e:
            failed.append((module_name, str(e)))
            logger.error(f"Error importing handler module {module_name}: {e}", exc_info=True)

    if discovered:
        logger.info(f"Auto-discovered {len(discovered)} handler modules: {', '.join(discovered)}")

    if failed:
        logger.warning(f"Failed to import {len(failed)} modules: {failed}")

    return discovered


def discover_handlers() -> Dict[str, type[BaseHandler]]:
    """
    Discover and import all handlers.

    This function triggers the import of all handler modules,
    which causes them to self-register via decorators.

    Returns:
        Dict mapping protocol to handler class
    """
    _auto_import_handlers()
    return HandlerRegistry.get_all_handlers()


class LazyHandlerLoader:
    """
    Lazy loader for handlers - only imports when accessed.

    This prevents import-time side effects and allows for faster startup.
    """

    def __init__(self):
        self._loaded = False
        self._discovered_modules: list[str] = []

    def _ensure_loaded(self):
        """Ensure all handlers are loaded"""
        if not self._loaded:
            self._discovered_modules = _auto_import_handlers()
            self._loaded = True

    def get_all_capabilities(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all handler capabilities - triggers loading.

        Returns:
            Dict mapping protocol to capabilities
        """
        self._ensure_loaded()
        return HandlerRegistry.get_all_capabilities()

    def get_registry(self) -> type:
        """
        Get the handler registry - triggers loading.

        Returns:
            HandlerRegistry class
        """
        self._ensure_loaded()
        return HandlerRegistry

    def get_handler(self, protocol: str) -> Optional[type[BaseHandler]]:
        """
        Get a specific handler by protocol.

        Args:
            protocol: Protocol identifier

        Returns:
            Handler class or None if not found
        """
        self._ensure_loaded()
        return HandlerRegistry.get_handler(protocol)

    def get_handler_for_type(self, task_type: str) -> Optional[type[BaseHandler]]:
        """
        Get handler for a task type.

        Args:
            task_type: Task type name

        Returns:
            Handler class or None if not found
        """
        self._ensure_loaded()
        return HandlerRegistry.get_handler_for_type(task_type)

    def get_handler_for_method(self, method: str) -> Optional[type[BaseHandler]]:
        """
        Get handler that supports a method.

        Args:
            method: Method name

        Returns:
            Handler class or None if not found
        """
        self._ensure_loaded()
        return HandlerRegistry.get_handler_for_method(method)

    def get_info(self) -> Dict[str, Any]:
        """
        Get information about loaded handlers.

        Returns:
            Dict with handler information
        """
        self._ensure_loaded()
        return {
            'loaded': self._loaded,
            'discovered_modules': self._discovered_modules,
            'registry_info': HandlerRegistry.get_registry_info()
        }

    def reset(self):
        """Reset the loader (mainly for testing)"""
        self._loaded = False
        self._discovered_modules = []
        HandlerRegistry.clear()


# Create global loader instance
handler_loader = LazyHandlerLoader()

# Convenience function for eager loading
def load_all_handlers():
    """Load all handlers immediately (instead of lazy loading)"""
    return handler_loader.get_all_capabilities()