"""
Ultra-Simplified Provider System

The absolute minimal code needed to create powerful providers.
"""

from typing import Dict, Any, Optional, Callable
from functools import wraps
import inspect

from .base import ProtocolProvider
from .http_provider import HTTPProvider


class UltraSimpleProvider(ProtocolProvider):
    """
    Ultra-simple provider that uses decorators for method routing.
    
    Example - Complete LLM provider in ~20 lines:
    
        class MyLLM(UltraSimpleProvider):
            base_url = "http://localhost:11434"
            
            @method("generate", "complete")  
            async def generate_text(self, prompt: str, model: str = "llama3.2"):
                return await self.post("/api/generate", {
                    "model": model, "prompt": prompt, "stream": False
                })
                
            @method("chat")
            async def chat(self, messages: list, model: str = "llama3.2"):
                return await self.post("/api/chat", {
                    "model": model, "messages": messages
                })
    """
    
    def __init__(self, **kwargs):
        # Auto-generate provider_id from class name if not provided
        if 'provider_id' not in kwargs:
            kwargs['provider_id'] = self.__class__.__name__.lower().replace('provider', '')
        
        # Auto-generate protocol_id if not provided
        if 'protocol_id' not in kwargs:
            kwargs['protocol_id'] = f"{kwargs['provider_id']}/v1"
            
        super().__init__(**kwargs)
        
        # Build method routing table from decorated methods
        self._method_routes = {}
        for name, func in inspect.getmembers(self, inspect.ismethod):
            if hasattr(func, '_method_names'):
                for method_name in func._method_names:
                    self._method_routes[method_name] = func
        
        # Re-generate protocol after method routes are set up (if auto-generation is enabled)
        if self.auto_generate_protocol and self._method_routes:
            self._generated_protocol = self._generate_protocol()
            if self.register_protocol and self._generated_protocol and self.protocol_registry:
                self._register_generated_protocol()
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Any:
        """Route to decorated methods automatically"""
        if method in self._method_routes:
            handler = self._method_routes[method]
            
            # If handler accepts **kwargs, pass all params
            sig = inspect.signature(handler)
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                # Handler accepts **kwargs, pass everything
                return await handler(**params)
            
            # Otherwise, extract parameters that match the handler's signature
            handler_params = {}
            for param_name, param_spec in sig.parameters.items():
                if param_name == 'self':
                    continue
                if param_name in params:
                    handler_params[param_name] = params[param_name]
                elif param_spec.default is not inspect.Parameter.empty:
                    # Use default value if not provided
                    pass
                else:
                    # Required parameter missing
                    from gleitzeit.core.errors import InvalidParameterError
                    raise InvalidParameterError(param_name, f"Required parameter '{param_name}' not provided")
            
            # Call the handler with extracted parameters
            return await handler(**handler_params)
        else:
            from gleitzeit.core.errors import InvalidParameterError
            raise InvalidParameterError("method", f"Unknown method: {method}")
    
    def get_supported_methods(self):
        """Return all registered method names"""
        return list(self._method_routes.keys())
    
    # Default implementations
    async def initialize(self) -> None:
        """Default: no initialization needed"""
        pass
    
    async def shutdown(self) -> None:
        """Default: no cleanup needed"""
        pass
    
    async def health_check(self) -> bool:
        """Default: always healthy"""
        return True


class UltraHTTPProvider(HTTPProvider):
    """
    Ultra-simple HTTP provider with method routing.
    
    Example:
        class WeatherAPI(UltraHTTPProvider):
            base_url = "https://api.weather.com"
            
            @method("get_weather")
            async def weather(self, city: str):
                data = await self.get(f"/current/{city}")
                return {"temp": data["main"]["temp"], "condition": data["weather"][0]["main"]}
    """
    
    def __init__(self, **kwargs):
        # Auto-configuration
        if 'provider_id' not in kwargs:
            kwargs['provider_id'] = self.__class__.__name__.lower().replace('provider', '')
        if 'protocol_id' not in kwargs:
            kwargs['protocol_id'] = f"{kwargs['provider_id']}/v1"
            
        super().__init__(**kwargs)
        
        # Build method routing
        self._method_routes = {}
        for name, func in inspect.getmembers(self, inspect.ismethod):
            if hasattr(func, '_method_names'):
                for method_name in func._method_names:
                    self._method_routes[method_name] = func
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Any:
        """Route to decorated methods with smart parameter extraction"""
        if method in self._method_routes:
            handler = self._method_routes[method]
            
            # If handler accepts **kwargs, pass all params
            sig = inspect.signature(handler)
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                # Handler accepts **kwargs, pass everything
                return await handler(**params)
            
            # Smart parameter extraction based on function signature
            handler_params = {}
            for param_name, param_spec in sig.parameters.items():
                if param_name == 'self':
                    continue
                if param_name in params:
                    handler_params[param_name] = params[param_name]
                elif param_spec.default is not inspect.Parameter.empty:
                    pass  # Use default
                else:
                    from gleitzeit.core.errors import InvalidParameterError
                    raise InvalidParameterError(param_name, f"Required: '{param_name}'")
            
            return await handler(**handler_params)
        else:
            from gleitzeit.core.errors import InvalidParameterError
            raise InvalidParameterError("method", f"Unknown method: {method}")
    
    def get_supported_methods(self):
        return list(self._method_routes.keys())


# Decorator for method routing
def method(*method_names):
    """
    Decorator to register a handler for one or more methods.
    
    Example:
        @method("generate", "complete")
        async def generate_text(self, prompt: str):
            return {"response": f"Generated: {prompt}"}
    """
    def decorator(func):
        func._method_names = method_names
        return func
    return decorator


# Ultra-simple factory functions
def create_llm_provider(
    base_url: str = "http://localhost:11434",
    default_model: str = "llama3.2",
    provider_id: str = "llm"
) -> UltraHTTPProvider:
    """
    Create a complete LLM provider in one line.
    
    Example:
        llm = create_llm_provider("http://localhost:11434")
        result = await llm.handle_request("generate", {"prompt": "Hello"})
    """
    
    class AutoLLMProvider(UltraHTTPProvider):
        def __init__(self):
            super().__init__(
                provider_id=provider_id,
                base_url=base_url
            )
            self.default_model = default_model
        
        @method("generate", "complete")
        async def generate(self, prompt: str, model: Optional[str] = None, **kwargs):
            return await self.post("/api/generate", {
                "model": model or self.default_model,
                "prompt": prompt,
                "stream": False,
                **kwargs
            })
        
        @method("chat")
        async def chat(self, messages: list, model: Optional[str] = None, **kwargs):
            response = await self.post("/api/chat", {
                "model": model or self.default_model,
                "messages": messages,
                "stream": False,
                **kwargs
            })
            return {
                "response": response.get("message", {}).get("content", ""),
                "raw": response
            }
        
        @method("embeddings")
        async def embeddings(self, text: str, model: str = "nomic-embed-text"):
            return await self.post("/api/embeddings", {
                "model": model,
                "prompt": text
            })
        
        @method("models")
        async def list_models(self):
            response = await self.get("/api/tags")
            return {"models": [m["name"] for m in response.get("models", [])]}
    
    return AutoLLMProvider()


def create_rest_provider(
    base_url: str,
    endpoints: Dict[str, str],
    provider_id: Optional[str] = None
) -> UltraHTTPProvider:
    """
    Create a REST API provider from a simple endpoint map.
    
    Example:
        api = create_rest_provider(
            "https://api.example.com",
            {
                "list_users": "GET /users",
                "get_user": "GET /users/{id}",
                "create_user": "POST /users",
                "update_user": "PUT /users/{id}",
                "delete_user": "DELETE /users/{id}"
            }
        )
    """
    
    class AutoRESTProvider(UltraHTTPProvider):
        def __init__(self):
            super().__init__(
                provider_id=provider_id or "rest",
                base_url=base_url
            )
            
            # Dynamically create methods from endpoints
            for method_name, endpoint_spec in endpoints.items():
                self._create_endpoint_method(method_name, endpoint_spec)
        
        def _create_endpoint_method(self, method_name: str, endpoint_spec: str):
            """Dynamically create a method for an endpoint"""
            parts = endpoint_spec.split()
            http_method = parts[0].upper()
            path_template = parts[1]
            
            async def endpoint_handler(**params):
                # Replace path parameters
                path = path_template
                body_params = dict(params)
                
                # Extract path parameters
                import re
                for match in re.finditer(r'\{(\w+)\}', path_template):
                    param_name = match.group(1)
                    if param_name in params:
                        path = path.replace(f"{{{param_name}}}", str(params[param_name]))
                        del body_params[param_name]
                
                # Make the HTTP request
                if http_method == "GET":
                    return await self.get(path, params=body_params if body_params else None)
                elif http_method == "POST":
                    return await self.post(path, data=body_params)
                elif http_method == "PUT":
                    return await self.put(path, data=body_params)
                elif http_method == "DELETE":
                    return await self.delete(path)
                elif http_method == "PATCH":
                    return await self.patch(path, data=body_params)
                else:
                    raise ValueError(f"Unsupported HTTP method: {http_method}")
            
            # Mark as a method handler
            endpoint_handler._method_names = [method_name]
            
            # Bind to instance
            setattr(self, method_name, endpoint_handler)
            
            # Register in routes
            if not hasattr(self, '_method_routes'):
                self._method_routes = {}
            self._method_routes[method_name] = endpoint_handler
    
    return AutoRESTProvider()


# Lambda-style provider creation
def lambda_provider(handler: Callable, provider_id: str = "lambda") -> UltraSimpleProvider:
    """
    Create a provider from a single function.
    
    Example:
        provider = lambda_provider(
            lambda method, **params: {
                "generate": lambda prompt: {"response": f"Echo: {prompt}"},
                "chat": lambda messages: {"response": messages[-1]["content"]}
            }.get(method, lambda **kw: {"error": "Unknown method"})(**params)
        )
    """
    
    class LambdaProvider(UltraSimpleProvider):
        async def execute(self, method: str, params: Dict[str, Any]) -> Any:
            if inspect.iscoroutinefunction(handler):
                return await handler(method, **params)
            else:
                return handler(method, **params)
    
    return LambdaProvider(provider_id=provider_id)