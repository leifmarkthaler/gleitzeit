"""
Generic load balancing strategies for resource selection
"""
from typing import List, Dict, Any, Optional, Protocol, TypeVar, Generic
from enum import Enum
from dataclasses import dataclass
import random
import hashlib
from abc import ABC, abstractmethod

T = TypeVar('T')


class LoadBalancingStrategy(Enum):
    """Available load balancing strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    RANDOM = "random"
    WEIGHTED_RANDOM = "weighted_random"
    LEAST_RESPONSE_TIME = "least_response_time"
    HASH_BASED = "hash_based"
    PRIORITY_BASED = "priority_based"
    ADAPTIVE = "adaptive"


@dataclass
class ResourceInfo:
    """Information about a resource for load balancing"""
    id: str
    weight: float = 1.0
    priority: int = 1
    active_requests: int = 0
    avg_response_time: float = 0.0
    error_rate: float = 0.0
    capabilities: set = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = set()
        if self.metadata is None:
            self.metadata = {}


class LoadBalancerStrategy(ABC):
    """Base class for load balancing strategies"""
    
    @abstractmethod
    def select(
        self,
        resources: List[ResourceInfo],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ResourceInfo]:
        """Select a resource based on the strategy"""
        pass


class RoundRobinStrategy(LoadBalancerStrategy):
    """Round-robin load balancing"""
    
    def __init__(self):
        self.index = 0
    
    def select(
        self,
        resources: List[ResourceInfo],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ResourceInfo]:
        if not resources:
            return None
        
        selected = resources[self.index % len(resources)]
        self.index += 1
        return selected


class RandomStrategy(LoadBalancerStrategy):
    """Random selection"""
    
    def select(
        self,
        resources: List[ResourceInfo],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ResourceInfo]:
        if not resources:
            return None
        return random.choice(resources)


class LeastLoadedStrategy(LoadBalancerStrategy):
    """Select least loaded resource"""
    
    def select(
        self,
        resources: List[ResourceInfo],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ResourceInfo]:
        if not resources:
            return None
        return min(resources, key=lambda r: r.active_requests)


class WeightedRandomStrategy(LoadBalancerStrategy):
    """Weighted random selection"""
    
    def select(
        self,
        resources: List[ResourceInfo],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ResourceInfo]:
        if not resources:
            return None
        
        weights = [r.weight for r in resources]
        return random.choices(resources, weights=weights)[0]


class LeastResponseTimeStrategy(LoadBalancerStrategy):
    """Select resource with lowest average response time"""
    
    def select(
        self,
        resources: List[ResourceInfo],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ResourceInfo]:
        if not resources:
            return None
        
        # Filter out resources with no response time data
        with_data = [r for r in resources if r.avg_response_time > 0]
        if not with_data:
            # Fallback to random if no data
            return random.choice(resources)
        
        return min(with_data, key=lambda r: r.avg_response_time)


class HashBasedStrategy(LoadBalancerStrategy):
    """Consistent hash-based selection"""
    
    def select(
        self,
        resources: List[ResourceInfo],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ResourceInfo]:
        if not resources:
            return None
        
        # Get hash key from context
        hash_key = ""
        if context:
            hash_key = context.get('hash_key', '')
            if not hash_key:
                # Try common keys
                hash_key = (
                    context.get('session_id', '') or
                    context.get('user_id', '') or
                    context.get('request_id', '')
                )
        
        if hash_key:
            # Consistent hash
            hash_value = int(hashlib.md5(str(hash_key).encode()).hexdigest(), 16)
            index = hash_value % len(resources)
            return resources[index]
        else:
            # Fallback to random
            return random.choice(resources)


class PriorityBasedStrategy(LoadBalancerStrategy):
    """Select based on priority, then least loaded within same priority"""
    
    def select(
        self,
        resources: List[ResourceInfo],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ResourceInfo]:
        if not resources:
            return None
        
        # Group by priority
        by_priority = {}
        for resource in resources:
            priority = resource.priority
            if priority not in by_priority:
                by_priority[priority] = []
            by_priority[priority].append(resource)
        
        # Select from highest priority group
        highest_priority = max(by_priority.keys())
        candidates = by_priority[highest_priority]
        
        # Within same priority, select least loaded
        return min(candidates, key=lambda r: r.active_requests)


class AdaptiveStrategy(LoadBalancerStrategy):
    """
    Adaptive strategy that considers multiple factors
    """
    
    def __init__(
        self,
        load_weight: float = 0.4,
        response_time_weight: float = 0.3,
        error_rate_weight: float = 0.3
    ):
        self.load_weight = load_weight
        self.response_time_weight = response_time_weight
        self.error_rate_weight = error_rate_weight
    
    def select(
        self,
        resources: List[ResourceInfo],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ResourceInfo]:
        if not resources:
            return None
        
        # Calculate score for each resource
        scores = []
        
        # Normalize metrics
        max_requests = max(r.active_requests for r in resources) or 1
        max_response_time = max(r.avg_response_time for r in resources) or 1
        max_error_rate = max(r.error_rate for r in resources) or 0.01
        
        for resource in resources:
            # Lower is better for all metrics
            load_score = 1 - (resource.active_requests / max_requests)
            
            response_score = 1.0
            if max_response_time > 0:
                response_score = 1 - (resource.avg_response_time / max_response_time)
            
            error_score = 1.0
            if max_error_rate > 0:
                error_score = 1 - (resource.error_rate / max_error_rate)
            
            # Weighted score
            total_score = (
                load_score * self.load_weight +
                response_score * self.response_time_weight +
                error_score * self.error_rate_weight
            )
            
            scores.append((resource, total_score))
        
        # Select resource with highest score
        return max(scores, key=lambda x: x[1])[0]


class LoadBalancer:
    """
    Main load balancer that manages different strategies
    """
    
    def __init__(self, default_strategy: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_LOADED):
        self.default_strategy = default_strategy
        self.strategies = {
            LoadBalancingStrategy.ROUND_ROBIN: RoundRobinStrategy(),
            LoadBalancingStrategy.RANDOM: RandomStrategy(),
            LoadBalancingStrategy.LEAST_LOADED: LeastLoadedStrategy(),
            LoadBalancingStrategy.WEIGHTED_RANDOM: WeightedRandomStrategy(),
            LoadBalancingStrategy.LEAST_RESPONSE_TIME: LeastResponseTimeStrategy(),
            LoadBalancingStrategy.HASH_BASED: HashBasedStrategy(),
            LoadBalancingStrategy.PRIORITY_BASED: PriorityBasedStrategy(),
            LoadBalancingStrategy.ADAPTIVE: AdaptiveStrategy()
        }
    
    def select_resource(
        self,
        resources: List[ResourceInfo],
        strategy: Optional[LoadBalancingStrategy] = None,
        required_capabilities: Optional[set] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[ResourceInfo]:
        """
        Select a resource using the specified strategy
        
        Args:
            resources: Available resources
            strategy: Load balancing strategy to use
            required_capabilities: Filter resources by capabilities
            context: Additional context for selection
            
        Returns:
            Selected resource or None
        """
        if not resources:
            return None
        
        # Filter by capabilities if required
        if required_capabilities:
            resources = [
                r for r in resources
                if required_capabilities.issubset(r.capabilities)
            ]
            
            if not resources:
                return None
        
        # Get strategy
        strategy = strategy or self.default_strategy
        strategy_impl = self.strategies.get(strategy)
        
        if not strategy_impl:
            # Fallback to default
            strategy_impl = self.strategies[self.default_strategy]
        
        # Select resource
        return strategy_impl.select(resources, context)
    
    def add_custom_strategy(
        self,
        name: str,
        strategy: LoadBalancerStrategy
    ):
        """Add a custom load balancing strategy"""
        self.strategies[name] = strategy
    
    def get_strategy_stats(self) -> Dict[str, Any]:
        """Get statistics about strategy usage"""
        return {
            'default_strategy': self.default_strategy.value,
            'available_strategies': [s.value for s in self.strategies.keys()]
        }