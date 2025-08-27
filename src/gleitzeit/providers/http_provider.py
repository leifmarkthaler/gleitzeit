"""
HTTP Provider

Simplified HTTP provider that combines HTTPServiceProvider functionality
with the SimpleProvider interface for easy HTTP API integration.
"""

import aiohttp
from typing import Dict, Any, Optional, List, Union
import json

from .simple import SimpleProvider
from gleitzeit.core.errors import ProviderError, NetworkError, AuthenticationError


class HTTPProvider(SimpleProvider):
    """
    Simplified HTTP provider for easy REST API integration.
    
    Combines the power of SimpleProvider with built-in HTTP functionality.
    Perfect for integrating with external APIs with minimal code.
    
    Attributes:
        base_url: Base URL for all requests
        default_headers: Headers sent with every request
        timeout: Request timeout in seconds
        
    Example:
        class WeatherProvider(HTTPProvider):
            base_url = "https://api.weather.com"
            
            async def execute(self, method: str, **params):
                if method == "get_weather":
                    response = await self.get("/current", params={"city": params["city"]})
                    return {
                        "temperature": response["main"]["temp"],
                        "condition": response["weather"][0]["main"]
                    }
    """
    
    # Class-level configuration (can be overridden)
    base_url: str = "http://localhost:8000"
    default_headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "User-Agent": "Gleitzeit-Provider/1.0"
    }
    timeout: int = 30
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        auth_token: Optional[str] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        
        # Override class attributes with instance values
        if base_url:
            self.base_url = base_url.rstrip('/')
        if headers:
            self.default_headers = {**self.default_headers, **headers}
        if timeout:
            self.timeout = timeout
            
        # Add authentication if provided
        if auth_token:
            self.default_headers["Authorization"] = f"Bearer {auth_token}"
        
        # HTTP session (initialized in initialize())
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self) -> None:
        """Initialize HTTP session with configured settings"""
        timeout_config = aiohttp.ClientTimeout(total=self.timeout)
        
        self.session = aiohttp.ClientSession(
            timeout=timeout_config,
            headers=self.default_headers
        )
        
        self.logger.info(f"HTTP provider initialized: {self.base_url}")
    
    async def shutdown(self) -> None:
        """Clean up HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def health_check(self) -> bool:
        """
        Default health check - tries to connect to base_url/health or base_url.
        Override for custom health check logic.
        """
        if not self.session:
            return False
            
        try:
            # Try common health check endpoints
            for path in ["/health", "/status", "/"]:
                try:
                    async with self.session.get(f"{self.base_url}{path}") as response:
                        return response.status < 500
                except:
                    continue
            return False
        except:
            return False
    
    # Convenience methods for HTTP requests
    
    async def get(
        self, 
        path: str, 
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Make GET request"""
        return await self._make_request("GET", path, params=params, headers=headers)
    
    async def post(
        self, 
        path: str, 
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Make POST request"""
        return await self._make_request("POST", path, data=data, params=params, headers=headers)
    
    async def put(
        self, 
        path: str, 
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Make PUT request"""
        return await self._make_request("PUT", path, data=data, headers=headers)
    
    async def delete(
        self, 
        path: str, 
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Make DELETE request"""
        return await self._make_request("DELETE", path, headers=headers)
    
    async def patch(
        self, 
        path: str, 
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Make PATCH request"""
        return await self._make_request("PATCH", path, data=data, headers=headers)
    
    async def _make_request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Internal method to make HTTP requests with error handling.
        
        Args:
            method: HTTP method
            path: URL path (relative to base_url)
            data: Request body data
            params: URL parameters
            headers: Additional headers
            
        Returns:
            Response data as dictionary
            
        Raises:
            NetworkError: For connection issues
            AuthenticationError: For 401/403 responses
            ProviderError: For other HTTP errors
        """
        if not self.session:
            raise ProviderError("HTTP provider not initialized - call initialize() first")
        
        # Build URL
        url = f"{self.base_url}/{path.lstrip('/')}"
        
        # Merge headers
        request_headers = {}
        if headers:
            request_headers.update(headers)
        
        try:
            # Make request
            async with self.session.request(
                method=method.upper(),
                url=url,
                json=data if data else None,
                params=params,
                headers=request_headers
            ) as response:
                
                # Handle different status codes
                if response.status == 401:
                    raise AuthenticationError("Authentication failed (401)")
                elif response.status == 403:
                    raise AuthenticationError("Access forbidden (403)")
                elif response.status >= 500:
                    error_text = await response.text()
                    raise ProviderError(f"Server error ({response.status}): {error_text}")
                elif response.status >= 400:
                    error_text = await response.text()
                    raise ProviderError(f"Client error ({response.status}): {error_text}")
                
                # Parse response
                try:
                    # Try JSON first
                    return await response.json()
                except (json.JSONDecodeError, aiohttp.ContentTypeError):
                    # Fall back to text
                    text = await response.text()
                    return {"data": text, "content_type": response.content_type}
                
        except aiohttp.ClientError as e:
            raise NetworkError(f"Network error: {e}")
        except Exception as e:
            if isinstance(e, (AuthenticationError, ProviderError, NetworkError)):
                raise
            else:
                raise ProviderError(f"Unexpected error: {e}")


class RESTProvider(HTTPProvider):
    """
    REST API provider with automatic endpoint mapping.
    
    Define your REST endpoints as a class attribute and get automatic
    method routing based on HTTP verbs and paths.
    
    Example:
        class UserAPIProvider(RESTProvider):
            base_url = "https://api.example.com"
            
            endpoints = {
                "list_users": {"method": "GET", "path": "/users"},
                "get_user": {"method": "GET", "path": "/users/{id}"},
                "create_user": {"method": "POST", "path": "/users"},
                "update_user": {"method": "PUT", "path": "/users/{id}"},
                "delete_user": {"method": "DELETE", "path": "/users/{id}"}
            }
    """
    
    # Override this in subclasses
    endpoints: Dict[str, Dict[str, str]] = {}
    
    async def execute(self, method: str, **params) -> Dict[str, Any]:
        """
        Automatically route to REST endpoints based on configuration.
        
        Supports path parameters using {param} syntax.
        """
        if method not in self.endpoints:
            available = list(self.endpoints.keys())
            raise ProviderError(f"Unknown method: {method}. Available: {available}")
        
        endpoint_config = self.endpoints[method]
        http_method = endpoint_config["method"]
        path = endpoint_config["path"]
        
        # Replace path parameters
        for param_name, param_value in params.items():
            placeholder = f"{{{param_name}}}"
            if placeholder in path:
                path = path.replace(placeholder, str(param_value))
                params = {k: v for k, v in params.items() if k != param_name}
        
        # Route to appropriate HTTP method
        if http_method.upper() == "GET":
            return await self.get(path, params=params)
        elif http_method.upper() == "POST":
            return await self.post(path, data=params)
        elif http_method.upper() == "PUT":
            return await self.put(path, data=params)
        elif http_method.upper() == "DELETE":
            return await self.delete(path)
        elif http_method.upper() == "PATCH":
            return await self.patch(path, data=params)
        else:
            raise ProviderError(f"Unsupported HTTP method: {http_method}")
    
    def get_supported_methods(self) -> List[str]:
        """Return list of configured endpoints"""
        return list(self.endpoints.keys())


# Usage examples and convenience functions

def create_simple_http_provider(
    base_url: str,
    protocol_id: str,
    endpoints: Dict[str, Dict[str, str]],
    provider_id: Optional[str] = None,
    auth_token: Optional[str] = None,
    **kwargs
) -> RESTProvider:
    """
    Factory function to create a simple REST provider from configuration.
    
    Args:
        base_url: Base URL for the API
        protocol_id: Protocol identifier
        endpoints: Dictionary mapping method names to endpoint configs
        provider_id: Provider identifier (auto-generated if not provided)
        auth_token: Optional authentication token
        **kwargs: Additional provider arguments
    
    Returns:
        Configured RESTProvider instance
    
    Example:
        weather_provider = create_simple_http_provider(
            base_url="https://api.weather.com",
            protocol_id="weather/v1",
            endpoints={
                "get_weather": {"method": "GET", "path": "/current/{city}"},
                "get_forecast": {"method": "GET", "path": "/forecast/{city}"}
            },
            auth_token="my-api-key"
        )
    """
    class DynamicRESTProvider(RESTProvider):
        endpoints = endpoints
    
    provider_id = provider_id or protocol_id.split('/')[0]
    
    return DynamicRESTProvider(
        provider_id=provider_id,
        protocol_id=protocol_id,
        base_url=base_url,
        auth_token=auth_token,
        **kwargs
    )