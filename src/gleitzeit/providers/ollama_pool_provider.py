"""
Ollama Pool Provider - Multi-instance Ollama with load balancing

This provider extends the basic OllamaProvider to support multiple Ollama instances
with load balancing, health monitoring, and automatic failover.
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
import aiohttp
import json
import base64

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.orchestration.ollama_pool import OllamaPoolManager, LoadBalancingStrategy
from gleitzeit.core.errors import (
    ProviderError, MethodNotSupportedError, InvalidParameterError,
    ProviderNotAvailableError, ProviderTimeoutError, ErrorCode
)

logger = logging.getLogger(__name__)


class OllamaPoolProvider(ProtocolProvider):
    """
    Multi-instance Ollama provider with load balancing and failover
    
    Extends the basic Ollama provider to support:
    - Multiple Ollama instance orchestration
    - Load balancing strategies
    - Health monitoring and failover
    - Model affinity routing
    - Circuit breaker protection
    """
    
    def __init__(
        self,
        provider_id: str,
        instances: List[Dict[str, Any]],
        load_balancing_config: Optional[Dict[str, Any]] = None,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
        timeout: int = 60
    ):
        """
        Initialize Ollama Pool Provider
        
        Args:
            provider_id: Unique provider identifier
            instances: List of Ollama instance configurations
            load_balancing_config: Load balancing configuration
            circuit_breaker_config: Circuit breaker configuration
            timeout: Request timeout in seconds
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id="llm/v1",
            name="Ollama Pool Provider",
            description="Multi-instance Ollama provider with load balancing"
        )
        
        # Validate instances configuration
        if not instances:
            raise ValueError("At least one Ollama instance must be configured")
            
        self.timeout = timeout
        self.session = None
        
        # Load balancing configuration
        lb_config = load_balancing_config or {}
        self.default_strategy = lb_config.get('strategy', 'least_loaded')
        self.health_check_interval = lb_config.get('health_check_interval', 30)
        self.enable_failover = lb_config.get('failover', True)
        self.retry_attempts = lb_config.get('retry_attempts', 3)
        
        # Initialize pool manager
        self.pool_manager = OllamaPoolManager(
            instances=instances,
            health_check_interval=self.health_check_interval,
            circuit_breaker_config=circuit_breaker_config
        )
        
        logger.info(f"Initialized OllamaPoolProvider with {len(instances)} instances")
        
    async def initialize(self):
        """Initialize the provider and pool manager"""
        try:
            # Create HTTP session
            self.session = aiohttp.ClientSession()
            
            # Initialize pool manager
            await self.pool_manager.initialize()
            
            # Get initial pool status
            status = await self.pool_manager.get_pool_status()
            
            logger.info(
                f"✅ Ollama pool initialized: "
                f"{status['healthy_instances']}/{status['total_instances']} healthy"
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize Ollama pool provider: {e}")
            raise ProviderError(
                code=ErrorCode.PROVIDER_INITIALIZATION_FAILED,
                message=f"Failed to initialize Ollama pool: {str(e)}",
                provider_id=self.provider_id
            )
            
    async def shutdown(self):
        """Shutdown the provider and cleanup resources"""
        # Shutdown pool manager
        if self.pool_manager:
            await self.pool_manager.shutdown()
            
        # Close HTTP session
        if self.session:
            await self.session.close()
            self.session = None
            
        logger.info("Ollama pool provider shutdown")
        
    async def health_check(self) -> Dict[str, Any]:
        """Get health status of the provider and all instances"""
        try:
            pool_status = await self.pool_manager.get_pool_status()
            
            return {
                "status": "healthy" if pool_status['healthy_instances'] > 0 else "unhealthy",
                "details": {
                    "pool_status": pool_status,
                    "default_strategy": self.default_strategy,
                    "failover_enabled": self.enable_failover
                }
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "details": {"error": str(e)}
            }
            
    def get_supported_methods(self) -> List[str]:
        """Get supported protocol methods"""
        return ["llm/generate", "llm/chat", "llm/vision", "llm/embed"]
        
    async def execute(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a method with automatic instance selection and failover
        
        Args:
            method: Protocol method (e.g., "llm/chat")
            params: Method parameters
            
        Returns:
            Execution result
        """
        # Validate method
        if method not in self.get_supported_methods():
            raise MethodNotSupportedError(
                code=ErrorCode.METHOD_NOT_SUPPORTED,
                message=f"Method '{method}' not supported",
                provider_id=self.provider_id,
                method=method
            )
            
        # Extract routing hints from params
        model = params.get('model')
        strategy = params.get('load_balancing_strategy', self.default_strategy)
        tags = params.get('instance_tags')
        require_gpu = params.get('require_gpu', False)
        
        # Add GPU tag if required
        if require_gpu and tags:
            tags.append('gpu')
        elif require_gpu:
            tags = ['gpu']
            
        # Execute with retry and failover
        last_error = None
        attempts = 0
        
        while attempts < self.retry_attempts:
            attempts += 1
            
            # Get instance from pool
            instance_url = await self.pool_manager.get_instance(
                model=model,
                strategy=strategy,
                tags=tags,
                require_healthy=True
            )
            
            if not instance_url:
                raise ProviderNotAvailableError(
                    code=ErrorCode.PROVIDER_NOT_AVAILABLE,
                    message="No available Ollama instances",
                    provider_id=self.provider_id
                )
                
            # Track timing
            start_time = time.time()
            
            try:
                # Execute request on selected instance
                result = await self._execute_on_instance(
                    instance_url,
                    method,
                    params
                )
                
                # Record success
                response_time = time.time() - start_time
                await self.pool_manager.record_success(instance_url, response_time)
                
                return result
                
            except asyncio.TimeoutError as e:
                # Record failure
                await self.pool_manager.record_failure(instance_url, e)
                last_error = e
                
                if not self.enable_failover or attempts >= self.retry_attempts:
                    raise ProviderTimeoutError(
                        code=ErrorCode.PROVIDER_TIMEOUT,
                        message=f"Request timeout after {self.timeout} seconds",
                        provider_id=self.provider_id
                    )
                    
                logger.warning(
                    f"Request timeout on {instance_url}, "
                    f"attempting failover (attempt {attempts}/{self.retry_attempts})"
                )
                
            except Exception as e:
                # Record failure
                await self.pool_manager.record_failure(instance_url, e)
                last_error = e
                
                if not self.enable_failover or attempts >= self.retry_attempts:
                    raise
                    
                logger.warning(
                    f"Request failed on {instance_url}: {e}, "
                    f"attempting failover (attempt {attempts}/{self.retry_attempts})"
                )
                
            finally:
                # Release instance
                await self.pool_manager.release_instance(instance_url)
                
        # All retries exhausted
        raise ProviderError(
            code=ErrorCode.PROVIDER_UNHEALTHY,
            message=f"All retry attempts failed: {last_error}",
            provider_id=self.provider_id
        )
        
    async def _execute_on_instance(
        self,
        instance_url: str,
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute request on specific Ollama instance"""
        
        # Map method to Ollama API endpoint
        if method == "llm/generate":
            return await self._generate(instance_url, params)
        elif method == "llm/chat":
            return await self._chat(instance_url, params)
        elif method == "llm/vision":
            return await self._vision(instance_url, params)
        elif method == "llm/embed":
            return await self._embed(instance_url, params)
        else:
            raise MethodNotSupportedError(
                code=ErrorCode.METHOD_NOT_SUPPORTED,
                message=f"Unknown method: {method}",
                provider_id=self.provider_id,
                method=method
            )
            
    async def _generate(
        self,
        instance_url: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute text generation"""
        model = params.get("model", "llama3.2")
        prompt = params.get("prompt", "")
        
        if not prompt:
            raise InvalidParameterError(
                code=ErrorCode.INVALID_PARAMS,
                message="Missing required parameter: prompt",
                provider_id=self.provider_id
            )
            
        # Prepare request
        request_data = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": params.get("temperature", 0.7),
                "top_p": params.get("top_p", 0.9),
                "max_tokens": params.get("max_tokens", 1000)
            }
        }
        
        # Make request
        async with self.session.post(
            f"{instance_url}/api/generate",
            json=request_data,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise ProviderError(
                    code=ErrorCode.PROVIDER_ERROR,
                    message=f"Ollama API error: {error_text}",
                    provider_id=self.provider_id
                )
                
            result = await response.json()
            
        return {
            "response": result.get("response", ""),
            "model": model,
            "done": result.get("done", True),
            "context": result.get("context"),
            "total_duration": result.get("total_duration"),
            "load_duration": result.get("load_duration"),
            "prompt_eval_duration": result.get("prompt_eval_duration"),
            "eval_duration": result.get("eval_duration"),
            "eval_count": result.get("eval_count")
        }
        
    async def _chat(
        self,
        instance_url: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute chat completion"""
        model = params.get("model", "llama3.2")
        messages = params.get("messages", [])
        
        if not messages:
            raise InvalidParameterError(
                code=ErrorCode.INVALID_PARAMS,
                message="Missing required parameter: messages",
                provider_id=self.provider_id
            )
            
        # Prepare request
        request_data = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": params.get("temperature", 0.7),
                "top_p": params.get("top_p", 0.9),
                "max_tokens": params.get("max_tokens", 1000)
            }
        }
        
        # Make request
        async with self.session.post(
            f"{instance_url}/api/chat",
            json=request_data,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise ProviderError(
                    code=ErrorCode.PROVIDER_ERROR,
                    message=f"Ollama API error: {error_text}",
                    provider_id=self.provider_id
                )
                
            result = await response.json()
            
        # Extract message content
        message = result.get("message", {})
        
        return {
            "response": message.get("content", ""),
            "role": message.get("role", "assistant"),
            "model": model,
            "done": result.get("done", True),
            "total_duration": result.get("total_duration"),
            "load_duration": result.get("load_duration"),
            "prompt_eval_duration": result.get("prompt_eval_duration"),
            "eval_duration": result.get("eval_duration"),
            "eval_count": result.get("eval_count")
        }
        
    async def _vision(
        self,
        instance_url: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute vision analysis"""
        model = params.get("model", "llava")
        prompt = params.get("prompt", "Describe this image")
        images = params.get("images", [])
        
        if not images:
            raise InvalidParameterError(
                code=ErrorCode.INVALID_PARAMS,
                message="Missing required parameter: images",
                provider_id=self.provider_id
            )
            
        # Handle both file paths and base64 encoded images
        processed_images = []
        for image in images:
            if isinstance(image, str) and image.startswith("data:"):
                # Already base64 encoded
                processed_images.append(image.split(",")[1] if "," in image else image)
            elif isinstance(image, str):
                # File path - read and encode
                try:
                    with open(image, "rb") as f:
                        image_data = base64.b64encode(f.read()).decode()
                        processed_images.append(image_data)
                except Exception as e:
                    raise InvalidParameterError(
                        code=ErrorCode.INVALID_PARAMS,
                        message=f"Failed to read image file: {e}",
                        provider_id=self.provider_id
                    )
            else:
                processed_images.append(image)
                
        # Prepare request
        request_data = {
            "model": model,
            "prompt": prompt,
            "images": processed_images,
            "stream": False,
            "options": {
                "temperature": params.get("temperature", 0.7)
            }
        }
        
        # Make request
        async with self.session.post(
            f"{instance_url}/api/generate",
            json=request_data,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise ProviderError(
                    code=ErrorCode.PROVIDER_ERROR,
                    message=f"Ollama API error: {error_text}",
                    provider_id=self.provider_id
                )
                
            result = await response.json()
            
        return {
            "response": result.get("response", ""),
            "model": model,
            "done": result.get("done", True),
            "total_duration": result.get("total_duration"),
            "eval_count": result.get("eval_count")
        }
        
    async def _embed(
        self,
        instance_url: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate embeddings"""
        model = params.get("model", "llama3.2")
        input_text = params.get("input", "")
        
        if not input_text:
            raise InvalidParameterError(
                code=ErrorCode.INVALID_PARAMS,
                message="Missing required parameter: input",
                provider_id=self.provider_id
            )
            
        # Handle both string and list inputs
        if isinstance(input_text, str):
            input_text = [input_text]
            
        embeddings = []
        
        for text in input_text:
            # Prepare request
            request_data = {
                "model": model,
                "input": text
            }
            
            # Make request
            async with self.session.post(
                f"{instance_url}/api/embed",
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise ProviderError(
                        code=ErrorCode.PROVIDER_ERROR,
                        message=f"Ollama API error: {error_text}",
                        provider_id=self.provider_id
                    )
                    
                result = await response.json()
                embeddings.append(result.get("embeddings", []))
                
        return {
            "embeddings": embeddings[0] if len(embeddings) == 1 else embeddings,
            "model": model
        }
        
    async def get_pool_status(self) -> Dict[str, Any]:
        """Get detailed pool status"""
        return await self.pool_manager.get_pool_status()
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle JSON-RPC request (required by base class)"""
        method = request.get("method")
        params = request.get("params", {})
        
        try:
            result = await self.execute(method, params)
            return {
                "jsonrpc": "2.0",
                "result": result,
                "id": request.get("id")
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "error": {
                    "code": getattr(e, "code", -32603),
                    "message": str(e)
                },
                "id": request.get("id")
            }