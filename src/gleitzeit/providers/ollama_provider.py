"""
Ollama Provider - Clean Protocol Implementation
Executes LLM methods using endpoints provided by ResourceManager/OllamaHub
"""

import logging
from typing import Dict, Any, List, Optional, Type, TypeVar
import aiohttp

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.errors import InvalidParameterError, TaskExecutionError

logger = logging.getLogger(__name__)


class OllamaProvider(ProtocolProvider):
    """
    Clean Ollama provider for protocol execution only.
    
    This provider is a pure protocol implementation that executes LLM methods.
    All resource management (discovery, health checks, instance lifecycle) is 
    handled by OllamaHub through the ResourceManager.
    
    Separation of concerns:
    - OllamaHub: Manages Ollama instances (start/stop, health, discovery, load balancing)
    - OllamaProvider: Executes LLM protocols (generate, chat, vision, embeddings)
    """
    
    def __init__(
        self,
        provider_id: str = "ollama",
        protocol_id: str = "llm/v1",
        default_model: str = "llama3.2",
        auto_discover: bool = False,  # Ignored - kept for compatibility
        resource_manager=None,  # Accept resource_manager
        hub=None,  # Accept hub (OllamaHub)
        **kwargs  # Accept and ignore other params for compatibility
    ):
        """
        Initialize Ollama provider
        
        Args:
            provider_id: Unique provider identifier
            protocol_id: Protocol this provider implements
            default_model: Default model to use for requests
            auto_discover: Ignored - discovery is handled by OllamaHub
            resource_manager: Optional ResourceManager for allocation
            hub: Optional OllamaHub for direct hub connection
            **kwargs: Additional arguments for compatibility
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id=protocol_id,
            name="Ollama Provider",
            description="Executes LLM protocols on Ollama instances",
            resource_manager=resource_manager,
            hub=hub
        )
        
        self.default_model = default_model
        self.session = None
        self.default_endpoint = "http://localhost:11434"
    
    async def initialize(self) -> None:
        """Initialize the provider"""
        self.session = aiohttp.ClientSession()
        logger.info(f"Initialized {self.name}")
    
    async def cleanup(self) -> None:
        """Clean up resources"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
    
    async def shutdown(self) -> None:
        """Shutdown the provider (alias for cleanup)"""
        await self.cleanup()
    
    async def health_check(self) -> bool:
        """Check if provider is healthy"""
        if not self.session or self.session.closed:
            return False
        
        try:
            # Just check if we can reach the default endpoint
            async with self.session.get(
                f"{self.default_endpoint}/api/tags",
                timeout=aiohttp.ClientTimeout(total=2)
            ) as response:
                return response.status == 200
        except:
            # Provider is healthy even if no Ollama instance is running
            # The hub will handle instance availability
            return True
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle a request - main entry point for protocol execution
        
        Args:
            method: The method to execute
            params: Method parameters
            
        Returns:
            Response dictionary
        """
        return await self.execute(method, params)
    
    def can_handle(self, method: str) -> bool:
        """Check if this provider can handle a method"""
        supported = self.get_supported_methods()
        return method in supported
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return [
            "llm/generate",
            "llm/complete",  # Alias for generate
            "llm/chat",
            "llm/vision", 
            "llm/embeddings",
            "llm/list_models"
        ]
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a method with the given parameters.
        
        Uses the hub/resource manager from base class to allocate resources.
        Falls back to default endpoint if no resource management is configured.
        
        Args:
            method: Method to execute
            params: Method parameters
            
        Returns:
            Method execution result
        """
        if not self.session:
            await self.initialize()
        
        # Get model from params to determine capabilities
        model = params.get('model', self.default_model)
        
        # Try to allocate a resource using base class method
        allocated_resource = await self.allocate_resource(
            capabilities={model} if model else None,
            strategy='least_loaded'
        )
        
        if allocated_resource:
            endpoint = allocated_resource.endpoint
            logger.debug(f"Using allocated Ollama resource at {endpoint}")
        else:
            # No resource allocated, use default or provided endpoint
            endpoint = params.get('endpoint', self.default_endpoint)
            logger.debug(f"Using endpoint {endpoint}")
        
        # Route to appropriate method handler
        method_map = {
            "llm/generate": self._generate,
            "llm/complete": self._generate,  # Alias
            "llm/chat": self._chat,
            "llm/vision": self._vision,
            "llm/embeddings": self._embeddings,
            "llm/list_models": self._list_models
        }
        
        handler = method_map.get(method)
        if not handler:
            raise InvalidParameterError(
                param_name="method",
                reason=f"Unsupported method: {method}"
            )
        
        # Execute the method
        result = await handler(endpoint, params)
        
        # Note: Resource release should be handled by the hub/resource manager
        # when the request completes or times out
        
        return result
    
    async def _generate(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate text completion"""
        model = params.get('model', self.default_model)
        prompt = params.get('prompt', '')
        
        if not prompt:
            raise InvalidParameterError(param_name='prompt', reason='Prompt is required')
        
        try:
            async with self.session.post(
                f"{endpoint}/api/generate",
                json={
                    'model': model,
                    'prompt': prompt,
                    'stream': False,
                    'temperature': params.get('temperature', 0.7),
                    'top_p': params.get('top_p', 0.9),
                    'max_tokens': params.get('max_tokens', 100)
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        'success': True,
                        'response': data.get('response', ''),
                        'model': model,
                        'done': True
                    }
                else:
                    error = await response.text()
                    raise TaskExecutionError(message=f"Generation failed: {error}")
                    
        except aiohttp.ClientError as e:
            raise TaskExecutionError(message=f"Connection error: {str(e)}")
    
    async def _chat(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Chat completion"""
        model = params.get('model', self.default_model)
        messages = params.get('messages', [])
        
        if not messages:
            raise InvalidParameterError(param_name='messages', reason='Messages are required')
        
        try:
            async with self.session.post(
                f"{endpoint}/api/chat",
                json={
                    'model': model,
                    'messages': messages,
                    'stream': False,
                    'temperature': params.get('temperature', 0.7),
                    'top_p': params.get('top_p', 0.9)
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    message = data.get('message', {})
                    return {
                        'success': True,
                        'response': message.get('content', ''),
                        'message': message,
                        'model': model,
                        'done': True
                    }
                else:
                    error = await response.text()
                    raise TaskExecutionError(message=f"Chat failed: {error}")
                    
        except aiohttp.ClientError as e:
            raise TaskExecutionError(message=f"Connection error: {str(e)}")
    
    async def _vision(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Vision analysis"""
        model = params.get('model', 'llava:latest')
        images = params.get('images', [])
        prompt = params.get('prompt', 'What is in this image?')
        
        if not images:
            raise InvalidParameterError(param_name='images', reason='At least one image required')
        
        try:
            async with self.session.post(
                f"{endpoint}/api/chat",
                json={
                    'model': model,
                    'messages': [{
                        'role': 'user',
                        'content': prompt,
                        'images': images
                    }],
                    'stream': False
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    message = data.get('message', {})
                    return {
                        'success': True,
                        'response': message.get('content', ''),
                        'model': model,
                        'done': True
                    }
                else:
                    error = await response.text()
                    raise TaskExecutionError(message=f"Vision analysis failed: {error}")
                    
        except aiohttp.ClientError as e:
            raise TaskExecutionError(message=f"Connection error: {str(e)}")
    
    async def _embeddings(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate embeddings"""
        model = params.get('model', 'nomic-embed-text')
        text = params.get('text', '')
        
        if not text:
            raise InvalidParameterError(param_name='text', reason='Text is required')
        
        try:
            async with self.session.post(
                f"{endpoint}/api/embeddings",
                json={
                    'model': model,
                    'prompt': text
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        'success': True,
                        'embedding': data.get('embedding', []),
                        'model': model
                    }
                else:
                    error = await response.text()
                    raise TaskExecutionError(message=f"Embeddings failed: {error}")
                    
        except aiohttp.ClientError as e:
            raise TaskExecutionError(message=f"Connection error: {str(e)}")
    
    async def _list_models(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """List available models"""
        try:
            async with self.session.get(f"{endpoint}/api/tags") as response:
                if response.status == 200:
                    data = await response.json()
                    models = [model['name'] for model in data.get('models', [])]
                    return {
                        'success': True,
                        'models': models
                    }
                else:
                    error = await response.text()
                    raise TaskExecutionError(message=f"List models failed: {error}")
                    
        except aiohttp.ClientError as e:
            raise TaskExecutionError(message=f"Connection error: {str(e)}")
    
    async def __aenter__(self) -> 'OllamaProvider':
        """Async context manager entry"""
        await self.initialize()
        return self
    
    async def __aexit__(self, 
                         exc_type: Optional[Type[BaseException]], 
                         exc_val: Optional[BaseException], 
                         exc_tb: Optional[Any]) -> None:
        """Async context manager exit"""
        await self.cleanup()