"""
Provider Decorators

Simple decorators to create providers from functions.
Perfect for quick prototypes and simple integrations.
"""

from typing import Callable, List, Optional, Dict, Any
from functools import wraps
import inspect

from .simple import SimpleProvider
from gleitzeit.core.errors import ProviderError


def provider(
    protocol_id: str,
    provider_id: Optional[str] = None,
    methods: Optional[List[str]] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    version: str = "1.0.0",
    **provider_kwargs
):
    """
    Decorator to create a provider from a simple function.
    
    This is the easiest way to create a provider - just decorate a function
    that takes (method, **params) and returns a result.
    
    Args:
        protocol_id: Protocol identifier (e.g., "weather/v1")
        provider_id: Provider identifier (defaults to function name)
        methods: List of supported methods (for documentation)
        name: Human-readable name
        description: Provider description
        version: Provider version
        **provider_kwargs: Additional arguments passed to SimpleProvider
    
    Returns:
        SimpleProvider instance that wraps the function
    
    Example:
        @provider("weather/v1", methods=["get_weather", "get_forecast"])
        async def weather_provider(method: str, **params):
            if method == "get_weather":
                return {"temp": 20, "city": params.get("city", "London")}
            elif method == "get_forecast":
                return {"forecast": "sunny", "days": params.get("days", 7)}
            else:
                raise ValueError(f"Unknown method: {method}")
        
        # weather_provider is now a SimpleProvider instance
        result = await weather_provider.execute("get_weather", city="Paris")
    """
    def decorator(func: Callable) -> SimpleProvider:
        # Ensure function is async
        if not inspect.iscoroutinefunction(func):
            raise ValueError(f"Provider function {func.__name__} must be async")
        
        # Create provider class
        class DecoratedProvider(SimpleProvider):
            async def execute(self, method: str, **params) -> Any:
                return await func(method, **params)
            
            def get_supported_methods(self) -> List[str]:
                return methods or []
        
        # Determine provider ID
        actual_provider_id = provider_id or func.__name__
        if actual_provider_id.endswith('_provider'):
            actual_provider_id = actual_provider_id[:-9]  # Remove '_provider' suffix
        
        # Create and return instance
        instance = DecoratedProvider(
            provider_id=actual_provider_id,
            protocol_id=protocol_id,
            name=name or f"{actual_provider_id.title()} Provider",
            description=description or func.__doc__ or f"Provider for {protocol_id}",
            version=version,
            **provider_kwargs
        )
        
        # Copy function metadata
        instance.__name__ = func.__name__
        instance.__doc__ = func.__doc__
        instance.__module__ = func.__module__
        
        return instance
    
    return decorator


def method_handler(method_name: str):
    """
    Decorator to mark a function as a handler for a specific method.
    
    Use this with the @provider_class decorator to build providers
    with multiple method handlers.
    
    Args:
        method_name: The method name this function handles
    
    Example:
        @provider_class("weather/v1")
        class WeatherProvider:
            @method_handler("get_weather")
            async def get_weather(self, **params):
                return {"temp": 20, "city": params.get("city")}
            
            @method_handler("get_forecast") 
            async def get_forecast(self, **params):
                return {"forecast": "sunny", "days": params.get("days", 7)}
    """
    def decorator(func: Callable) -> Callable:
        func._method_name = method_name
        func._is_method_handler = True
        return func
    return decorator


def provider_class(
    protocol_id: str,
    provider_id: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    version: str = "1.0.0",
    **provider_kwargs
):
    """
    Class decorator to convert a class with @method_handler methods
    into a SimpleProvider.
    
    This provides a middle ground between the simple @provider function
    decorator and full SimpleProvider inheritance.
    
    Args:
        protocol_id: Protocol identifier
        provider_id: Provider identifier (defaults to class name)
        name: Human-readable name
        description: Provider description
        version: Provider version
        **provider_kwargs: Additional arguments passed to SimpleProvider
    
    Returns:
        Function that creates SimpleProvider instances
    
    Example:
        @provider_class("weather/v1")
        class WeatherProvider:
            def __init__(self, api_key):
                self.api_key = api_key
            
            @method_handler("get_weather")
            async def get_weather(self, **params):
                city = params.get("city", "London")
                # Use self.api_key here
                return {"temp": 20, "city": city, "api_key_used": bool(self.api_key)}
            
            @method_handler("get_forecast")
            async def get_forecast(self, **params):
                return {"forecast": "sunny", "days": params.get("days", 7)}
        
        # Usage:
        weather = WeatherProvider(api_key="my-key")
        result = await weather.get_weather(city="Paris")
    """
    def decorator(cls):
        # Find all method handlers
        method_handlers = {}
        method_names = []
        
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if hasattr(attr, '_is_method_handler'):
                method_name = attr._method_name
                method_handlers[method_name] = attr
                method_names.append(method_name)
        
        if not method_handlers:
            raise ValueError(f"Class {cls.__name__} has no @method_handler decorated methods")
        
        # Create the provider class
        class ClassBasedProvider(SimpleProvider):
            def __init__(self, *args, **kwargs):
                # Separate provider kwargs from user class kwargs
                provider_init_kwargs = {}
                user_kwargs = {}
                
                # Known provider arguments
                provider_args = {
                    'provider_id', 'protocol_id', 'name', 'description', 'version',
                    'max_retries', 'retry_delay', 'retry_backoff', 'resource_manager', 'hub'
                }
                
                for key, value in kwargs.items():
                    if key in provider_args:
                        provider_init_kwargs[key] = value
                    else:
                        user_kwargs[key] = value
                
                # Initialize provider
                actual_provider_id = provider_id or cls.__name__.lower()
                if actual_provider_id.endswith('provider'):
                    actual_provider_id = actual_provider_id[:-8]
                
                super().__init__(
                    provider_id=actual_provider_id,
                    protocol_id=protocol_id,
                    name=name or f"{actual_provider_id.title()} Provider",
                    description=description or cls.__doc__ or f"Provider for {protocol_id}",
                    version=version,
                    **provider_kwargs,
                    **provider_init_kwargs
                )
                
                # Initialize user class
                self._user_instance = cls(*args, **user_kwargs)
            
            async def execute(self, method: str, **params) -> Any:
                if method not in method_handlers:
                    available = ", ".join(method_handlers.keys())
                    raise ProviderError(f"Unknown method: {method}. Available methods: {available}")
                
                # Call the method handler on the user instance
                handler = method_handlers[method]
                return await handler(self._user_instance, **params)
            
            def get_supported_methods(self) -> List[str]:
                return method_names
        
        # Factory function to create provider instances
        def create_provider(*args, **kwargs):
            return ClassBasedProvider(*args, **kwargs)
        
        # Copy metadata
        create_provider.__name__ = cls.__name__
        create_provider.__doc__ = cls.__doc__
        create_provider.__module__ = cls.__module__
        create_provider._original_class = cls
        create_provider._method_handlers = method_handlers
        create_provider._supported_methods = method_names
        
        return create_provider
    
    return decorator


def simple_http_provider(
    base_url: str,
    protocol_id: str,
    provider_id: Optional[str] = None,
    auth_header: Optional[str] = None,
    **provider_kwargs
):
    """
    Decorator for creating simple HTTP providers from endpoint configurations.
    
    Args:
        base_url: Base URL for the API
        protocol_id: Protocol identifier
        provider_id: Provider identifier (defaults to function name)
        auth_header: Authorization header value (e.g., "Bearer token")
        **provider_kwargs: Additional provider arguments
    
    Example:
        @simple_http_provider(
            base_url="https://api.weather.com",
            protocol_id="weather/v1",
            auth_header="Bearer my-token"
        )
        async def weather_endpoints():
            return {
                "get_weather": {
                    "method": "GET",
                    "path": "/current/{city}",
                    "params": ["city"],
                    "response_map": {
                        "temperature": "main.temp",
                        "condition": "weather[0].main"
                    }
                },
                "get_forecast": {
                    "method": "GET", 
                    "path": "/forecast/{city}",
                    "params": ["city", "days"],
                    "response_map": {
                        "forecast": "list[0].weather[0].main",
                        "days": "cnt"
                    }
                }
            }
    """
    def decorator(func: Callable) -> SimpleProvider:
        # Get endpoint configuration
        if inspect.iscoroutinefunction(func):
            raise ValueError("Endpoint configuration function should not be async")
        
        endpoints_config = func()
        if not isinstance(endpoints_config, dict):
            raise ValueError("Endpoint configuration must return a dictionary")
        
        # Create HTTP provider class
        class HTTPConfigProvider(SimpleProvider):
            def __init__(self):
                actual_provider_id = provider_id or func.__name__.replace('_endpoints', '')
                super().__init__(
                    provider_id=actual_provider_id,
                    protocol_id=protocol_id,
                    name=f"{actual_provider_id.title()} HTTP Provider",
                    description=f"HTTP provider for {protocol_id}",
                    **provider_kwargs
                )
                self.base_url = base_url.rstrip('/')
                self.auth_header = auth_header
                self.endpoints = endpoints_config
                
                # Set up HTTP session
                import aiohttp
                self._session = None
            
            async def initialize(self):
                import aiohttp
                headers = {}
                if self.auth_header:
                    headers["Authorization"] = self.auth_header
                
                self._session = aiohttp.ClientSession(headers=headers)
            
            async def shutdown(self):
                if self._session:
                    await self._session.close()
            
            async def execute(self, method: str, **params) -> Any:
                if method not in self.endpoints:
                    available = ", ".join(self.endpoints.keys())
                    raise ProviderError(f"Unknown method: {method}. Available: {available}")
                
                config = self.endpoints[method]
                
                # Build URL with path parameters
                path = config["path"]
                for param in config.get("params", []):
                    if param in params:
                        path = path.replace(f"{{{param}}}", str(params[param]))
                
                url = f"{self.base_url}{path}"
                
                # Make request
                http_method = config.get("method", "GET").upper()
                
                async with self._session.request(http_method, url) as response:
                    response.raise_for_status()
                    data = await response.json()
                    
                    # Apply response mapping if configured
                    if "response_map" in config:
                        result = {}
                        for output_key, input_path in config["response_map"].items():
                            result[output_key] = self._extract_from_response(data, input_path)
                        return result
                    else:
                        return data
            
            def _extract_from_response(self, data: Any, path: str) -> Any:
                """Extract value from response using dot notation path"""
                current = data
                for part in path.split('.'):
                    if '[' in part and ']' in part:
                        # Handle array indexing like "weather[0]"
                        key, index_str = part.split('[')
                        index = int(index_str.rstrip(']'))
                        current = current[key][index]
                    else:
                        current = current[part]
                return current
            
            def get_supported_methods(self) -> List[str]:
                return list(self.endpoints.keys())
        
        return HTTPConfigProvider()
    
    return decorator


# New decorators for enhanced validation and monitoring

def validated_provider(
    strict: bool = False,
    auto_validate: bool = True
):
    """
    Class decorator that ensures provider is validated on creation.
    
    Usage:
        @validated_provider(strict=True)
        class MyProvider(SimpleProvider):
            async def execute(self, method, params):
                return {"result": "data"}
    
    Args:
        strict: Enable strict validation mode
        auto_validate: Validate on initialization (default: True)
    """
    def decorator(cls):
        original_init = cls.__init__
        
        @wraps(original_init)
        def new_init(self, *args, **kwargs):
            # Force validation settings
            kwargs['validate_on_init'] = auto_validate
            kwargs['strict_validation'] = strict
            
            # Call original init
            original_init(self, *args, **kwargs)
        
        cls.__init__ = new_init
        cls._validated_provider = True
        
        return cls
    
    return decorator


def auto_validated(cls):
    """
    Simple class decorator that enables automatic validation.
    
    Usage:
        @auto_validated
        class MyProvider(SimpleProvider):
            async def execute(self, method, params):
                return {"result": "data"}
    """
    return validated_provider(strict=False, auto_validate=True)(cls)