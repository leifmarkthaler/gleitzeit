"""
Refactored Ollama Pool Provider - Version 2
Uses OllamaHub for resource management while maintaining protocol compatibility
"""

import logging
from typing import Dict, Any, Optional, List
import json
import time

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.hub.ollama_hub import OllamaHub, OllamaConfig
from gleitzeit.hub.base import ResourceStatus
from gleitzeit.common.load_balancer import LoadBalancingStrategy
from gleitzeit.core.errors import (
    ProviderError, MethodNotSupportedError, InvalidParameterError,
    ProviderNotAvailableError, TaskExecutionError
)

logger = logging.getLogger(__name__)


class OllamaPoolProviderV2(ProtocolProvider):
    """
    Refactored Ollama provider using hub architecture
    
    This version:
    - Delegates resource management to OllamaHub
    - Focuses on protocol-specific logic (LLM methods)
    - Maintains backward compatibility with existing API
    - Reduces code duplication
    """
    
    def __init__(
        self,
        provider_id: str,
        hub: Optional[OllamaHub] = None,
        instances: Optional[List[Dict[str, Any]]] = None,
        auto_discover: bool = True,
        default_model: str = "llama3.2",
        timeout: int = 60,
        use_legacy_api: bool = False  # For backward compatibility
    ):
        """
        Initialize refactored Ollama provider
        
        Args:
            provider_id: Unique provider identifier
            hub: Optional existing OllamaHub to use (shared resource management)
            instances: Optional list of instance configs if creating new hub
            auto_discover: Auto-discover local Ollama instances
            default_model: Default model to use
            timeout: Request timeout in seconds
            use_legacy_api: Use legacy API format for compatibility
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id="llm/v1",
            name="Ollama Pool Provider V2",
            description="Refactored Ollama provider with hub architecture"
        )
        
        self.timeout = timeout
        self.default_model = default_model
        self.use_legacy_api = use_legacy_api
        
        # Hub management
        if hub:
            # Use existing hub (shared resource management)
            self.hub = hub
            self.owns_hub = False
            logger.info(f"Provider {provider_id} using shared hub {hub.hub_id}")
        else:
            # Create dedicated hub
            self.hub = OllamaHub(
                hub_id=f"{provider_id}-hub",
                auto_discover=auto_discover
            )
            self.owns_hub = True
            logger.info(f"Provider {provider_id} created dedicated hub")
            
            # Store instances to register after initialization
            self._instances_to_register = instances or []
    
    async def initialize(self):
        """Initialize the provider and hub"""
        try:
            # Start hub if we own it
            if self.owns_hub:
                await self.hub.start()
                
                # Register provided instances
                for inst_config in self._instances_to_register:
                    config = OllamaConfig(
                        host=inst_config.get('host', '127.0.0.1'),
                        port=inst_config.get('port', 11434),
                        models=inst_config.get('models', []),
                        max_concurrent=inst_config.get('max_concurrent', 4),
                        tags=inst_config.get('tags', []),
                        priority=inst_config.get('priority', 1)
                    )
                    
                    instance = await self.hub.start_instance(config)
                    if instance:
                        logger.info(f"Registered instance {instance.id}")
            
            # Wait for at least one healthy instance
            import asyncio
            for attempt in range(10):
                instances = await self.hub.list_instances(status=ResourceStatus.HEALTHY)
                if instances:
                    logger.info(
                        f"✅ Provider initialized with {len(instances)} healthy instance(s)"
                    )
                    break
                    
                if attempt < 9:
                    await asyncio.sleep(1)
            else:
                # No healthy instances after waiting
                if not self.hub.auto_discover:
                    raise ProviderNotAvailableError(
                        "No healthy Ollama instances available",
                        provider_id=self.provider_id
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
                logger.info(f"Stopped dedicated hub for provider {self.provider_id}")
            
            logger.info("Provider shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check provider health"""
        hub_status = await self.hub.get_status() if self.hub else {}
        instances = await self.hub.list_instances() if self.hub else []
        
        healthy_count = sum(
            1 for inst in instances 
            if inst.status == ResourceStatus.HEALTHY
        )
        
        return {
            "status": "healthy" if healthy_count > 0 else "unhealthy",
            "details": {
                "hub_id": self.hub.hub_id if self.hub else None,
                "owns_hub": self.owns_hub,
                "total_instances": len(instances),
                "healthy_instances": healthy_count,
                "default_model": self.default_model
            }
        }
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an LLM method using hub-managed instances
        """
        # Map protocol methods
        method_map = {
            "llm/generate": self._generate,
            "llm/chat": self._chat,
            "llm/embeddings": self._embeddings,
            "llm/list_models": self._list_models,
            "llm/pull_model": self._pull_model,
            "llm/delete_model": self._delete_model
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
            raise InvalidParameterError(param_name='prompt', reason="Prompt is required")
        
        # Determine load balancing strategy
        strategy_name = params.get('load_balancing_strategy', 'least_loaded')
        strategy = self._get_strategy(strategy_name)
        
        # Get instance from hub
        instance = await self.hub.get_instance_for_model(
            model_name=model,
            strategy=strategy
        )
        
        if not instance:
            # Try to ensure model on any available instance
            instances = await self.hub.list_instances(status=ResourceStatus.HEALTHY)
            if instances:
                instance = instances[0]
                logger.info(f"Ensuring model {model} on instance {instance.id}")
                success = await self.hub.ensure_model(instance.id, model)
                if not success:
                    raise ProviderError(f"Failed to load model {model}")
            else:
                raise ProviderNotAvailableError("No instances available")
        
        # Execute on the selected instance
        start_time = time.time()
        try:
            result = await self.hub.execute_on_instance(
                instance_id=instance.id,
                method='generate',
                params={
                    'model': model,
                    'prompt': prompt,
                    'temperature': params.get('temperature', 0.7),
                    'max_tokens': params.get('max_tokens'),
                    'top_p': params.get('top_p'),
                    'top_k': params.get('top_k'),
                    'stream': False
                }
            )
            
            response_time = (time.time() - start_time) * 1000  # ms
            
            # Format response based on API version
            if self.use_legacy_api:
                return {
                    'success': True,
                    'response': result.get('response', ''),
                    'model': model,
                    'instance_url': instance.endpoint,
                    'metrics': {
                        'response_time': response_time,
                        'instance_load': instance.metrics.active_connections
                    }
                }
            else:
                return {
                    'success': True,
                    'response': result.get('response', ''),
                    'model': model,
                    'instance_id': instance.id,
                    'metrics': {
                        'response_time_ms': response_time,
                        'queue_depth': instance.metrics.active_connections,
                        'total_requests': instance.metrics.request_count
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
            raise InvalidParameterError(param_name='messages', reason="Messages are required")
        
        # Get load balancing strategy
        strategy = self._get_strategy(params.get('load_balancing_strategy', 'least_loaded'))
        
        # Get instance from hub
        instance = await self.hub.get_instance_for_model(
            model_name=model,
            strategy=strategy
        )
        
        if not instance:
            # Try to load model
            instances = await self.hub.list_instances(status=ResourceStatus.HEALTHY)
            if instances:
                instance = instances[0]
                await self.hub.ensure_model(instance.id, model)
            else:
                raise ProviderNotAvailableError(f"No instance available for model {model}")
        
        # Execute chat
        start_time = time.time()
        try:
            result = await self.hub.execute_on_instance(
                instance_id=instance.id,
                method='chat',
                params={
                    'model': model,
                    'messages': messages,
                    'temperature': params.get('temperature', 0.7),
                    'max_tokens': params.get('max_tokens'),
                    'stream': False
                }
            )
            
            response_time = (time.time() - start_time) * 1000
            
            return {
                'success': True,
                'message': result.get('message', {}),
                'model': model,
                'instance_id': instance.id,
                'metrics': {
                    'response_time_ms': response_time
                }
            }
            
        except Exception as e:
            logger.error(f"Chat failed on {instance.id}: {e}")
            raise TaskExecutionError(f"Chat failed: {e}")
    
    async def _embeddings(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle embeddings generation"""
        model = params.get('model', 'nomic-embed-text')
        text = params.get('text', '')
        
        if not text:
            raise InvalidParameterError(param_name='text', reason="Text is required")
        
        # Get instance
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
                    'models': list(inst.capabilities),
                    'metrics': {
                        'active_requests': inst.metrics.active_connections,
                        'total_requests': inst.metrics.request_count,
                        'avg_response_time_ms': inst.metrics.avg_response_time_ms
                    }
                }
                for inst in instances
            ],
            'total_capacity': sum(
                inst.config.max_concurrent for inst in instances
                if inst.status == ResourceStatus.HEALTHY
            )
        }
    
    async def _pull_model(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Pull a model to one or more instances"""
        model = params.get('model')
        if not model:
            raise InvalidParameterError(param_name='model', reason="Model name is required")
        
        instance_ids = params.get('instance_ids', [])
        
        if not instance_ids:
            # Pull to all healthy instances
            instances = await self.hub.list_instances(status=ResourceStatus.HEALTHY)
            instance_ids = [inst.id for inst in instances]
        
        results = {}
        for instance_id in instance_ids:
            success = await self.hub.ensure_model(instance_id, model)
            results[instance_id] = success
        
        return {
            'success': all(results.values()),
            'model': model,
            'results': results
        }
    
    async def _delete_model(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a model from instances"""
        model = params.get('model')
        if not model:
            raise InvalidParameterError(param_name='model', reason="Model name is required")
        
        instance_ids = params.get('instance_ids', [])
        
        # Execute delete on instances
        results = {}
        for instance_id in instance_ids:
            try:
                result = await self.hub.execute_on_instance(
                    instance_id=instance_id,
                    method='delete',
                    params={'model': model}
                )
                results[instance_id] = result.get('success', False)
            except Exception as e:
                logger.error(f"Failed to delete model from {instance_id}: {e}")
                results[instance_id] = False
        
        return {
            'success': all(results.values()),
            'model': model,
            'results': results
        }
    
    async def get_status(self) -> Dict[str, Any]:
        """Get provider status including hub metrics"""
        hub_status = await self.hub.get_status()
        hub_metrics = await self.hub.get_metrics_summary()
        
        return {
            'provider_id': self.provider_id,
            'protocol': self.protocol_id,
            'owns_hub': self.owns_hub,
            'hub_id': self.hub.hub_id,
            'hub_status': hub_status,
            'metrics': hub_metrics,
            'capabilities': {
                'methods': [
                    'llm/generate', 'llm/chat', 'llm/embeddings',
                    'llm/list_models', 'llm/pull_model', 'llm/delete_model'
                ],
                'load_balancing': True,
                'auto_discovery': self.hub.auto_discover,
                'health_monitoring': True,
                'model_management': True,
                'circuit_breaker': True
            }
        }
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle JSON-RPC style requests"""
        method = request.get('method')
        params = request.get('params', {})
        
        try:
            result = await self.execute(method, params)
            return {
                'jsonrpc': '2.0',
                'result': result,
                'id': request.get('id')
            }
        except Exception as e:
            return {
                'jsonrpc': '2.0',
                'error': {
                    'code': getattr(e, 'code', -32603),
                    'message': str(e)
                },
                'id': request.get('id')
            }
    
    def _get_strategy(self, strategy_name: str) -> str:
        """Map strategy names to LoadBalancingStrategy values"""
        strategy_map = {
            'round_robin': 'round_robin',
            'least_loaded': 'least_loaded',
            'random': 'random',
            'model_affinity': 'least_loaded',  # Use least_loaded with model filter
            'latency_based': 'least_response_time',
            'weighted': 'weighted_random'
        }
        return strategy_map.get(strategy_name, 'least_loaded')