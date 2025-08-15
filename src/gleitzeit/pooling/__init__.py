"""
Gleitzeit V4 Pooling System

Event-driven provider pooling with dynamic scaling, load balancing,
and fault tolerance. Integrates with the existing task queue and
execution engine infrastructure.

Key Components:
- PoolingAdapter: Main integration point with ExecutionEngine  
- PoolManager: Orchestrates multiple pools and routes tasks
- ProviderPool: Manages a pool of workers for a specific protocol
- ProviderWorker: Individual worker that executes tasks
- CircuitBreaker: Prevents cascade failures through circuit breaker pattern
- BackpressureManager: Monitors resource usage and prevents overload

Key Features:
- Dynamic scaling based on load metrics
- Fault tolerance with circuit breakers
- Backpressure management and resource monitoring
- Event-driven coordination through centralized event system
- Integration with existing queue and persistence infrastructure
- Support for multiple protocols simultaneously
"""

from gleitzeit.pooling.adapter import PoolingAdapter
from gleitzeit.pooling.manager import PoolManager
from gleitzeit.pooling.pool import ProviderPool
from gleitzeit.pooling.worker import ProviderWorker, WorkerState
from gleitzeit.pooling.circuit_breaker import CircuitBreaker, CircuitState
from gleitzeit.pooling.backpressure import BackpressureManager

__all__ = [
    # Main Components
    'PoolingAdapter',
    'PoolManager',
    'ProviderPool', 
    'ProviderWorker',
    
    # State and Utilities
    'WorkerState',
    'CircuitBreaker',
    'CircuitState',
    'BackpressureManager',
]