"""
Configuration-Based Providers

Create providers from YAML/JSON configuration files.
Zero code required - just define endpoints and transformations.
"""

import yaml
import json
import re
import logging
from typing import Dict, Any, List, Optional, Union
from pathlib import Path
import asyncio
import aiohttp
from jinja2 import Template, Environment, BaseLoader

from .simple import SimpleProvider
from .discovery import discover_service
from gleitzeit.core.errors import ProviderError, TaskValidationError as ValidationError

logger = logging.getLogger(__name__)


class ConfigProvider(SimpleProvider):
    """
    Provider that loads configuration from YAML or JSON files.
    
    Supports:
    - HTTP endpoint definitions
    - Request/response transformations
    - Parameter validation
    - Service discovery integration
    - Template-based dynamic URLs
    
    Example config file (weather-provider.yaml):
    ```yaml
    provider:
      id: weather
      protocol: weather/v1
      type: http
      base_url: https://api.weather.com
      discovery:
        enabled: true
        service_type: weather
        port_range: [8000, 8100]
      
    auth:
      type: bearer
      token: ${WEATHER_API_KEY}
      
    methods:
      get_weather:
        endpoint: /current
        method: GET
        params:
          - name: city
            type: string
            required: true
            description: City name
        headers:
          Accept: application/json
        transform_response: |
          return {
            "temperature": response["main"]["temp"],
            "condition": response["weather"][0]["main"],
            "city": response["name"]
          }
      
      get_forecast:
        endpoint: /forecast
        method: GET
        params:
          - name: city
            type: string
            required: true
          - name: days
            type: integer
            default: 7
            min: 1
            max: 14
        transform_response: |
          forecast_data = []
          for item in response["list"][:days]:
            forecast_data.append({
              "date": item["dt_txt"],
              "temp": item["main"]["temp"],
              "condition": item["weather"][0]["main"]
            })
          return {"forecast": forecast_data, "city": city}
    ```
    """
    
    def __init__(self, config_path: Union[str, Path, Dict[str, Any]], **kwargs):
        """
        Initialize provider from configuration file or dictionary.
        
        Args:
            config_path: Path to YAML/JSON config file or config dictionary
            **kwargs: Additional provider arguments
        """
        # Load configuration
        if isinstance(config_path, (str, Path)):
            self.config_path = Path(config_path)
            self.config = self._load_config_file(self.config_path)
        elif isinstance(config_path, dict):
            self.config_path = None
            self.config = config_path
        else:
            raise ValueError("config_path must be a file path or dictionary")
        
        # Extract provider configuration
        provider_config = self.config.get('provider', {})
        
        # Initialize parent with config values
        super().__init__(
            provider_id=provider_config.get('id', 'config_provider'),
            protocol_id=provider_config.get('protocol', 'config/v1'),
            name=provider_config.get('name'),
            description=provider_config.get('description'),
            version=provider_config.get('version', '1.0.0'),
            **kwargs
        )
        
        # HTTP configuration
        self.base_url = provider_config.get('base_url', 'http://localhost:8000')
        self.provider_type = provider_config.get('type', 'http').lower()
        
        # Authentication configuration
        self.auth_config = self.config.get('auth', {})
        
        # Method definitions
        self.methods_config = self.config.get('methods', {})
        
        # Discovery configuration
        self.discovery_config = self.config.get('discovery', {})
        
        # HTTP session
        self.session = None
        
        # Template environment for dynamic values
        self.template_env = Environment(loader=BaseLoader())
        
        # Discovered service info
        self.discovered_service = None
    
    def _load_config_file(self, config_path: Path) -> Dict[str, Any]:
        """Load configuration from YAML or JSON file"""
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        config_text = config_path.read_text()
        
        # Expand environment variables
        config_text = self._expand_environment_variables(config_text)
        
        try:
            if config_path.suffix.lower() in ['.yaml', '.yml']:
                return yaml.safe_load(config_text)
            elif config_path.suffix.lower() == '.json':
                return json.loads(config_text)
            else:
                # Try YAML first, then JSON
                try:
                    return yaml.safe_load(config_text)
                except yaml.YAMLError:
                    return json.loads(config_text)
        except Exception as e:
            raise ProviderError(f"Failed to parse configuration file {config_path}: {e}")
    
    def _expand_environment_variables(self, text: str) -> str:
        """Expand ${VAR} and ${VAR:-default} environment variables"""
        import os
        
        def replace_env_var(match):
            var_expr = match.group(1)
            
            if ':-' in var_expr:
                # Handle default values: ${VAR:-default}
                var_name, default = var_expr.split(':-', 1)
                return os.getenv(var_name, default)
            else:
                # Simple variable: ${VAR}
                return os.getenv(var_expr, '')
        
        # Replace ${...} patterns
        return re.sub(r'\$\{([^}]+)\}', replace_env_var, text)
    
    async def initialize(self) -> None:
        """Initialize provider with service discovery and HTTP session"""
        await super().initialize()
        
        # Service discovery if enabled
        if self.discovery_config.get('enabled', False):
            service_type = self.discovery_config.get('service_type', 'http')
            host = self.discovery_config.get('host', 'localhost')
            port_range = self.discovery_config.get('port_range')
            
            if port_range and len(port_range) == 2:
                port_range = tuple(port_range)
            
            logger.info(f"Discovering {service_type} service...")
            self.discovered_service = await discover_service(service_type, host, port_range)
            
            if self.discovered_service:
                self.base_url = self.discovered_service.url
                logger.info(f"Using discovered service: {self.base_url}")
            else:
                logger.warning(f"Service discovery failed, using configured URL: {self.base_url}")
        
        # Initialize HTTP session
        headers = self._build_default_headers()
        timeout = aiohttp.ClientTimeout(total=30)
        
        self.session = aiohttp.ClientSession(
            headers=headers,
            timeout=timeout
        )
        
        logger.info(f"Config provider initialized: {self.base_url}")
    
    async def shutdown(self) -> None:
        """Clean up resources"""
        if self.session:
            await self.session.close()
            self.session = None
        await super().shutdown()
    
    def _build_default_headers(self) -> Dict[str, str]:
        """Build default HTTP headers including authentication"""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Gleitzeit-ConfigProvider/1.0"
        }
        
        # Add authentication headers
        auth_type = self.auth_config.get('type', '').lower()
        
        if auth_type == 'bearer':
            token = self.auth_config.get('token')
            if token:
                headers['Authorization'] = f"Bearer {token}"
        elif auth_type == 'api_key':
            key = self.auth_config.get('key')
            header_name = self.auth_config.get('header', 'X-API-Key')
            if key:
                headers[header_name] = key
        elif auth_type == 'basic':
            username = self.auth_config.get('username', '')
            password = self.auth_config.get('password', '')
            if username or password:
                import base64
                credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
                headers['Authorization'] = f"Basic {credentials}"
        
        return headers
    
    async def execute(self, method: str, **params) -> Any:
        """Execute a method based on configuration"""
        if method not in self.methods_config:
            available = list(self.methods_config.keys())
            raise ProviderError(f"Unknown method: {method}. Available methods: {available}")
        
        method_config = self.methods_config[method]
        
        # Validate parameters
        validated_params = self._validate_parameters(method, params, method_config)
        
        # Build request
        request_data = self._build_request(method_config, validated_params)
        
        # Make HTTP request
        response_data = await self._make_http_request(request_data)
        
        # Transform response
        result = self._transform_response(method_config, response_data, validated_params)
        
        return result
    
    def _validate_parameters(
        self, 
        method: str, 
        params: Dict[str, Any], 
        method_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate and process parameters according to method configuration"""
        param_configs = method_config.get('params', [])
        validated = {}
        
        # Process each configured parameter
        for param_config in param_configs:
            param_name = param_config['name']
            param_type = param_config.get('type', 'string')
            required = param_config.get('required', False)
            default = param_config.get('default')
            
            # Check if parameter is provided
            if param_name in params:
                value = params[param_name]
            elif default is not None:
                value = default
            elif required:
                raise ValidationError(f"Required parameter '{param_name}' missing for method '{method}'")
            else:
                continue
            
            # Type validation and conversion
            try:
                if param_type == 'integer':
                    value = int(value)
                    # Check range constraints
                    if 'min' in param_config and value < param_config['min']:
                        raise ValidationError(f"Parameter '{param_name}' must be >= {param_config['min']}")
                    if 'max' in param_config and value > param_config['max']:
                        raise ValidationError(f"Parameter '{param_name}' must be <= {param_config['max']}")
                elif param_type == 'number':
                    value = float(value)
                elif param_type == 'boolean':
                    if isinstance(value, str):
                        value = value.lower() in ('true', '1', 'yes', 'on')
                    else:
                        value = bool(value)
                elif param_type == 'string':
                    value = str(value)
                    # Check length constraints
                    if 'min_length' in param_config and len(value) < param_config['min_length']:
                        raise ValidationError(f"Parameter '{param_name}' must be at least {param_config['min_length']} characters")
                    if 'max_length' in param_config and len(value) > param_config['max_length']:
                        raise ValidationError(f"Parameter '{param_name}' must be at most {param_config['max_length']} characters")
                elif param_type == 'array':
                    if not isinstance(value, list):
                        raise ValidationError(f"Parameter '{param_name}' must be an array")
                
                validated[param_name] = value
                
            except (ValueError, TypeError) as e:
                raise ValidationError(f"Parameter '{param_name}' type error: {e}")
        
        # Add any additional parameters not in config (for flexibility)
        for param_name, value in params.items():
            if param_name not in validated:
                validated[param_name] = value
        
        return validated
    
    def _build_request(
        self, 
        method_config: Dict[str, Any], 
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build HTTP request from method configuration and parameters"""
        
        # Build URL
        endpoint = method_config.get('endpoint', '/')
        
        # Template substitution in endpoint (e.g., /users/{user_id})
        endpoint_template = self.template_env.from_string(endpoint)
        endpoint = endpoint_template.render(**params)
        
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        # HTTP method
        http_method = method_config.get('method', 'GET').upper()
        
        # Headers
        headers = {}
        if 'headers' in method_config:
            headers.update(method_config['headers'])
        
        # Request body and query parameters
        json_data = None
        query_params = {}
        
        if http_method in ['GET', 'DELETE']:
            # Use query parameters
            query_params = params.copy()
        else:
            # Use request body
            body_config = method_config.get('body', {})
            if body_config.get('type') == 'form':
                # Form data (not implemented in this example)
                json_data = params
            else:
                # JSON body (default)
                json_data = params
        
        return {
            'method': http_method,
            'url': url,
            'headers': headers,
            'json': json_data,
            'params': query_params
        }
    
    async def _make_http_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Make HTTP request and return response data"""
        if not self.session:
            raise ProviderError("HTTP session not initialized")
        
        try:
            async with self.session.request(
                method=request_data['method'],
                url=request_data['url'],
                headers=request_data.get('headers', {}),
                json=request_data.get('json'),
                params=request_data.get('params')
            ) as response:
                
                # Check for HTTP errors
                if response.status >= 400:
                    error_text = await response.text()
                    raise ProviderError(f"HTTP {response.status}: {error_text}")
                
                # Parse response
                try:
                    return await response.json()
                except aiohttp.ContentTypeError:
                    # Not JSON, return as text
                    text = await response.text()
                    return {"data": text, "content_type": response.content_type}
                
        except aiohttp.ClientError as e:
            raise ProviderError(f"HTTP request failed: {e}")
    
    def _transform_response(
        self, 
        method_config: Dict[str, Any], 
        response_data: Dict[str, Any], 
        params: Dict[str, Any]
    ) -> Any:
        """Transform response data according to method configuration"""
        
        # Check for custom transformation script
        transform_script = method_config.get('transform_response')
        if transform_script:
            return self._execute_transform_script(transform_script, response_data, params)
        
        # Check for response mapping
        response_map = method_config.get('response_map')
        if response_map:
            return self._apply_response_mapping(response_map, response_data)
        
        # No transformation configured, return raw response
        return response_data
    
    def _execute_transform_script(
        self, 
        script: str, 
        response: Dict[str, Any], 
        params: Dict[str, Any]
    ) -> Any:
        """Execute transformation script in sandboxed environment"""
        
        # Create safe execution environment
        safe_globals = {
            '__builtins__': {
                'len': len,
                'str': str,
                'int': int,
                'float': float,
                'bool': bool,
                'list': list,
                'dict': dict,
                'range': range,
                'enumerate': enumerate,
                'zip': zip,
                'min': min,
                'max': max,
                'sum': sum,
                'sorted': sorted,
                'round': round
            },
            'response': response,
            'params': params,
            **params  # Make parameters available as variables
        }
        
        local_vars = {}
        
        try:
            # Handle scripts with return statements by wrapping in a function
            if 'return' in script:
                # Wrap the script in a function to allow return statements
                # Indent the script properly
                indented_script = '\n'.join('    ' + line for line in script.split('\n'))
                function_script = f"""
def transform():
{indented_script}

result = transform()
"""
                exec(function_script, safe_globals, local_vars)
                return local_vars.get('result', response)
            else:
                # Execute script normally
                exec(script, safe_globals, local_vars)
                
                # Look for result in local variables
                if 'result' in local_vars:
                    return local_vars['result']
                
                # If no explicit result, return modified response
                return local_vars.get('response', response)
            
        except Exception as e:
            raise ProviderError(f"Response transformation failed: {e}")
    
    def _apply_response_mapping(
        self, 
        response_map: Dict[str, str], 
        response_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply response field mapping"""
        result = {}
        
        for output_key, input_path in response_map.items():
            try:
                value = self._extract_value_by_path(response_data, input_path)
                result[output_key] = value
            except Exception as e:
                logger.warning(f"Failed to extract '{input_path}' for '{output_key}': {e}")
                result[output_key] = None
        
        return result
    
    def _extract_value_by_path(self, data: Any, path: str) -> Any:
        """Extract value from data using dot-notation path"""
        current = data
        
        for part in path.split('.'):
            if '[' in part and ']' in part:
                # Handle array indexing like "items[0]" or "data[*]"
                key, index_part = part.split('[', 1)
                index_part = index_part.rstrip(']')
                
                if key:
                    current = current[key]
                
                if index_part == '*':
                    # Return all items
                    if isinstance(current, list):
                        return current
                    elif isinstance(current, dict):
                        return list(current.values())
                else:
                    # Specific index
                    index = int(index_part)
                    current = current[index]
            else:
                current = current[part]
        
        return current
    
    def get_supported_methods(self) -> List[str]:
        """Return list of methods defined in configuration"""
        return list(self.methods_config.keys())
    
    def get_config_info(self) -> Dict[str, Any]:
        """Get information about the current configuration"""
        return {
            "config_path": str(self.config_path) if self.config_path else None,
            "provider_id": self.provider_id,
            "protocol_id": self.protocol_id,
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "discovered_service": {
                "url": self.discovered_service.url,
                "service_type": self.discovered_service.service_type,
                "version": self.discovered_service.version,
                "capabilities": self.discovered_service.capabilities
            } if self.discovered_service else None,
            "methods": list(self.methods_config.keys()),
            "auth_configured": bool(self.auth_config),
            "discovery_enabled": self.discovery_config.get('enabled', False)
        }


# Convenience functions
def load_config_provider(config_path: Union[str, Path]) -> ConfigProvider:
    """
    Load a provider from configuration file.
    
    Args:
        config_path: Path to YAML or JSON configuration file
        
    Returns:
        Configured ConfigProvider instance
    
    Example:
        provider = load_config_provider("weather-provider.yaml")
        await provider.initialize()
        result = await provider.execute("get_weather", city="London")
    """
    return ConfigProvider(config_path)


def create_config_provider(config: Dict[str, Any]) -> ConfigProvider:
    """
    Create a provider from configuration dictionary.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Configured ConfigProvider instance
    
    Example:
        config = {
            "provider": {"id": "test", "protocol": "test/v1", "type": "http"},
            "methods": {
                "echo": {
                    "endpoint": "/echo",
                    "method": "POST"
                }
            }
        }
        provider = create_config_provider(config)
    """
    return ConfigProvider(config)