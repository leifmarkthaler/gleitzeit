"""
Refactored Ollama Provider - Uses OllamaHub for resource management

This is a proof-of-concept showing how providers can be refactored
to use the new hub architecture while maintaining protocol compatibility.
"""

import logging
from typing import Dict, Any, Optional, List
import json

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.hub.ollama_hub import OllamaHub, OllamaConfig
from gleitzeit.hub.base import ResourceStatus
from gleitzeit.core.errors import (
    ProviderError, MethodNotSupportedError, InvalidParameterError,
    ProviderNotAvailableError, TaskExecutionError
)

logger = logging.getLogger(__name__)


class RefactoredOllamaProvider(ProtocolProvider):
    """
    Refactored Ollama provider that uses OllamaHub for resource management
    
    This demonstrates the layered architecture where:
    - Provider handles protocol-specific logic (LLM methods)
    - Hub handles resource management (instances, health, metrics)
    - Clear separation of concerns
    """
    
    def __init__(
        self,
        provider_id: str,
        hub: Optional[OllamaHub] = None,
        instances: Optional[List[Dict[str, Any]]] = None,
        auto_discover: bool = True,
        default_model: str = "llama3.2",
        timeout: int = 60
    ):
        """
        Initialize the refactored Ollama provider
        
        Args:
            provider_id: Unique provider identifier
            hub: Optional existing OllamaHub to use
            instances: Optional list of instance configs if creating new hub
            auto_discover: Auto-discover local Ollama instances
            default_model: Default model to use
            timeout: Request timeout in seconds
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id="llm/v1",
            name="Refactored Ollama Provider",
            description="Ollama provider using hub architecture"
        )
        
        self.timeout = timeout
        self.default_model = default_model
        
        # Use provided hub or create new one
        if hub:
            self.hub = hub
            self.owns_hub = False
        else:
            self.hub = OllamaHub(
                hub_id=f"{provider_id}-hub",
                auto_discover=auto_discover
            )
            self.owns_hub = True
            
            # Register provided instances
            if instances:
                self._instances_to_register = instances
            else:
                self._instances_to_register = []
    
    async def initialize(self):
        """Initialize the provider and hub"""
        try:
            # Start hub if we own it
            if self.owns_hub:
                await self.hub.start()
                
                # Register any provided instances
                for inst_config in self._instances_to_register:
                    config = OllamaConfig(
                        host=inst_config.get('host', '127.0.0.1'),
                        port=inst_config.get('port', 11434),
                        models=inst_config.get('models', []),
                        max_concurrent=inst_config.get('max_concurrent', 4)
                    )
                    await self.hub.start_instance(config)
            
            # Wait for at least one healthy instance
            import asyncio
            for _ in range(10):  # Try for 10 seconds
                instances = await self.hub.list_instances(status=ResourceStatus.HEALTHY)
                if instances:
                    break
                await asyncio.sleep(1)
            
            if not instances:
                raise ProviderNotAvailableError(
                    "No healthy Ollama instances available",
                    provider_id=self.provider_id
                )
            
            logger.info(
                f"✅ Refactored Ollama provider initialized with "
                f"{len(instances)} healthy instance(s)"
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize provider: {e}")
            raise ProviderError(f"Initialization failed: {e}")
    
    async def shutdown(self):
        """Shutdown the provider and optionally the hub"""
        try:
            # Stop hub if we own it
            if self.owns_hub and self.hub:
                await self.hub.stop()
                
            logger.info("Provider shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an LLM method using hub-managed instances
        
        The provider focuses on protocol-specific logic while
        the hub handles instance selection and health.
        """
        # Map protocol methods to implementations
        method_map = {
            "llm/generate": self._generate,
            "llm/chat": self._chat,
            "llm/embeddings": self._embeddings,
            "llm/list_models": self._list_models
        }
        
        handler = method_map.get(method)
        if not handler:
            raise MethodNotSupportedError(
                f"Method {method} not supported",
                method=method,
                supported_methods=list(method_map.keys())
            )
        
        return await handler(params)
    
    async def _generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle text generation"""
        model = params.get('model', self.default_model)
        prompt = params.get('prompt', '')
        
        if not prompt:
            raise InvalidParameterError("Prompt is required", parameter='prompt')
        
        # Get instance from hub based on model
        instance = await self.hub.get_instance_for_model(
            model_name=model,
            strategy=params.get('load_balancing_strategy', 'least_loaded')
        )
        
        if not instance:
            # Try to ensure model on any available instance
            instances = await self.hub.list_instances(status=ResourceStatus.HEALTHY)
            if instances:
                instance = instances[0]
                success = await self.hub.ensure_model(instance.id, model)
                if not success:
                    raise ProviderError(f"Failed to load model {model}")
            else:
                raise ProviderNotAvailableError("No instances available")
        
        # Execute on the selected instance
        try:
            result = await self.hub.execute_on_instance(
                instance_id=instance.id,
                method='generate',
                params={
                    'model': model,
                    'prompt': prompt,
                    'temperature': params.get('temperature', 0.7),
                    'max_tokens': params.get('max_tokens'),
                    'stream': False
                }
            )
            
            return {
                'success': True,
                'response': result.get('response', ''),
                'model': model,
                'instance_id': instance.id,
                'metrics': {
                    'response_time': instance.metrics.avg_response_time_ms,
                    'instance_load': instance.metrics.active_connections
                }
            }
            
        except Exception as e:
            logger.error(f"Generation failed on {instance.id}: {e}")
            raise TaskExecutionError(f"Generation failed: {e}")
    
    async def _chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle chat completion"""
        model = params.get('model', self.default_model)
        messages = params.get('messages', [])
        
        if not messages:
            raise InvalidParameterError("Messages are required", parameter='messages')
        
        # Get instance from hub
        instance = await self.hub.get_instance_for_model(
            model_name=model,
            strategy=params.get('load_balancing_strategy', 'least_loaded')
        )
        
        if not instance:
            raise ProviderNotAvailableError(f"No instance available for model {model}")
        
        # Execute chat
        try:
            result = await self.hub.execute_on_instance(
                instance_id=instance.id,
                method='chat',
                params={
                    'model': model,
                    'messages': messages,
                    'temperature': params.get('temperature', 0.7),
                    'stream': False
                }
            )
            
            return {
                'success': True,
                'message': result.get('message', {}),
                'model': model,
                'instance_id': instance.id
            }
            
        except Exception as e:
            logger.error(f"Chat failed on {instance.id}: {e}")
            raise TaskExecutionError(f"Chat failed: {e}")
    
    async def _embeddings(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle embeddings generation"""
        model = params.get('model', 'nomic-embed-text')
        text = params.get('text', '')
        
        if not text:
            raise InvalidParameterError("Text is required", parameter='text')
        
        # Get instance from hub
        instance = await self.hub.get_instance_for_model(
            model_name=model,
            strategy='least_loaded'
        )
        
        if not instance:
            raise ProviderNotAvailableError(f"No instance available for model {model}")
        
        # Generate embeddings
        try:
            result = await self.hub.execute_on_instance(
                instance_id=instance.id,
                method='embeddings',
                params={
                    'model': model,
                    'prompt': text
                }
            )
            
            return {
                'success': True,
                'embedding': result.get('embedding', []),
                'model': model,
                'instance_id': instance.id
            }
            
        except Exception as e:
            logger.error(f"Embeddings failed on {instance.id}: {e}")
            raise TaskExecutionError(f"Embeddings failed: {e}")
    
    async def _list_models(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List available models across all instances"""
        # Get model distribution from hub
        model_distribution = await self.hub.get_model_distribution()
        
        # Get instance status
        instances = await self.hub.list_instances()
        
        return {
            'success': True,
            'models': list(model_distribution.keys()),
            'model_distribution': model_distribution,
            'instances': [
                {
                    'id': inst.id,
                    'endpoint': inst.endpoint,
                    'status': inst.status.value,
                    'models': list(inst.capabilities)
                }
                for inst in instances
            ]
        }
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle JSON-RPC style requests"""
        method = request.get('method')
        params = request.get('params', {})
        
        try:
            result = await self.execute(method, params)
            return {
                'success': True,
                'result': result
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def get_status(self) -> Dict[str, Any]:
        """Get provider status including hub metrics"""
        hub_status = await self.hub.get_status()
        hub_metrics = await self.hub.get_metrics_summary()
        
        return {
            'provider_id': self.provider_id,
            'protocol': self.protocol_id,
            'hub_status': hub_status,
            'metrics': hub_metrics,
            'capabilities': {
                'methods': ['llm/generate', 'llm/chat', 'llm/embeddings', 'llm/list_models'],
                'load_balancing': True,
                'auto_discovery': self.hub.auto_discover,
                'health_monitoring': True,
                'model_management': True
            }
        }


# Example usage
async def example_usage():
    """Example of using the refactored provider"""
    
    # Option 1: Let provider manage its own hub with auto-discovery
    provider = RefactoredOllamaProvider(
        provider_id="ollama-refactored",
        auto_discover=True
    )
    
    # Option 2: Use existing hub (shared resource management)
    # from gleitzeit.hub import OllamaHub
    # shared_hub = OllamaHub("shared-ollama-hub")
    # await shared_hub.start()
    # provider = RefactoredOllamaProvider(
    #     provider_id="ollama-refactored",
    #     hub=shared_hub
    # )
    
    # Initialize
    await provider.initialize()
    
    # Use the provider
    result = await provider.execute(
        method="llm/generate",
        params={
            "model": "llama3.2",
            "prompt": "Hello, how are you?",
            "temperature": 0.7
        }
    )
    
    print(f"Response: {result['response']}")
    print(f"Used instance: {result['instance_id']}")
    
    # Get status
    status = await provider.get_status()
    print(f"Provider status: {json.dumps(status, indent=2)}")
    
    # Cleanup
    await provider.shutdown()