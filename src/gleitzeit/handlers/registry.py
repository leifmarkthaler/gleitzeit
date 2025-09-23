"""
Handler registry for auto-discovery and registration.

This registry allows handlers to self-register using decorators and provides
centralized access to handler capabilities for validation and discovery.
"""

import logging
from typing import Dict, Type, Optional, List, Any

from .base import BaseHandler

logger = logging.getLogger(__name__)


class HandlerRegistry:
    """
    Global registry for task handlers.

    Handlers register themselves using the @HandlerRegistry.register decorator.
    This registry provides:
    - Auto-registration on import
    - Protocol to handler mapping
    - Task type to handler mapping (for backward compatibility)
    - Capability discovery
    """

    # Class-level storage for registered handlers
    _handlers: Dict[str, Type[BaseHandler]] = {}
    _type_mapping: Dict[str, Type[BaseHandler]] = {}
    _initialized = False

    @classmethod
    def register(cls, handler_class: Type[BaseHandler]) -> Type[BaseHandler]:
        """
        Decorator to register a handler class.

        Usage:
            @HandlerRegistry.register
            class MyHandler(BaseHandler):
                ...

        Args:
            handler_class: Handler class to register

        Returns:
            The handler class (unchanged)

        Raises:
            ValueError: If handler is invalid or duplicate protocol
        """
        # Validate handler class
        if not issubclass(handler_class, BaseHandler):
            raise ValueError(f"{handler_class.__name__} must inherit from BaseHandler")

        # Get capabilities
        try:
            caps = handler_class.get_capabilities()
        except Exception as e:
            raise ValueError(f"Failed to get capabilities from {handler_class.__name__}: {e}")

        # Validate capabilities
        if not caps.get('protocol'):
            raise ValueError(f"{handler_class.__name__} must define a protocol")

        protocol = caps['protocol']

        # Check for duplicate registration
        if protocol in cls._handlers:
            existing = cls._handlers[protocol]
            if existing != handler_class:
                logger.warning(
                    f"Protocol {protocol} already registered to {existing.__name__}, "
                    f"overriding with {handler_class.__name__}"
                )

        # Register by protocol
        cls._handlers[protocol] = handler_class
        logger.info(f"Registered handler {handler_class.__name__} for protocol {protocol}")

        # Register by task type for backward compatibility
        for task_type in caps.get('task_types', []):
            cls._type_mapping[task_type] = handler_class
            logger.debug(f"  - Mapped task type '{task_type}' to {handler_class.__name__}")

        return handler_class

    @classmethod
    def get_handler(cls, protocol: str) -> Optional[Type[BaseHandler]]:
        """
        Get handler class by protocol.

        Args:
            protocol: Protocol identifier (e.g., 'python/v1')

        Returns:
            Handler class or None if not found
        """
        return cls._handlers.get(protocol)

    @classmethod
    def get_handler_for_type(cls, task_type: str) -> Optional[Type[BaseHandler]]:
        """
        Get handler class by task type.

        This is for backward compatibility with task type-based routing.

        Args:
            task_type: Task type (e.g., 'python', 'timer')

        Returns:
            Handler class or None if not found
        """
        return cls._type_mapping.get(task_type)

    @classmethod
    def get_handler_for_method(cls, method: str) -> Optional[Type[BaseHandler]]:
        """
        Get handler that supports a specific method.

        Args:
            method: Method name (e.g., 'python/execute')

        Returns:
            Handler class or None if not found
        """
        for handler_class in cls._handlers.values():
            caps = handler_class.get_capabilities()
            if method in caps.get('methods', {}):
                return handler_class
        return None

    @classmethod
    def get_all_handlers(cls) -> Dict[str, Type[BaseHandler]]:
        """
        Get all registered handlers.

        Returns:
            Dict mapping protocol to handler class
        """
        return cls._handlers.copy()

    @classmethod
    def get_all_capabilities(cls) -> Dict[str, Dict[str, Any]]:
        """
        Get capabilities from all registered handlers.

        Returns:
            Dict mapping protocol to capabilities
        """
        return {
            protocol: handler.get_capabilities()
            for protocol, handler in cls._handlers.items()
        }

    @classmethod
    def get_supported_protocols(cls) -> List[str]:
        """
        Get list of supported protocols.

        Returns:
            List of protocol identifiers
        """
        return list(cls._handlers.keys())

    @classmethod
    def get_supported_task_types(cls) -> List[str]:
        """
        Get list of supported task types.

        Returns:
            List of task type names
        """
        return list(cls._type_mapping.keys())

    @classmethod
    def get_supported_methods(cls) -> List[str]:
        """
        Get list of all supported methods across all handlers.

        Returns:
            List of method names
        """
        methods = []
        for handler_class in cls._handlers.values():
            caps = handler_class.get_capabilities()
            methods.extend(caps.get('methods', {}).keys())
        return methods

    @classmethod
    def clear(cls):
        """
        Clear all registrations.

        Mainly useful for testing.
        """
        cls._handlers.clear()
        cls._type_mapping.clear()
        logger.info("Handler registry cleared")

    @classmethod
    def validate_method(cls, method: str, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate if a method can be executed with given parameters.

        Args:
            method: Method name
            params: Parameters to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Find handler for method
        handler_class = cls.get_handler_for_method(method)
        if not handler_class:
            return False, f"No handler found for method '{method}'"

        # Get method spec
        caps = handler_class.get_capabilities()
        method_spec = caps['methods'].get(method, {})

        # Check required parameters
        for required in method_spec.get('required', []):
            if required not in params:
                return False, f"Missing required parameter '{required}'"

        return True, None

    @classmethod
    def get_registry_info(cls) -> Dict[str, Any]:
        """
        Get detailed registry information for debugging.

        Returns:
            Dict with registry statistics and details
        """
        return {
            'num_handlers': len(cls._handlers),
            'num_task_types': len(cls._type_mapping),
            'protocols': cls.get_supported_protocols(),
            'task_types': cls.get_supported_task_types(),
            'total_methods': len(cls.get_supported_methods()),
            'handlers': {
                protocol: {
                    'class': handler.__name__,
                    'module': handler.__module__,
                    'methods': list(handler.get_capabilities().get('methods', {}).keys())
                }
                for protocol, handler in cls._handlers.items()
            }
        }