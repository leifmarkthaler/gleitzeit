"""
Ollama Pool Manager - Orchestrates multiple Ollama instances
"""
from typing import List, Dict, Any, Optional, Set, Tuple
import asyncio
import logging
import time
import random
import aiohttp
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class InstanceState(Enum):
    """Instance health states"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class LoadBalancingStrategy(Enum):
    """Load balancing strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    RANDOM = "random"
    MODEL_AFFINITY = "model_affinity"
    LATENCY_BASED = "latency_based"
    WEIGHTED = "weighted"


@dataclass
class InstanceMetrics:
    """Metrics for an Ollama instance"""
    response_times: List[float] = field(default_factory=list)
    error_count: int = 0
    success_count: int = 0
    last_error_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    models_loaded: Set[str] = field(default_factory=set)
    active_requests: int = 0
    total_requests: int = 0
    
    @property
    def avg_response_time(self) -> float:
        """Calculate average response time"""
        if not self.response_times:
            return 0.0
        # Keep only last 100 measurements
        recent = self.response_times[-100:]
        return sum(recent) / len(recent)
    
    @property
    def error_rate(self) -> float:
        """Calculate error rate"""
        total = self.error_count + self.success_count
        return self.error_count / total if total > 0 else 0.0
    
    @property
    def availability(self) -> float:
        """Calculate availability percentage"""
        total = self.error_count + self.success_count
        return (self.success_count / total * 100) if total > 0 else 100.0


@dataclass
class OllamaInstance:
    """Represents an Ollama instance"""
    id: str
    url: str
    models: List[str] = field(default_factory=list)
    max_concurrent: int = 5
    tags: List[str] = field(default_factory=list)
    priority: int = 1
    weight: float = 1.0
    specialization: Optional[str] = None
    state: InstanceState = InstanceState.UNKNOWN
    metrics: InstanceMetrics = field(default_factory=InstanceMetrics)
    circuit_breaker_open: bool = False
    circuit_breaker_failures: int = 0
    circuit_breaker_last_failure: Optional[datetime] = None
    

class CircuitBreaker:
    """Circuit breaker for instance failover"""
    
    def __init__(
        self, 
        failure_threshold: int = 5, 
        recovery_timeout: int = 60,
        half_open_requests: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_requests = half_open_requests
        self.states = {}  # instance_id -> state
        
    def record_success(self, instance_id: str):
        """Record successful request"""
        if instance_id in self.states:
            self.states[instance_id]['failures'] = 0
            self.states[instance_id]['state'] = 'closed'
            
    def record_failure(self, instance_id: str):
        """Record failed request"""
        if instance_id not in self.states:
            self.states[instance_id] = {
                'failures': 0,
                'state': 'closed',
                'last_failure': None,
                'half_open_attempts': 0
            }
            
        state = self.states[instance_id]
        state['failures'] += 1
        state['last_failure'] = datetime.now()
        
        if state['failures'] >= self.failure_threshold:
            state['state'] = 'open'
            logger.warning(f"Circuit breaker opened for instance {instance_id}")
            
    def is_open(self, instance_id: str) -> bool:
        """Check if circuit is open"""
        if instance_id not in self.states:
            return False
            
        state = self.states[instance_id]
        if state['state'] == 'closed':
            return False
            
        # Check if recovery timeout has passed
        if state['last_failure']:
            elapsed = (datetime.now() - state['last_failure']).seconds
            if elapsed > self.recovery_timeout:
                # Move to half-open state
                state['state'] = 'half_open'
                state['half_open_attempts'] = 0
                return False
                
        return state['state'] == 'open'
        
    def is_half_open(self, instance_id: str) -> bool:
        """Check if circuit is in half-open state"""
        return (instance_id in self.states and 
                self.states[instance_id]['state'] == 'half_open')


class OllamaPoolManager:
    """
    Manages multiple Ollama instances with load balancing and failover
    """
    
    def __init__(
        self, 
        instances: List[Dict[str, Any]],
        health_check_interval: int = 30,
        circuit_breaker_config: Optional[Dict[str, Any]] = None
    ):
        self.instances: Dict[str, OllamaInstance] = {}
        self.health_check_interval = health_check_interval
        self.round_robin_index = 0
        self.monitoring_task = None
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Initialize circuit breaker
        cb_config = circuit_breaker_config or {}
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=cb_config.get('failure_threshold', 5),
            recovery_timeout=cb_config.get('recovery_timeout', 60),
            half_open_requests=cb_config.get('half_open_requests', 3)
        )
        
        # Parse instance configurations
        for config in instances:
            instance = OllamaInstance(
                id=config['id'],
                url=config['url'],
                models=config.get('models', []),
                max_concurrent=config.get('max_concurrent', 5),
                tags=config.get('tags', []),
                priority=config.get('priority', 1),
                weight=config.get('weight', 1.0),
                specialization=config.get('specialization')
            )
            self.instances[instance.id] = instance
            
    async def initialize(self):
        """Initialize all instances and start health monitoring"""
        # Create HTTP session
        self.session = aiohttp.ClientSession()
        
        # Initial health check for all instances
        await self._check_all_instances()
        
        # Start monitoring task
        self.monitoring_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Initialized Ollama pool with {len(self.instances)} instances")
        
    async def shutdown(self):
        """Shutdown pool manager"""
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
                
        if self.session:
            await self.session.close()
            
    async def get_instance(
        self, 
        model: Optional[str] = None,
        strategy: str = "least_loaded",
        tags: Optional[List[str]] = None,
        require_healthy: bool = True
    ) -> Optional[str]:
        """
        Get best instance based on strategy
        
        Args:
            model: Required model name
            strategy: Load balancing strategy
            tags: Required instance tags
            require_healthy: Only return healthy instances
            
        Returns:
            Instance URL or None if no suitable instance
        """
        # Filter available instances
        available = self._get_available_instances(
            model=model,
            tags=tags,
            require_healthy=require_healthy
        )
        
        if not available:
            logger.warning(f"No available instances for model={model}, tags={tags}")
            return None
            
        # Select instance based on strategy
        instance = await self._select_instance(
            available,
            LoadBalancingStrategy(strategy),
            model
        )
        
        if instance:
            # Update metrics
            instance.metrics.active_requests += 1
            instance.metrics.total_requests += 1
            return instance.url
            
        return None
        
    async def release_instance(self, url: str):
        """Release instance after request completion"""
        for instance in self.instances.values():
            if instance.url == url:
                instance.metrics.active_requests = max(0, instance.metrics.active_requests - 1)
                break
                
    async def record_success(self, url: str, response_time: float):
        """Record successful request"""
        for instance in self.instances.values():
            if instance.url == url:
                instance.metrics.success_count += 1
                instance.metrics.last_success_time = datetime.now()
                instance.metrics.response_times.append(response_time)
                # Keep only last 100 response times
                if len(instance.metrics.response_times) > 100:
                    instance.metrics.response_times = instance.metrics.response_times[-100:]
                self.circuit_breaker.record_success(instance.id)
                break
                
    async def record_failure(self, url: str, error: Optional[Exception] = None):
        """Record failed request"""
        for instance in self.instances.values():
            if instance.url == url:
                instance.metrics.error_count += 1
                instance.metrics.last_error_time = datetime.now()
                self.circuit_breaker.record_failure(instance.id)
                logger.error(f"Request failed for instance {instance.id}: {error}")
                break
                
    async def health_check(self, instance_id: str) -> bool:
        """Check health of specific instance"""
        if instance_id not in self.instances:
            return False
            
        instance = self.instances[instance_id]
        
        try:
            # Check if Ollama API is responsive
            async with self.session.get(
                f"{instance.url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    # Update loaded models
                    instance.models_loaded = {
                        model['name'] for model in data.get('models', [])
                    }
                    instance.state = InstanceState.HEALTHY
                    return True
                else:
                    instance.state = InstanceState.UNHEALTHY
                    return False
                    
        except asyncio.TimeoutError:
            logger.warning(f"Health check timeout for instance {instance_id}")
            instance.state = InstanceState.DEGRADED
            return False
        except Exception as e:
            logger.error(f"Health check failed for instance {instance_id}: {e}")
            instance.state = InstanceState.UNHEALTHY
            return False
            
    async def get_pool_status(self) -> Dict[str, Any]:
        """Get status of all instances in the pool"""
        status = {
            'total_instances': len(self.instances),
            'healthy_instances': sum(
                1 for i in self.instances.values() 
                if i.state == InstanceState.HEALTHY
            ),
            'degraded_instances': sum(
                1 for i in self.instances.values() 
                if i.state == InstanceState.DEGRADED
            ),
            'unhealthy_instances': sum(
                1 for i in self.instances.values() 
                if i.state == InstanceState.UNHEALTHY
            ),
            'instances': {}
        }
        
        for instance_id, instance in self.instances.items():
            status['instances'][instance_id] = {
                'url': instance.url,
                'state': instance.state.value,
                'active_requests': instance.metrics.active_requests,
                'total_requests': instance.metrics.total_requests,
                'avg_response_time': round(instance.metrics.avg_response_time, 3),
                'error_rate': round(instance.metrics.error_rate * 100, 2),
                'availability': round(instance.metrics.availability, 2),
                'models_loaded': list(instance.models_loaded),
                'circuit_breaker_open': self.circuit_breaker.is_open(instance_id)
            }
            
        return status
        
    # Private methods
    
    async def _monitor_loop(self):
        """Continuous health monitoring loop"""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._check_all_instances()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                
    async def _check_all_instances(self):
        """Check health of all instances"""
        tasks = [
            self.health_check(instance_id) 
            for instance_id in self.instances.keys()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        healthy_count = sum(1 for r in results if r is True)
        logger.debug(f"Health check complete: {healthy_count}/{len(self.instances)} healthy")
        
    def _get_available_instances(
        self,
        model: Optional[str] = None,
        tags: Optional[List[str]] = None,
        require_healthy: bool = True
    ) -> List[OllamaInstance]:
        """Filter instances based on criteria"""
        available = []
        
        for instance in self.instances.values():
            # Check circuit breaker
            if self.circuit_breaker.is_open(instance.id):
                continue
                
            # Check health state
            if require_healthy and instance.state != InstanceState.HEALTHY:
                if instance.state != InstanceState.DEGRADED:
                    continue
                    
            # Check model availability
            if model:
                if model not in instance.models and model not in instance.models_loaded:
                    continue
                    
            # Check tags
            if tags:
                if not all(tag in instance.tags for tag in tags):
                    continue
                    
            # Check concurrent limit
            if instance.metrics.active_requests >= instance.max_concurrent:
                continue
                
            available.append(instance)
            
        return available
        
    async def _select_instance(
        self,
        available: List[OllamaInstance],
        strategy: LoadBalancingStrategy,
        model: Optional[str] = None
    ) -> Optional[OllamaInstance]:
        """Select instance based on strategy"""
        if not available:
            return None
            
        if strategy == LoadBalancingStrategy.ROUND_ROBIN:
            # Simple round robin
            instance = available[self.round_robin_index % len(available)]
            self.round_robin_index += 1
            return instance
            
        elif strategy == LoadBalancingStrategy.RANDOM:
            # Random selection
            return random.choice(available)
            
        elif strategy == LoadBalancingStrategy.LEAST_LOADED:
            # Select instance with least active requests
            return min(available, key=lambda i: i.metrics.active_requests)
            
        elif strategy == LoadBalancingStrategy.LATENCY_BASED:
            # Select instance with lowest average response time
            return min(available, key=lambda i: i.metrics.avg_response_time or float('inf'))
            
        elif strategy == LoadBalancingStrategy.MODEL_AFFINITY:
            # Prefer instances that already have the model loaded
            if model:
                with_model = [i for i in available if model in i.models_loaded]
                if with_model:
                    return min(with_model, key=lambda i: i.metrics.active_requests)
            # Fallback to least loaded
            return min(available, key=lambda i: i.metrics.active_requests)
            
        elif strategy == LoadBalancingStrategy.WEIGHTED:
            # Weighted random selection
            weights = [i.weight for i in available]
            return random.choices(available, weights=weights)[0]
            
        else:
            # Default to least loaded
            return min(available, key=lambda i: i.metrics.active_requests)
