# Hub Persistence Integration Design

## Overview
This document explores integrating Redis/SQL persistence backends directly into the hub architecture for resource state management, metrics storage, and distributed coordination.

## Why It Makes Sense

### Current State
- Hubs manage resource instances in memory only
- State is lost on restart
- No sharing between multiple Gleitzeit instances
- Metrics are ephemeral

### Benefits of Persistence Integration

1. **State Persistence**
   - Resource instances preserved across restarts
   - Metrics history for analysis
   - Health check history

2. **Distributed Coordination**
   - Multiple Gleitzeit instances can share resource pools
   - Centralized resource discovery
   - Distributed locking for resource allocation

3. **Observability**
   - Historical metrics for capacity planning
   - Performance trends over time
   - Resource utilization patterns

4. **Reliability**
   - Automatic recovery after crashes
   - Resource reservation system
   - Queue persistence for fault tolerance

## Proposed Architecture

```
┌──────────────────────────────────────┐
│         HubProvider                  │
│  ┌──────────────────────────────┐    │
│  │   PersistenceAdapter          │    │
│  │  ┌──────────┬──────────┐     │    │
│  │  │  Redis   │   SQL    │     │    │
│  │  └──────────┴──────────┘     │    │
│  └──────────────────────────────┘    │
│                                       │
│  Resources │ Metrics │ Health │ Queue│
└──────────────────────────────────────┘
```

## Implementation Approach

### 1. PersistenceAdapter Interface

```python
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import asyncio

class HubPersistenceAdapter(ABC):
    """Abstract interface for hub persistence backends"""
    
    @abstractmethod
    async def save_instance(self, instance: ResourceInstance) -> None:
        """Persist resource instance state"""
        pass
    
    @abstractmethod
    async def load_instance(self, instance_id: str) -> Optional[ResourceInstance]:
        """Load resource instance from storage"""
        pass
    
    @abstractmethod
    async def list_instances(self, hub_id: str) -> List[ResourceInstance]:
        """List all instances for a hub"""
        pass
    
    @abstractmethod
    async def delete_instance(self, instance_id: str) -> None:
        """Remove instance from storage"""
        pass
    
    @abstractmethod
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        """Store metrics snapshot"""
        pass
    
    @abstractmethod
    async def get_metrics_history(
        self, 
        instance_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[ResourceMetrics]:
        """Retrieve historical metrics"""
        pass
    
    @abstractmethod
    async def acquire_lock(self, resource_id: str, timeout: int = 30) -> bool:
        """Acquire distributed lock for resource allocation"""
        pass
    
    @abstractmethod
    async def release_lock(self, resource_id: str) -> None:
        """Release distributed lock"""
        pass
```

### 2. Redis Adapter Implementation

```python
class RedisHubAdapter(HubPersistenceAdapter):
    """Redis-based persistence for hub state"""
    
    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url)
        self.key_prefix = "gleitzeit:hub"
    
    async def save_instance(self, instance: ResourceInstance) -> None:
        key = f"{self.key_prefix}:instance:{instance.id}"
        data = json.dumps(instance.to_dict())
        await self.redis.set(key, data)
        # Also add to hub's instance set
        hub_key = f"{self.key_prefix}:instances:{instance.metadata.get('hub_id')}"
        await self.redis.sadd(hub_key, instance.id)
    
    async def load_instance(self, instance_id: str) -> Optional[ResourceInstance]:
        key = f"{self.key_prefix}:instance:{instance_id}"
        data = await self.redis.get(key)
        if data:
            return ResourceInstance.from_dict(json.loads(data))
        return None
    
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        # Store in time series
        key = f"{self.key_prefix}:metrics:{instance_id}"
        timestamp = int(datetime.utcnow().timestamp())
        await self.redis.zadd(key, {json.dumps(metrics.to_dict()): timestamp})
        # Trim old metrics (keep last 24 hours)
        cutoff = timestamp - (24 * 3600)
        await self.redis.zremrangebyscore(key, 0, cutoff)
    
    async def acquire_lock(self, resource_id: str, timeout: int = 30) -> bool:
        lock_key = f"{self.key_prefix}:lock:{resource_id}"
        return await self.redis.set(lock_key, "1", nx=True, ex=timeout)
```

### 3. SQL Adapter Implementation

```python
class SQLHubAdapter(HubPersistenceAdapter):
    """SQL-based persistence for hub state"""
    
    def __init__(self, connection_string: str):
        self.engine = create_async_engine(connection_string)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
    
    async def save_instance(self, instance: ResourceInstance) -> None:
        async with self.async_session() as session:
            # Convert to ORM model
            db_instance = DBResourceInstance(
                id=instance.id,
                name=instance.name,
                type=instance.type.value,
                endpoint=instance.endpoint,
                status=instance.status.value,
                metadata=json.dumps(instance.metadata),
                config=json.dumps(instance.config.__dict__ if instance.config else {}),
                created_at=instance.created_at,
                updated_at=datetime.utcnow()
            )
            await session.merge(db_instance)
            await session.commit()
    
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        async with self.async_session() as session:
            db_metrics = DBResourceMetrics(
                instance_id=instance_id,
                timestamp=datetime.utcnow(),
                request_count=metrics.request_count,
                error_count=metrics.error_count,
                avg_response_time_ms=metrics.avg_response_time_ms,
                # ... other fields
            )
            session.add(db_metrics)
            await session.commit()
```

### 4. Enhanced HubProvider with Persistence

```python
class HubProvider(ProtocolProvider, Generic[T], ABC):
    def __init__(
        self,
        provider_id: str,
        # ... existing params
        persistence_adapter: Optional[HubPersistenceAdapter] = None,
        enable_persistence: bool = False,
        persistence_interval: int = 60  # seconds
    ):
        super().__init__(...)
        self.persistence = persistence_adapter
        self.enable_persistence = enable_persistence and persistence_adapter is not None
        self.persistence_interval = persistence_interval
        self._persistence_task = None
        
    async def initialize(self):
        """Initialize with persistence support"""
        await super().initialize()
        
        if self.enable_persistence:
            # Load existing instances from persistence
            await self._load_persisted_state()
            
            # Start periodic persistence task
            self._persistence_task = asyncio.create_task(
                self._persistence_loop()
            )
    
    async def _load_persisted_state(self):
        """Restore state from persistence"""
        if not self.persistence:
            return
            
        try:
            instances = await self.persistence.list_instances(self.provider_id)
            for instance in instances:
                # Verify instance is still valid
                if await self.check_resource_health(instance):
                    self.instances[instance.id] = instance
                    logger.info(f"Restored instance from persistence: {instance.id}")
                else:
                    # Clean up invalid instance
                    await self.persistence.delete_instance(instance.id)
        except Exception as e:
            logger.error(f"Failed to load persisted state: {e}")
    
    async def _persistence_loop(self):
        """Periodically persist state"""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(self.persistence_interval)
                await self._persist_current_state()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Persistence loop error: {e}")
    
    async def _persist_current_state(self):
        """Save current state to persistence"""
        if not self.persistence:
            return
            
        for instance in self.instances.values():
            try:
                # Save instance state
                await self.persistence.save_instance(instance)
                
                # Save metrics
                await self.persistence.save_metrics(
                    instance.id, 
                    instance.metrics
                )
            except Exception as e:
                logger.error(f"Failed to persist instance {instance.id}: {e}")
    
    async def get_instance(
        self,
        requirements: Optional[Dict[str, Any]] = None,
        strategy: Optional[LoadBalancingStrategy] = None
    ) -> Optional[ResourceInstance[T]]:
        """Get instance with distributed locking"""
        
        instance = await super().get_instance(requirements, strategy)
        
        if instance and self.persistence:
            # Try to acquire lock for distributed coordination
            lock_acquired = await self.persistence.acquire_lock(
                instance.id, 
                timeout=30
            )
            if not lock_acquired:
                # Try another instance
                return await self.get_instance(requirements, strategy)
        
        return instance
```

## Use Cases

### 1. Distributed Ollama Pool
Multiple Gleitzeit instances sharing a pool of Ollama servers:

```python
# Instance 1
redis_adapter = RedisHubAdapter("redis://shared-redis:6379")
ollama_provider = OllamaProvider(
    provider_id="ollama-pool-1",
    persistence_adapter=redis_adapter,
    enable_persistence=True
)

# Instance 2 (different machine)
redis_adapter = RedisHubAdapter("redis://shared-redis:6379")
ollama_provider = OllamaProvider(
    provider_id="ollama-pool-1",  # Same ID for shared pool
    persistence_adapter=redis_adapter,
    enable_persistence=True
)
```

### 2. Metrics Dashboard
Query historical metrics for monitoring:

```python
async def get_provider_metrics(provider_id: str, hours: int = 24):
    adapter = SQLHubAdapter("postgresql://localhost/gleitzeit")
    
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours)
    
    metrics = await adapter.get_metrics_history(
        provider_id,
        start_time,
        end_time
    )
    
    # Generate dashboard data
    return {
        'timeline': [m.timestamp for m in metrics],
        'request_rate': [m.request_count for m in metrics],
        'error_rate': [m.error_count for m in metrics],
        'response_times': [m.avg_response_time_ms for m in metrics]
    }
```

### 3. Auto-scaling Based on Historical Data
Use persisted metrics to predict resource needs:

```python
async def auto_scale_resources(provider: HubProvider):
    if not provider.persistence:
        return
    
    # Get last hour of metrics
    metrics = await provider.persistence.get_metrics_history(
        provider.provider_id,
        datetime.utcnow() - timedelta(hours=1),
        datetime.utcnow()
    )
    
    # Calculate average load
    avg_load = sum(m.active_connections for m in metrics) / len(metrics)
    
    # Scale based on load
    if avg_load > 0.8 and len(provider.instances) < provider.max_instances:
        # Create new instance
        config = provider.create_default_config()
        instance = await provider.create_resource(config)
        await provider.register_instance(instance)
```

## Configuration

### Via Environment Variables
```bash
# Redis persistence
GLEITZEIT_HUB_PERSISTENCE=redis
GLEITZEIT_REDIS_URL=redis://localhost:6379

# SQL persistence
GLEITZEIT_HUB_PERSISTENCE=sql
GLEITZEIT_SQL_URL=postgresql://user:pass@localhost/gleitzeit
```

### Via Configuration File
```yaml
hub:
  persistence:
    type: redis  # or sql
    redis:
      url: redis://localhost:6379
      key_prefix: gleitzeit:hub
    sql:
      url: postgresql://localhost/gleitzeit
      pool_size: 10
  
  providers:
    ollama:
      enable_persistence: true
      persistence_interval: 60  # seconds
    python:
      enable_persistence: false  # Don't persist Docker containers
```

## Benefits Summary

1. **Resilience**: Survive restarts without losing state
2. **Scalability**: Share resources across multiple instances
3. **Observability**: Historical metrics for analysis
4. **Coordination**: Distributed locking prevents conflicts
5. **Efficiency**: Better resource utilization through sharing

## Implementation Priority

1. **Phase 1**: Redis adapter for state persistence
2. **Phase 2**: Metrics storage and retrieval
3. **Phase 3**: Distributed locking for coordination
4. **Phase 4**: SQL adapter for long-term storage
5. **Phase 5**: Auto-scaling based on metrics

## Conclusion

Integrating persistence into the hub architecture makes perfect sense for production deployments. It provides resilience, enables distributed coordination, and improves observability without adding significant complexity. The modular adapter pattern keeps it optional for simpler deployments.