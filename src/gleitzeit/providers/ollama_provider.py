"""
Streamlined Ollama Provider with Integrated Hub
Much simpler implementation with built-in resource management
"""

import logging
from typing import Dict, Any, Optional, List
import aiohttp
import asyncio
from datetime import datetime

from gleitzeit.providers.hub_provider import HubProvider
from gleitzeit.hub.base import ResourceInstance, ResourceStatus
from gleitzeit.hub.ollama_hub import OllamaConfig
from gleitzeit.core.errors import InvalidParameterError, TaskExecutionError

logger = logging.getLogger(__name__)


class OllamaProvider(HubProvider[OllamaConfig]):
    """
    Streamlined Ollama provider with integrated resource management
    
    This version is much simpler:
    - Inherits all resource management from HubProvider
    - Only implements Ollama-specific logic
    - Automatic health monitoring, metrics, load balancing
    """
    
    def __init__(
        self,
        provider_id: str = "ollama-streamlined",
        default_model: str = "llama3.2",
        auto_discover: bool = True,
        max_instances: int = 10,
        enable_sharing: bool = False
    ):
        """
        Initialize streamlined Ollama provider
        
        Args:
            provider_id: Unique provider identifier  
            default_model: Default model to use
            auto_discover: Auto-discover local Ollama instances
            max_instances: Maximum Ollama instances to manage
            enable_sharing: Allow provider to be shared
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id="llm/v1",
            name="Streamlined Ollama Provider",
            description="Ollama provider with integrated hub functionality",
            resource_config_class=OllamaConfig,
            enable_sharing=enable_sharing,
            max_instances=max_instances,
            enable_auto_discovery=auto_discover
        )
        
        self.default_model = default_model
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self):
        """Initialize provider and create HTTP session"""
        # Create HTTP session
        self.session = aiohttp.ClientSession()
        
        # Call parent initialization (handles auto-discovery, etc.)
        await super().initialize()
    
    async def shutdown(self):
        """Cleanup resources"""
        # Close HTTP session
        if self.session:
            await self.session.close()
            self.session = None
        
        # Call parent shutdown
        await super().shutdown()
    
    async def create_resource(self, config: OllamaConfig) -> ResourceInstance[OllamaConfig]:
        """Create an Ollama resource instance"""
        # Ollama instances are external, we just create a reference
        from gleitzeit.hub.base import ResourceType
        instance = ResourceInstance(
            id=f"ollama-{config.host}-{config.port}",
            name=f"Ollama@{config.port}",
            type=ResourceType.OLLAMA,
            endpoint=f"http://{config.host}:{config.port}",
            status=ResourceStatus.UNKNOWN,
            config=config,
            capabilities=set(config.models) if config.models else set(),
            tags=set(config.tags) if hasattr(config, 'tags') and config.tags else set()
        )
        
        # Check if it's actually available
        if await self.check_resource_health(instance):
            instance.status = ResourceStatus.HEALTHY
        else:
            instance.status = ResourceStatus.UNHEALTHY
        
        return instance
    
    async def destroy_resource(self, instance: ResourceInstance[OllamaConfig]):
        """Destroy an Ollama resource (just cleanup references)"""
        # Ollama instances are external, nothing to destroy
        logger.info(f"Removed Ollama instance reference: {instance.id}")
    
    async def check_resource_health(self, instance: ResourceInstance[OllamaConfig]) -> bool:
        """Check if Ollama instance is healthy"""
        if not self.session:
            return False
        
        try:
            async with self.session.get(
                f"{instance.endpoint}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    # Update capabilities with available models
                    models = {model['name'] for model in data.get('models', [])}
                    instance.capabilities = models
                    return True
                return False
        except Exception as e:
            logger.debug(f"Health check failed for {instance.id}: {e}")
            return False
    
    async def discover_resources(self) -> List[OllamaConfig]:
        """Auto-discover local Ollama instances"""
        discovered = []
        
        # Check common Ollama ports
        ports_to_check = [11434, 11435, 11436, 11437, 11438]
        
        for port in ports_to_check:
            config = OllamaConfig(
                host="127.0.0.1",
                port=port,
                max_concurrent=4
            )
            
            # Create temporary instance to check
            from gleitzeit.hub.base import ResourceType
            temp_instance = ResourceInstance(
                id=f"temp-{port}",
                name=f"temp-{port}",
                type=ResourceType.OLLAMA,
                endpoint=f"http://127.0.0.1:{port}",
                status=ResourceStatus.UNKNOWN,
                config=config
            )
            
            if await self.check_resource_health(temp_instance):
                config.models = list(temp_instance.capabilities)
                discovered.append(config)
                logger.info(f"Discovered Ollama at port {port} with models: {config.models}")
        
        return discovered
    
    async def execute_on_resource(
        self,
        instance: ResourceInstance[OllamaConfig],
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute an LLM method on an Ollama instance"""
        
        # Map methods to Ollama API endpoints
        if method == "llm/complete":
            return await self._complete(instance, params)
        elif method == "llm/chat":
            return await self._chat(instance, params)
        elif method == "llm/vision":
            return await self._vision(instance, params)
        elif method == "llm/embeddings":
            return await self._embeddings(instance, params)
        elif method == "llm/list_models":
            return await self._list_models(instance, params)
        # Support legacy method names for backward compatibility
        elif method == "llm/generate":
            return await self._complete(instance, params)
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _complete(self, instance: ResourceInstance[OllamaConfig], params: Dict[str, Any]) -> Dict[str, Any]:
        """Text completion"""
        model = params.get('model', self.default_model)
        prompt = params.get('prompt', '')
        
        if not prompt:
            raise InvalidParameterError(param_name='prompt', reason='Prompt is required')
        
        # Ensure model is available
        if model not in instance.capabilities:
            await self._pull_model(instance, model)
        
        # Make API call
        async with self.session.post(
            f"{instance.endpoint}/api/generate",
            json={
                'model': model,
                'prompt': prompt,
                'temperature': params.get('temperature', 0.7),
                'stream': False
            }
        ) as response:
            if response.status == 200:
                data = await response.json()
                return {
                    'success': True,
                    'response': data.get('response', ''),
                    'text': data.get('response', ''),  # Also include 'text' field for protocol compliance
                    'model': model,
                    'done': True,
                    'instance_id': instance.id
                }
            else:
                error = await response.text()
                raise TaskExecutionError(message=f"Completion failed: {error}")
    
    async def _chat(self, instance: ResourceInstance[OllamaConfig], params: Dict[str, Any]) -> Dict[str, Any]:
        """Chat completion"""
        model = params.get('model', self.default_model)
        messages = params.get('messages', [])
        
        if not messages:
            raise InvalidParameterError(param_name='messages', reason='Messages are required')
        
        # Ensure model is available
        if model not in instance.capabilities:
            await self._pull_model(instance, model)
        
        # Make API call
        async with self.session.post(
            f"{instance.endpoint}/api/chat",
            json={
                'model': model,
                'messages': messages,
                'temperature': params.get('temperature', 0.7),
                'stream': False
            }
        ) as response:
            if response.status == 200:
                data = await response.json()
                message = data.get('message', {})
                return {
                    'success': True,
                    'response': message.get('content', ''),  # Extract response text for workflows
                    'message': message,
                    'model': model,
                    'done': True,
                    'instance_id': instance.id
                }
            else:
                error = await response.text()
                raise TaskExecutionError(message=f"Chat failed: {error}")
    
    async def _vision(self, instance: ResourceInstance[OllamaConfig], params: Dict[str, Any]) -> Dict[str, Any]:
        """Vision analysis with multimodal models
        
        Note: The base ProtocolProvider already handles image_path -> base64 conversion
        and adds it to the images array during preprocessing.
        """
        model = params.get('model', 'llava:latest')
        messages = params.get('messages', [])
        images = params.get('images', [])  # Already preprocessed by base class
        
        if not messages:
            raise InvalidParameterError(param_name='messages', reason='Messages are required')
        
        # Ensure vision model is available (e.g., llava)
        if model not in instance.capabilities:
            await self._pull_model(instance, model)
        
        # Prepare messages with images
        formatted_messages = []
        for msg in messages:
            formatted_msg = {
                'role': msg.get('role', 'user'),
                'content': msg.get('content', '')
            }
            # Add images to user messages if they have them
            if msg.get('images'):
                formatted_msg['images'] = msg['images']
            # Or add the preprocessed images to the first user message
            elif msg.get('role') == 'user' and images:
                formatted_msg['images'] = images
                images = []  # Only add once
            formatted_messages.append(formatted_msg)
        
        # If images still weren't added, add them to the last user message
        if images:
            for msg in reversed(formatted_messages):
                if msg['role'] == 'user':
                    msg['images'] = images
                    break
        
        # Make API call using chat endpoint (Ollama uses same endpoint for vision)
        async with self.session.post(
            f"{instance.endpoint}/api/chat",
            json={
                'model': model,
                'messages': formatted_messages,
                'temperature': params.get('temperature', 0.7),
                'stream': False
            }
        ) as response:
            if response.status == 200:
                data = await response.json()
                message = data.get('message', {})
                return {
                    'success': True,
                    'response': message.get('content', ''),  # Extract response text for workflows
                    'message': message,
                    'model': model,
                    'done': True,
                    'instance_id': instance.id
                }
            else:
                error = await response.text()
                raise TaskExecutionError(message=f"Vision analysis failed: {error}")
    
    async def _embeddings(self, instance: ResourceInstance[OllamaConfig], params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate embeddings"""
        model = params.get('model', 'nomic-embed-text')
        text = params.get('text', '')
        
        if not text:
            raise InvalidParameterError(param_name='text', reason='Text is required')
        
        # Ensure model is available
        if model not in instance.capabilities:
            await self._pull_model(instance, model)
        
        # Make API call
        async with self.session.post(
            f"{instance.endpoint}/api/embeddings",
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
                    'model': model,
                    'instance_id': instance.id
                }
            else:
                error = await response.text()
                raise TaskExecutionError(message=f"Embeddings failed: {error}")
    
    async def _list_models(self, instance: ResourceInstance[OllamaConfig], params: Dict[str, Any]) -> Dict[str, Any]:
        """List available models"""
        # Aggregate from all instances
        all_models = set()
        model_distribution = {}
        
        for inst in self.instances.values():
            if inst.status == ResourceStatus.HEALTHY:
                for model in inst.capabilities:
                    all_models.add(model)
                    if model not in model_distribution:
                        model_distribution[model] = []
                    model_distribution[model].append(inst.id)
        
        return {
            'success': True,
            'models': list(all_models),
            'model_distribution': model_distribution,
            'total_instances': len(self.instances)
        }
    
    async def _pull_model(self, instance: ResourceInstance[OllamaConfig], model: str):
        """Pull a model to an instance"""
        logger.info(f"Pulling model {model} to {instance.id}")
        
        async with self.session.post(
            f"{instance.endpoint}/api/pull",
            json={'name': model}
        ) as response:
            if response.status == 200:
                # Update capabilities
                instance.capabilities.add(model)
                logger.info(f"Successfully pulled {model} to {instance.id}")
            else:
                error = await response.text()
                logger.error(f"Failed to pull model: {error}")
    
    def get_method_requirements(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get resource requirements for a method"""
        requirements = {}
        
        # For model-specific methods, prefer instances with that model
        if method in ["llm/complete", "llm/generate", "llm/chat", "llm/vision", "llm/embeddings"]:
            model = params.get('model', self.default_model)
            # Use vision-specific default for vision method
            if method == "llm/vision" and model == self.default_model:
                model = 'llava:latest'
            requirements['capabilities'] = {model}
        
        return requirements
    
    def create_default_config(self, method: str, params: Dict[str, Any]) -> OllamaConfig:
        """Create default Ollama configuration"""
        return OllamaConfig(
            host="127.0.0.1",
            port=11434,
            max_concurrent=4
        )
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return ["llm/complete", "llm/chat", "llm/vision", "llm/embeddings", "llm/list_models", "llm/generate"]  # generate for backward compatibility
    
