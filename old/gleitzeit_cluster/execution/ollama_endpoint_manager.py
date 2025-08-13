"""
Multiple Ollama Endpoint Manager

Manages multiple Ollama endpoints with load balancing, model routing,
health monitoring, and failover capabilities.
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Union, Any
from datetime import datetime, timedelta

from .ollama_client import OllamaClient, OllamaError
from ..core.error_handling import RetryManager, RetryConfig, GleitzeitLogger


class LoadBalancingStrategy(Enum):
    """Load balancing strategies for Ollama endpoints"""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    FASTEST_RESPONSE = "fastest_response"
    MODEL_AFFINITY = "model_affinity"


@dataclass
class EndpointConfig:
    """Configuration for an Ollama endpoint"""
    name: str
    url: str
    timeout: int = 300
    max_concurrent: int = 10
    priority: int = 1  # Higher number = higher priority
    models: Optional[List[str]] = None  # Preferred models, None = any
    tags: Set[str] = field(default_factory=set)  # Tags like "gpu", "fast", "large"


@dataclass
class EndpointStats:
    """Statistics for an endpoint"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    current_load: int = 0  # Current concurrent requests
    average_response_time: float = 0.0
    last_health_check: Optional[datetime] = None
    is_healthy: bool = True
    available_models: List[str] = field(default_factory=list)
    last_error: Optional[str] = None


class OllamaEndpointManager:
    """
    Manages multiple Ollama endpoints with intelligent routing and load balancing
    
    Features:
    - Multiple endpoint support with health monitoring
    - Model-aware routing (route tasks to endpoints with specific models)
    - Load balancing strategies (round-robin, least-loaded, fastest)
    - Automatic failover and recovery
    - Endpoint priority and tagging
    """
    
    def __init__(
        self,
        endpoints: List[EndpointConfig],
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_LOADED,
        health_check_interval: int = 60,
        health_check_timeout: int = 10
    ):
        """
        Initialize endpoint manager
        
        Args:
            endpoints: List of endpoint configurations
            strategy: Load balancing strategy
            health_check_interval: How often to check endpoint health (seconds)
            health_check_timeout: Timeout for health checks (seconds)
        """
        self.endpoints = {ep.name: ep for ep in endpoints}
        self.strategy = strategy
        self.health_check_interval = health_check_interval
        self.health_check_timeout = health_check_timeout
        
        # Ollama clients for each endpoint
        self.clients: Dict[str, OllamaClient] = {}
        
        # Statistics and state tracking
        self.stats: Dict[str, EndpointStats] = {}
        self.round_robin_index = 0
        
        # Health monitoring
        self._health_check_task: Optional[asyncio.Task] = None
        self._is_started = False
        
        # Logging and error handling
        self.logger = GleitzeitLogger("OllamaEndpointManager")
        self.retry_manager = RetryManager(self.logger)
        
        # Initialize clients and stats
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialize Ollama clients for each endpoint"""
        for name, config in self.endpoints.items():
            self.clients[name] = OllamaClient(
                base_url=config.url,
                timeout=config.timeout
            )
            self.stats[name] = EndpointStats()
    
    async def start(self) -> None:
        """Start the endpoint manager and begin health monitoring"""
        print("🚀 Starting Ollama Endpoint Manager...")
        print(f"📊 Managing {len(self.endpoints)} endpoints:")
        
        for name, config in self.endpoints.items():
            print(f"   • {name}: {config.url} (priority: {config.priority})")
        
        # Initial health check for all endpoints
        await self._check_all_endpoints_health()
        
        # Start background health monitoring
        if self.health_check_interval > 0:
            self._health_check_task = asyncio.create_task(self._health_monitor_loop())
        
        self._is_started = True
        print("✅ Ollama Endpoint Manager started")
    
    async def stop(self) -> None:
        """Stop the endpoint manager and cleanup resources"""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # Close all clients
        for client in self.clients.values():
            await client.close()
        
        self._is_started = False
        print("🛑 Ollama Endpoint Manager stopped")
    
    async def _health_monitor_loop(self):
        """Background task to monitor endpoint health"""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._check_all_endpoints_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.logger.error(f"Health monitoring error: {e}")
    
    async def _check_all_endpoints_health(self):
        """Check health of all endpoints"""
        tasks = []
        for name in self.endpoints:
            task = asyncio.create_task(self._check_endpoint_health(name))
            tasks.append(task)
        
        # Run all health checks concurrently
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _check_endpoint_health(self, endpoint_name: str) -> bool:
        """Check health of a specific endpoint"""
        client = self.clients[endpoint_name]
        stats = self.stats[endpoint_name]
        
        try:
            start_time = time.time()
            
            # Health check with timeout
            healthy = await asyncio.wait_for(
                client.health_check(),
                timeout=self.health_check_timeout
            )
            
            response_time = time.time() - start_time
            
            if healthy:
                stats.is_healthy = True
                stats.last_error = None
                
                # Update response time (exponential moving average)
                if stats.average_response_time == 0:
                    stats.average_response_time = response_time
                else:
                    stats.average_response_time = (
                        0.7 * stats.average_response_time + 0.3 * response_time
                    )
                
                # Update available models
                try:
                    models = await client.list_models()
                    stats.available_models = models
                except Exception:
                    pass  # Model listing failure doesn't mark endpoint unhealthy
                
            else:
                stats.is_healthy = False
                stats.last_error = "Health check failed"
            
            stats.last_health_check = datetime.utcnow()
            return healthy
            
        except Exception as e:
            stats.is_healthy = False
            stats.last_error = str(e)
            stats.last_health_check = datetime.utcnow()
            return False
    
    def get_healthy_endpoints(self) -> List[str]:
        """Get list of currently healthy endpoint names"""
        return [
            name for name, stats in self.stats.items()
            if stats.is_healthy
        ]
    
    def get_endpoints_with_model(self, model: str) -> List[str]:
        """Get endpoints that have the specified model available"""
        endpoints_with_model = []
        
        for name, stats in self.stats.items():
            if not stats.is_healthy:
                continue
            
            # Check if model is in available models
            if model in stats.available_models:
                endpoints_with_model.append(name)
            
            # If endpoint has no model restrictions, assume it can pull any model
            config = self.endpoints[name]
            if not config.models and not stats.available_models:
                endpoints_with_model.append(name)
        
        return endpoints_with_model
    
    def select_endpoint(
        self,
        model: Optional[str] = None,
        tags: Optional[Set[str]] = None,
        exclude: Optional[Set[str]] = None
    ) -> Optional[str]:
        """
        Select the best endpoint based on strategy and constraints
        
        Args:
            model: Required model name
            tags: Required endpoint tags
            exclude: Endpoint names to exclude
            
        Returns:
            Selected endpoint name or None if no suitable endpoint
        """
        exclude = exclude or set()
        
        # Start with healthy endpoints
        candidates = [name for name in self.get_healthy_endpoints() if name not in exclude]
        
        if not candidates:
            return None
        
        # Filter by model availability
        if model:
            model_candidates = [
                name for name in candidates
                if name in self.get_endpoints_with_model(model)
            ]
            if model_candidates:
                candidates = model_candidates
        
        # Filter by tags
        if tags:
            tag_candidates = [
                name for name in candidates
                if tags.issubset(self.endpoints[name].tags)
            ]
            if tag_candidates:
                candidates = tag_candidates
        
        if not candidates:
            return None
        
        # Apply load balancing strategy
        return self._apply_strategy(candidates, model)
    
    def _apply_strategy(self, candidates: List[str], model: Optional[str] = None) -> str:
        """Apply load balancing strategy to select from candidates"""
        
        if self.strategy == LoadBalancingStrategy.ROUND_ROBIN:
            # Round-robin selection
            selected = candidates[self.round_robin_index % len(candidates)]
            self.round_robin_index += 1
            return selected
        
        elif self.strategy == LoadBalancingStrategy.LEAST_LOADED:
            # Select endpoint with least current load
            return min(candidates, key=lambda name: (
                self.stats[name].current_load,
                -self.endpoints[name].priority  # Higher priority first
            ))
        
        elif self.strategy == LoadBalancingStrategy.FASTEST_RESPONSE:
            # Select endpoint with fastest average response time
            return min(candidates, key=lambda name: (
                self.stats[name].average_response_time,
                self.stats[name].current_load
            ))
        
        elif self.strategy == LoadBalancingStrategy.MODEL_AFFINITY:
            # Prefer endpoints that have the model readily available
            if model:
                model_ready = [
                    name for name in candidates
                    if model in self.stats[name].available_models
                ]
                if model_ready:
                    # Among model-ready endpoints, choose least loaded
                    return min(model_ready, key=lambda name: self.stats[name].current_load)
            
            # Fallback to least loaded
            return min(candidates, key=lambda name: self.stats[name].current_load)
        
        # Default: random selection
        return random.choice(candidates)
    
    async def execute_text_task(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        preferred_tags: Optional[Set[str]] = None
    ) -> str:
        """
        Execute text generation task on best available endpoint
        
        Args:
            model: Model name
            prompt: Input prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            system_prompt: System prompt
            stream: Enable streaming
            preferred_tags: Preferred endpoint tags
            
        Returns:
            Generated text
            
        Raises:
            OllamaError: If all endpoints fail
        """
        return await self._execute_with_failover(
            "generate_text",
            model=model,
            preferred_tags=preferred_tags,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            stream=stream
        )
    
    async def execute_vision_task(
        self,
        model: str,
        prompt: str,
        image_path: str,
        temperature: float = 0.4,
        max_tokens: Optional[int] = None,
        preferred_tags: Optional[Set[str]] = None
    ) -> str:
        """
        Execute vision task on best available endpoint
        
        Args:
            model: Vision model name (e.g., "llava")
            prompt: Image analysis prompt
            image_path: Path to image file
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            preferred_tags: Preferred endpoint tags
            
        Returns:
            Image analysis result
            
        Raises:
            OllamaError: If all endpoints fail
        """
        return await self._execute_with_failover(
            "generate_vision",
            model=model,
            preferred_tags=preferred_tags,
            prompt=prompt,
            image_path=image_path,
            temperature=temperature,
            max_tokens=max_tokens
        )
    
    async def _execute_with_failover(
        self,
        method: str,
        model: str,
        preferred_tags: Optional[Set[str]] = None,
        **kwargs
    ) -> Any:
        """
        Execute method with automatic failover between endpoints
        
        Args:
            method: Method name to call on OllamaClient
            model: Model name for endpoint selection
            preferred_tags: Preferred endpoint tags
            **kwargs: Arguments for the method
            
        Returns:
            Method result
            
        Raises:
            OllamaError: If all suitable endpoints fail
        """
        attempted_endpoints = set()
        last_error = None
        
        while True:
            # Select best available endpoint
            endpoint_name = self.select_endpoint(
                model=model,
                tags=preferred_tags,
                exclude=attempted_endpoints
            )
            
            if not endpoint_name:
                if attempted_endpoints:
                    raise OllamaError(f"All suitable endpoints failed. Last error: {last_error}")
                else:
                    raise OllamaError(f"No healthy endpoints available for model '{model}'")
            
            # Track load
            stats = self.stats[endpoint_name]
            stats.current_load += 1
            start_time = time.time()
            
            try:
                # Execute on selected endpoint
                client = self.clients[endpoint_name]
                method_func = getattr(client, method)
                
                # Include model parameter in kwargs
                kwargs_with_model = dict(kwargs)
                kwargs_with_model['model'] = model
                
                result = await method_func(**kwargs_with_model)
                
                # Update success statistics
                response_time = time.time() - start_time
                stats.successful_requests += 1
                stats.total_requests += 1
                
                # Update response time (exponential moving average)
                if stats.average_response_time == 0:
                    stats.average_response_time = response_time
                else:
                    stats.average_response_time = (
                        0.8 * stats.average_response_time + 0.2 * response_time
                    )
                
                return result
                
            except Exception as e:
                # Update failure statistics
                stats.failed_requests += 1
                stats.total_requests += 1
                stats.last_error = str(e)
                
                # Mark endpoint as potentially unhealthy if too many failures
                failure_rate = stats.failed_requests / max(stats.total_requests, 1)
                if failure_rate > 0.5 and stats.total_requests >= 5:
                    stats.is_healthy = False
                
                attempted_endpoints.add(endpoint_name)
                last_error = e
                
                self.logger.logger.warning(
                    f"Endpoint {endpoint_name} failed for {method}: {e}. "
                    f"Trying next endpoint..."
                )
                
            finally:
                # Decrease load counter
                stats.current_load = max(0, stats.current_load - 1)
    
    def get_endpoint_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get comprehensive statistics for all endpoints"""
        result = {}
        
        for name, stats in self.stats.items():
            config = self.endpoints[name]
            
            result[name] = {
                "config": {
                    "url": config.url,
                    "priority": config.priority,
                    "max_concurrent": config.max_concurrent,
                    "tags": list(config.tags),
                    "preferred_models": config.models
                },
                "stats": {
                    "is_healthy": stats.is_healthy,
                    "current_load": stats.current_load,
                    "total_requests": stats.total_requests,
                    "successful_requests": stats.successful_requests,
                    "failed_requests": stats.failed_requests,
                    "success_rate": stats.successful_requests / max(stats.total_requests, 1),
                    "average_response_time": stats.average_response_time,
                    "available_models": stats.available_models,
                    "last_health_check": stats.last_health_check.isoformat() if stats.last_health_check else None,
                    "last_error": stats.last_error
                }
            }
        
        return result
    
    def add_endpoint(self, config: EndpointConfig) -> None:
        """Add a new endpoint at runtime"""
        if config.name in self.endpoints:
            raise ValueError(f"Endpoint '{config.name}' already exists")
        
        self.endpoints[config.name] = config
        self.clients[config.name] = OllamaClient(
            base_url=config.url,
            timeout=config.timeout
        )
        self.stats[config.name] = EndpointStats()
        
        print(f"➕ Added endpoint: {config.name} ({config.url})")
        
        # Trigger immediate health check if running
        if self._is_started:
            asyncio.create_task(self._check_endpoint_health(config.name))
    
    def remove_endpoint(self, endpoint_name: str) -> None:
        """Remove an endpoint at runtime"""
        if endpoint_name not in self.endpoints:
            raise ValueError(f"Endpoint '{endpoint_name}' not found")
        
        # Close client
        asyncio.create_task(self.clients[endpoint_name].close())
        
        # Remove from all tracking
        del self.endpoints[endpoint_name]
        del self.clients[endpoint_name]
        del self.stats[endpoint_name]
        
        print(f"➖ Removed endpoint: {endpoint_name}")
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.stop()
    
    def __str__(self) -> str:
        healthy = len(self.get_healthy_endpoints())
        total = len(self.endpoints)
        return f"OllamaEndpointManager({healthy}/{total} healthy, strategy={self.strategy.value})"