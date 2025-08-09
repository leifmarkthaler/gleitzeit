"""
Socket.IO Provider Client for CLI

Dedicated client for interacting with the providers namespace
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
import socketio

logger = logging.getLogger(__name__)


class ProviderSocketClient:
    """
    Socket.IO client specifically for the /providers namespace
    
    Used by CLI commands to interact with the provider manager
    """
    
    def __init__(self, server_url: str = "http://localhost:8000"):
        """
        Initialize provider Socket.IO client
        
        Args:
            server_url: Socket.IO server URL
        """
        self.server_url = server_url
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=3,
            reconnection_delay=1
        )
        self.connected = False
        
        # Setup event handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.on('connect', namespace='/providers')
        async def on_connect():
            self.connected = True
            logger.debug("Connected to providers namespace")
        
        @self.sio.on('disconnect', namespace='/providers') 
        async def on_disconnect():
            self.connected = False
            logger.debug("Disconnected from providers namespace")
        
        @self.sio.on('connect_error', namespace='/providers')
        async def on_connect_error(data):
            logger.error(f"Connection error: {data}")
    
    async def connect(self) -> bool:
        """
        Connect to Socket.IO server
        
        Returns:
            True if connection successful
        """
        try:
            await self.sio.connect(
                self.server_url, 
                namespaces=['/providers']
            )
            
            # Wait a moment for connection to establish
            await asyncio.sleep(0.5)
            
            return self.connected
            
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from Socket.IO server"""
        if self.connected:
            await self.sio.disconnect()
            self.connected = False
    
    async def call_with_timeout(
        self, 
        event: str, 
        data: Dict[str, Any] = None, 
        timeout: int = 10
    ) -> Dict[str, Any]:
        """
        Make a Socket.IO call with timeout handling
        
        Args:
            event: Event name
            data: Event data
            timeout: Timeout in seconds
            
        Returns:
            Response data
        """
        if not self.connected:
            raise ConnectionError("Not connected to server")
        
        try:
            response = await self.sio.call(
                event,
                data or {},
                namespace='/providers',
                timeout=timeout
            )
            return response
            
        except asyncio.TimeoutError:
            raise TimeoutError(f"Request timed out after {timeout} seconds")
        except Exception as e:
            raise ConnectionError(f"Socket.IO call failed: {e}")
    
    async def get_all_providers(self) -> Dict[str, Any]:
        """
        Get all connected providers
        
        Returns:
            Dictionary of providers and their information
        """
        # The provider manager doesn't have a direct "list all providers" event
        # So we'll get models first, then get provider details for each
        models_response = await self.call_with_timeout('provider:list_models')
        
        if not models_response.get('success'):
            raise Exception(f"Failed to get models: {models_response.get('error')}")
        
        models = models_response.get('models', {})
        
        # Get unique provider names
        provider_names = set(models.values())
        
        providers = {}
        
        # Get details for each provider by querying capabilities
        for provider_name in provider_names:
            try:
                caps_response = await self.call_with_timeout(
                    'provider:capabilities',
                    {'capability': 'text'}  # Use a common capability to find providers
                )
                
                if caps_response.get('success'):
                    provider_list = caps_response.get('providers', [])
                    
                    # Find this provider in the list
                    for provider_info in provider_list:
                        if provider_info.get('name') == provider_name:
                            providers[provider_name] = {
                                'name': provider_name,
                                'type': provider_info.get('type', 'unknown'),
                                'models': [m for m, p in models.items() if p == provider_name],
                                'capabilities': [],  # Will be filled by separate call
                                'connected': provider_info.get('connected', True),
                                'description': f"Provider: {provider_name}"
                            }
                            break
                    
                    if provider_name not in providers:
                        # Provider not found in capabilities, create basic entry
                        providers[provider_name] = {
                            'name': provider_name,
                            'type': 'unknown',
                            'models': [m for m, p in models.items() if p == provider_name],
                            'capabilities': [],
                            'connected': True,
                            'description': f"Provider: {provider_name}"
                        }
                        
            except Exception as e:
                logger.warning(f"Failed to get details for provider {provider_name}: {e}")
                # Create basic entry
                providers[provider_name] = {
                    'name': provider_name,
                    'type': 'unknown', 
                    'models': [m for m, p in models.items() if p == provider_name],
                    'capabilities': [],
                    'connected': True,
                    'description': f"Provider: {provider_name}"
                }
        
        return providers
    
    async def get_all_models(self) -> Dict[str, str]:
        """
        Get all available models
        
        Returns:
            Dictionary mapping model names to provider names
        """
        response = await self.call_with_timeout('provider:list_models')
        
        if not response.get('success'):
            raise Exception(f"Failed to get models: {response.get('error')}")
        
        return response.get('models', {})
    
    async def get_all_capabilities(self) -> List[str]:
        """
        Get all available capabilities
        
        Returns:
            List of capability names
        """
        response = await self.call_with_timeout('provider:capabilities')
        
        if not response.get('success'):
            raise Exception(f"Failed to get capabilities: {response.get('error')}")
        
        return response.get('capabilities', [])
    
    async def get_providers_by_capability(self, capability: str) -> List[Dict[str, Any]]:
        """
        Get providers that support a specific capability
        
        Args:
            capability: Capability name
            
        Returns:
            List of provider information
        """
        response = await self.call_with_timeout(
            'provider:capabilities',
            {'capability': capability}
        )
        
        if not response.get('success'):
            raise Exception(f"Failed to get providers for capability '{capability}': {response.get('error')}")
        
        return response.get('providers', [])
    
    async def invoke_provider(
        self,
        provider_name: str,
        method: str,
        arguments: Dict[str, Any],
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Invoke a method on a provider
        
        Args:
            provider_name: Name of the provider
            method: Method to invoke
            arguments: Method arguments
            timeout: Timeout in seconds
            
        Returns:
            Invocation result
        """
        data = {
            'provider': provider_name,
            'method': method,
            'args': arguments,
            'timeout': timeout
        }
        
        response = await self.call_with_timeout(
            'provider:invoke',
            data,
            timeout=timeout + 5
        )
        
        if not response.get('success'):
            raise Exception(f"Provider invocation failed: {response.get('error')}")
        
        return response.get('result')
    
    async def get_provider_tools(self, provider_name: str) -> List[Dict[str, Any]]:
        """
        Get available tools from a provider
        
        Args:
            provider_name: Provider name
            
        Returns:
            List of tool information
        """
        response = await self.call_with_timeout(
            'provider:list_tools',
            {'provider': provider_name}
        )
        
        if not response.get('success'):
            raise Exception(f"Failed to get tools from provider '{provider_name}': {response.get('error')}")
        
        return response.get('tools', [])
    
    # Context manager support
    async def __aenter__(self):
        """Async context manager entry"""
        success = await self.connect()
        if not success:
            raise ConnectionError("Failed to connect to provider server")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect()