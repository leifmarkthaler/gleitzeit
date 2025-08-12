"""
Extension Decorators

Decorator-based extension definition system for easy, code-first extension creation.

Usage:
    @extension(name="my-provider", description="My LLM provider")
    @requires("requests>=2.0")
    @model("my-model", capabilities=["text"])
    @capability("streaming", "function_calling")
    class MyProviderExtension:
        async def setup(self):
            # Extension initialization
            pass
        
        async def generate_text(self, prompt: str, model: str = "my-model") -> str:
            # Text generation implementation
            pass
"""

import functools
import inspect
from typing import List, Dict, Any, Optional, Callable, Union
from dataclasses import dataclass, field

from .exceptions import ExtensionValidationError


@dataclass
class ExtensionMeta:
    """Metadata for decorator-based extensions"""
    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    models: List[Dict[str, Any]] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)
    

def extension(
    name: str,
    description: str = "",
    version: str = "1.0.0", 
    author: str = ""
) -> Callable:
    """
    Mark a class as a Gleitzeit extension
    
    Args:
        name: Extension name (used for loading)
        description: Human-readable description
        version: Extension version
        author: Extension author
    
    Example:
        @extension(name="openai", description="OpenAI integration", version="1.0.0")
        class OpenAIExtension:
            pass
    """
    def decorator(cls):
        # Create metadata container
        meta = ExtensionMeta(
            name=name,
            description=description,
            version=version,
            author=author
        )
        
        # Store metadata on class
        cls._meta = meta
        cls._is_gleitzeit_extension = True
        
        # Validate extension structure
        _validate_extension_class(cls)
        
        # Auto-register with global registry if available
        try:
            from .registry import global_registry
            global_registry.register_decorator(cls)
        except ImportError:
            # Registry not available yet, that's ok
            pass
        
        return cls
    
    return decorator


def requires(*dependencies: str) -> Callable:
    """
    Specify extension dependencies
    
    Args:
        dependencies: Package requirements (e.g., "openai>=1.0", "tiktoken")
    
    Example:
        @requires("openai>=1.0", "tiktoken>=0.5")
        class OpenAIExtension:
            pass
    """
    def decorator(cls):
        if not hasattr(cls, '_meta'):
            raise ExtensionValidationError(
                cls.__name__, 
                ["@requires must be used after @extension decorator"]
            )
        
        cls._meta.dependencies.extend(dependencies)
        return cls
    
    return decorator


def model(
    name: str,
    capabilities: Optional[List[str]] = None,
    max_tokens: Optional[int] = None,
    cost_per_token: Optional[float] = None,
    **kwargs
) -> Callable:
    """
    Register a model supported by this extension
    
    Args:
        name: Model name (e.g., "gpt-4")
        capabilities: List of capabilities (e.g., ["text", "vision"])
        max_tokens: Maximum tokens supported
        cost_per_token: Cost per token
        **kwargs: Additional model metadata
    
    Example:
        @model("gpt-4", capabilities=["text", "vision"], max_tokens=8192)
        @model("gpt-3.5-turbo", capabilities=["text"], max_tokens=4096)
        class OpenAIExtension:
            pass
    """
    def decorator(cls):
        if not hasattr(cls, '_meta'):
            raise ExtensionValidationError(
                cls.__name__,
                ["@model must be used after @extension decorator"]
            )
        
        model_info = {
            "name": name,
            "capabilities": capabilities or [],
            "max_tokens": max_tokens,
            "cost_per_token": cost_per_token,
            **kwargs
        }
        
        cls._meta.models.append(model_info)
        return cls
    
    return decorator


def capability(*capabilities: str) -> Callable:
    """
    Specify extension capabilities
    
    Args:
        capabilities: List of capabilities (e.g., "streaming", "function_calling")
    
    Example:
        @capability("streaming", "function_calling", "vision")
        class MyExtension:
            pass
    """
    def decorator(cls):
        if not hasattr(cls, '_meta'):
            raise ExtensionValidationError(
                cls.__name__,
                ["@capability must be used after @extension decorator"]
            )
        
        cls._meta.capabilities.extend(capabilities)
        return cls
    
    return decorator


def config_field(
    name: str,
    field_type: str = "string",
    required: bool = False,
    default: Any = None,
    env_var: Optional[str] = None,
    description: str = "",
    **kwargs
) -> Callable:
    """
    Define a configuration field for the extension
    
    Args:
        name: Configuration field name
        field_type: Type of field ("string", "integer", "boolean", "list")
        required: Whether field is required
        default: Default value
        env_var: Environment variable to read from
        description: Field description
        **kwargs: Additional validation options
    
    Example:
        @config_field("api_key", required=True, env_var="OPENAI_API_KEY")
        @config_field("timeout", field_type="integer", default=60)
        class OpenAIExtension:
            pass
    """
    def decorator(cls):
        if not hasattr(cls, '_meta'):
            raise ExtensionValidationError(
                cls.__name__,
                ["@config_field must be used after @extension decorator"]
            )
        
        field_info = {
            "type": field_type,
            "required": required,
            "default": default,
            "env_var": env_var,
            "description": description,
            **kwargs
        }
        
        cls._meta.config_schema[name] = field_info
        return cls
    
    return decorator


def _validate_extension_class(cls) -> None:
    """Validate that extension class has required structure"""
    errors = []
    
    # Check for required methods
    required_methods = ['setup']
    for method in required_methods:
        if not hasattr(cls, method):
            errors.append(f"Extension must implement '{method}' method")
        elif not callable(getattr(cls, method)):
            errors.append(f"Extension '{method}' must be callable")
    
    # Check for at least one handler method
    handler_methods = []
    for attr_name in dir(cls):
        attr = getattr(cls, attr_name)
        if callable(attr) and not attr_name.startswith('_'):
            if attr_name in ['generate_text', 'generate_vision', 'execute_function']:
                handler_methods.append(attr_name)
    
    if not handler_methods and not hasattr(cls, '_custom_handlers'):
        errors.append("Extension should implement at least one handler method (generate_text, generate_vision, etc.)")
    
    # Check __init__ signature
    init_sig = inspect.signature(cls.__init__)
    if len(init_sig.parameters) < 2:  # self + at least one config param
        errors.append("Extension __init__ should accept configuration parameters")
    
    if errors:
        raise ExtensionValidationError(cls.__name__, errors)


def handler(event_name: str) -> Callable:
    """
    Mark a method as an event handler
    
    Args:
        event_name: Socket.IO event name to handle
    
    Example:
        @handler("custom_generate")
        async def handle_custom_generate(self, task_data: dict) -> dict:
            # Custom handling logic
            pass
    """
    def decorator(func):
        func._is_handler = True
        func._event_name = event_name
        return func
    
    return decorator


# Utility functions for working with decorated extensions
def is_extension(cls) -> bool:
    """Check if a class is a decorated extension"""
    return hasattr(cls, '_is_gleitzeit_extension') and cls._is_gleitzeit_extension


def get_extension_meta(cls) -> Optional[ExtensionMeta]:
    """Get extension metadata from decorated class"""
    return getattr(cls, '_meta', None)


def get_extension_handlers(cls) -> Dict[str, str]:
    """Get mapping of event names to handler methods"""
    handlers = {}
    
    for attr_name in dir(cls):
        attr = getattr(cls, attr_name)
        if callable(attr) and hasattr(attr, '_is_handler'):
            handlers[attr._event_name] = attr_name
    
    return handlers