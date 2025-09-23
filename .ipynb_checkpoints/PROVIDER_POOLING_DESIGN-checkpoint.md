# Provider Pooling Architecture

## Overview

Provider pooling creates multiple instances of each provider type to handle concurrent requests efficiently. Instead of a single provider instance becoming a bottleneck, we maintain a pool of instances that can process requests in parallel.

## How Pooling Works

### 1. Pool Creation

When the system starts, it creates multiple instances of each provider:

```python
# src/gleitzeit/providers/pool.py

class ProviderPool:
    """Manages a pool of provider instances for a specific protocol"""

    def __init__(self, protocol: str, provider_class: Type[Provider], config: Dict):
        self.protocol = protocol
        self.provider_class = provider_class
        self.config = config

        # Pool configuration
        self.min_size = config.get('min_instances', 2)
        self.max_size = config.get('max_instances', 10)
        self.current_size = 0

        # Instance tracking
        self.available = asyncio.Queue()  # Available instances
        self.in_use = {}  # Map of request_id -> instance
        self.all_instances = []  # All instances

        # Metrics
        self.requests_processed = 0
        self.total_wait_time = 0

    async def initialize(self):
        """Create initial pool of providers"""
        for i in range(self.min_size):
            await self._create_instance()

    async def _create_instance(self):
        """Create a new provider instance"""
        instance = self.provider_class(self.config)
        wrapper = PooledProvider(
            instance=instance,
            pool=self,
            instance_id=f"{self.protocol}_{self.current_size}"
        )

        self.all_instances.append(wrapper)
        await self.available.put(wrapper)
        self.current_size += 1

        return wrapper
```

### 2. Request Distribution

When a request comes in, the pool assigns it to an available provider:

```python
class ProviderPool:

    async def acquire(self, timeout: float = 5.0) -> 'PooledProvider':
        """Get an available provider from the pool"""
        start_time = time.time()

        try:
            # Try to get an available instance
            instance = await asyncio.wait_for(
                self.available.get(),
                timeout=timeout
            )

            self.total_wait_time += time.time() - start_time
            return instance

        except asyncio.TimeoutError:
            # No available instances, check if we can scale up
            if self.current_size < self.max_size:
                # Create new instance on demand
                return await self._create_instance()
            else:
                raise ProviderPoolExhausted(
                    f"No available providers in pool for {self.protocol}"
                )

    async def release(self, instance: 'PooledProvider'):
        """Return a provider to the pool"""
        instance.in_use = False
        instance.last_used = time.time()
        await self.available.put(instance)
```

### 3. Wrapped Provider Instance

Each provider in the pool is wrapped to track usage:

```python
class PooledProvider:
    """Wrapper around a provider instance in the pool"""

    def __init__(self, instance: Provider, pool: ProviderPool, instance_id: str):
        self.instance = instance
        self.pool = pool
        self.instance_id = instance_id

        # Usage tracking
        self.in_use = False
        self.requests_handled = 0
        self.errors = 0
        self.total_execution_time = 0
        self.last_used = time.time()
        self.created_at = time.time()

    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """Execute request and track metrics"""
        self.in_use = True
        self.requests_handled += 1
        start_time = time.time()

        try:
            # Execute on the wrapped instance
            response = await self.instance.execute(request)

            # Track success metrics
            self.total_execution_time += time.time() - start_time

            return response

        except Exception as e:
            # Track error metrics
            self.errors += 1
            raise

        finally:
            # Always release back to pool
            await self.pool.release(self)

    @property
    def health_score(self) -> float:
        """Calculate health score for this instance"""
        if self.requests_handled == 0:
            return 1.0

        error_rate = self.errors / self.requests_handled
        avg_execution_time = self.total_execution_time / self.requests_handled

        # Penalize high error rates and slow execution
        score = (1 - error_rate) * (1 / (1 + avg_execution_time))
        return max(0, min(1, score))
```

### 4. Load Balancing Strategies

Different strategies for selecting which instance to use:

```python
class LoadBalancer(ABC):
    """Base class for load balancing strategies"""

    @abstractmethod
    async def select(self, pool: ProviderPool) -> PooledProvider:
        pass

class RoundRobinBalancer(LoadBalancer):
    """Simple round-robin selection"""

    def __init__(self):
        self.counters = {}

    async def select(self, pool: ProviderPool) -> PooledProvider:
        """Get next instance in rotation"""
        return await pool.acquire()

class LeastConnectionsBalancer(LoadBalancer):
    """Select instance with fewest active connections"""

    async def select(self, pool: ProviderPool) -> PooledProvider:
        """Get instance with minimum load"""
        # In this case, the queue naturally provides this
        return await pool.acquire()

class WeightedBalancer(LoadBalancer):
    """Select based on health scores"""

    async def select(self, pool: ProviderPool) -> PooledProvider:
        """Get healthiest instance"""
        instance = await pool.acquire()

        # If unhealthy, try to get a better one
        if instance.health_score < 0.5 and pool.available.qsize() > 0:
            await pool.release(instance)
            instance = await pool.acquire()

        return instance
```

### 5. Auto-Scaling

The pool can automatically scale based on metrics:

```python
class AutoScaler:
    """Handles automatic scaling of provider pools"""

    def __init__(self, pool: ProviderPool):
        self.pool = pool
        self.check_interval = 10  # seconds
        self.scale_up_threshold = 0.8  # 80% utilization
        self.scale_down_threshold = 0.2  # 20% utilization

    async def start(self):
        """Start monitoring and scaling"""
        while True:
            await asyncio.sleep(self.check_interval)
            await self.check_and_scale()

    async def check_and_scale(self):
        """Check metrics and scale if needed"""
        utilization = self.calculate_utilization()

        if utilization > self.scale_up_threshold:
            await self.scale_up()
        elif utilization < self.scale_down_threshold:
            await self.scale_down()

    def calculate_utilization(self) -> float:
        """Calculate pool utilization"""
        available_count = self.pool.available.qsize()
        total_count = self.pool.current_size

        if total_count == 0:
            return 0

        return 1 - (available_count / total_count)

    async def scale_up(self):
        """Add more instances to the pool"""
        if self.pool.current_size >= self.pool.max_size:
            return

        # Add 20% more instances or at least 1
        to_add = max(1, int(self.pool.current_size * 0.2))
        to_add = min(to_add, self.pool.max_size - self.pool.current_size)

        for _ in range(to_add):
            await self.pool._create_instance()

        logging.info(f"Scaled up {self.pool.protocol} pool to {self.pool.current_size} instances")

    async def scale_down(self):
        """Remove idle instances from the pool"""
        if self.pool.current_size <= self.pool.min_size:
            return

        # Remove instances idle for more than 60 seconds
        now = time.time()
        to_remove = []

        for instance in self.pool.all_instances:
            if not instance.in_use and now - instance.last_used > 60:
                to_remove.append(instance)

        for instance in to_remove[:len(to_remove)//2]:  # Remove at most half
            self.pool.all_instances.remove(instance)
            self.pool.current_size -= 1

        logging.info(f"Scaled down {self.pool.protocol} pool to {self.pool.current_size} instances")
```

### 6. Pool Manager

Manages all pools across different provider types:

```python
class PoolManager:
    """Manages all provider pools"""

    def __init__(self, redis_cluster):
        self.redis = redis_cluster
        self.pools: Dict[str, ProviderPool] = {}
        self.scalers: Dict[str, AutoScaler] = {}
        self.balancer = WeightedBalancer()

    async def create_pool(
        self,
        protocol: str,
        provider_class: Type[Provider],
        config: Dict
    ):
        """Create and initialize a provider pool"""
        pool = ProviderPool(protocol, provider_class, config)
        await pool.initialize()

        self.pools[protocol] = pool

        # Start auto-scaler
        scaler = AutoScaler(pool)
        self.scalers[protocol] = scaler
        asyncio.create_task(scaler.start())

        return pool

    async def execute(
        self,
        protocol: str,
        request: ExecutionRequest
    ) -> ExecutionResponse:
        """Execute request using pooled provider"""
        pool = self.pools.get(protocol)
        if not pool:
            raise ValueError(f"No pool for protocol: {protocol}")

        # Get instance from pool
        instance = await self.balancer.select(pool)

        # Execute request
        return await instance.execute(request)

    async def get_pool_metrics(self, protocol: str) -> Dict:
        """Get metrics for a specific pool"""
        pool = self.pools.get(protocol)
        if not pool:
            return {}

        return {
            "protocol": protocol,
            "current_size": pool.current_size,
            "min_size": pool.min_size,
            "max_size": pool.max_size,
            "available": pool.available.qsize(),
            "in_use": pool.current_size - pool.available.qsize(),
            "requests_processed": pool.requests_processed,
            "average_wait_time": pool.total_wait_time / max(1, pool.requests_processed),
            "instances": [
                {
                    "id": inst.instance_id,
                    "health_score": inst.health_score,
                    "requests_handled": inst.requests_handled,
                    "errors": inst.errors,
                    "in_use": inst.in_use
                }
                for inst in pool.all_instances
            ]
        }
```

## Usage Example

```python
# Initialize the pool manager
pool_manager = PoolManager(redis_cluster)

# Create pools for each provider type
await pool_manager.create_pool(
    protocol="python/v2",
    provider_class=PythonProvider,
    config={
        "min_instances": 2,
        "max_instances": 10,
        "max_workers": 4  # Per instance
    }
)

await pool_manager.create_pool(
    protocol="http/v2",
    provider_class=HTTPProvider,
    config={
        "min_instances": 3,
        "max_instances": 20,
        "timeout": 30
    }
)

# Execute requests - pooling is handled transparently
response = await pool_manager.execute(
    protocol="python/v2",
    request=ExecutionRequest(
        request_id="req-123",
        method="exec",
        params={"code": "result = sum(range(100))"}
    )
)

# Get pool metrics
metrics = await pool_manager.get_pool_metrics("python/v2")
print(f"Python pool: {metrics['in_use']}/{metrics['current_size']} instances in use")
```

## Benefits of This Pooling Approach

### 1. **Concurrency**
- Multiple requests can be processed simultaneously
- No single provider instance becomes a bottleneck

### 2. **Fault Isolation**
- If one instance crashes, others continue working
- Bad instances can be removed from the pool

### 3. **Resource Management**
- Instances are reused, avoiding creation/destruction overhead
- Memory and CPU usage is bounded by max pool size

### 4. **Auto-Scaling**
- Pools grow under load, shrink when idle
- Efficient resource utilization

### 5. **Health-Based Routing**
- Requests preferentially go to healthy instances
- Failing instances naturally get less traffic

## Configuration

```yaml
# config/pools.yaml

pools:
  python/v2:
    min_instances: 2
    max_instances: 10
    scale_up_threshold: 0.8    # 80% busy
    scale_down_threshold: 0.2  # 20% busy
    idle_timeout: 60           # seconds before removing idle instance

  http/v2:
    min_instances: 5
    max_instances: 50
    scale_up_threshold: 0.7
    scale_down_threshold: 0.3
    idle_timeout: 30

  llm/v2:
    min_instances: 1
    max_instances: 5
    scale_up_threshold: 0.9    # LLMs are expensive, scale conservatively
    scale_down_threshold: 0.1
    idle_timeout: 120
```

## Monitoring

The pool publishes metrics to Redis for monitoring:

```python
async def publish_metrics(self):
    """Publish pool metrics to Redis"""
    for protocol, pool in self.pools.items():
        metrics = await self.get_pool_metrics(protocol)

        await self.redis.hset(
            f"metrics:pool:{protocol}",
            mapping={
                "timestamp": time.time(),
                "data": json.dumps(metrics)
            }
        )

        # Publish event for monitoring systems
        await self.redis.publish(
            "pool:metrics",
            json.dumps({
                "protocol": protocol,
                "utilization": (pool.current_size - pool.available.qsize()) / pool.current_size,
                "queue_depth": pool.available.qsize(),
                "total_instances": pool.current_size
            })
        )
```

This design ensures efficient resource utilization while maintaining high availability and performance.