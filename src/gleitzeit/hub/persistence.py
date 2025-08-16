"""
Hub Persistence Adapters for state management and distributed coordination

Provides persistence backends for hub resource state, metrics, and distributed locking.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, TypeVar, Generic
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
import json
import asyncio
import logging

from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType

logger = logging.getLogger(__name__)

T = TypeVar('T')


class HubPersistenceAdapter(ABC):
    """Abstract interface for hub persistence backends"""
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the persistence backend"""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """Cleanup and close connections"""
        pass
    
    @abstractmethod
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None:
        """Persist resource instance state"""
        pass
    
    @abstractmethod
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Load resource instance from storage"""
        pass
    
    @abstractmethod
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
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
    ) -> List[Dict[str, Any]]:
        """Retrieve historical metrics"""
        pass
    
    @abstractmethod
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Acquire distributed lock for resource allocation"""
        pass
    
    @abstractmethod
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        """Release distributed lock"""
        pass
    
    @abstractmethod
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Extend lock timeout"""
        pass
    
    @abstractmethod
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        """Get current lock owner"""
        pass


class RedisHubAdapter(HubPersistenceAdapter):
    """Redis-based persistence for hub state"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379", key_prefix: str = "gleitzeit:hub"):
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.redis = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize Redis connection"""
        if self._initialized:
            return
        
        try:
            import redis.asyncio as redis
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            # Test connection
            await self.redis.ping()
            self._initialized = True
            logger.info(f"Redis hub adapter initialized: {self.redis_url}")
        except ImportError:
            raise ImportError("redis not installed. Install with: pip install redis")
        except Exception as e:
            logger.error(f"Failed to initialize Redis adapter: {e}")
            raise
    
    async def shutdown(self) -> None:
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()
            self._initialized = False
            logger.info("Redis hub adapter shut down")
    
    def _instance_key(self, instance_id: str) -> str:
        """Generate Redis key for instance"""
        return f"{self.key_prefix}:instance:{instance_id}"
    
    def _hub_instances_key(self, hub_id: str) -> str:
        """Generate Redis key for hub's instance set"""
        return f"{self.key_prefix}:instances:{hub_id}"
    
    def _metrics_key(self, instance_id: str) -> str:
        """Generate Redis key for metrics time series"""
        return f"{self.key_prefix}:metrics:{instance_id}"
    
    def _lock_key(self, resource_id: str) -> str:
        """Generate Redis key for resource lock"""
        return f"{self.key_prefix}:lock:{resource_id}"
    
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None:
        """Persist resource instance state"""
        if not self.redis:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            # Convert instance to dict for serialization
            instance_data = {
                'id': instance.id,
                'name': instance.name,
                'type': instance.type.value if isinstance(instance.type, ResourceType) else instance.type,
                'endpoint': instance.endpoint,
                'status': instance.status.value if isinstance(instance.status, ResourceStatus) else instance.status,
                'metadata': instance.metadata,
                'tags': list(instance.tags),
                'capabilities': list(instance.capabilities),
                'health_checks_failed': instance.health_checks_failed,
                'last_health_check': instance.last_health_check.isoformat() if instance.last_health_check else None,
                'created_at': instance.created_at.isoformat(),
                'updated_at': datetime.utcnow().isoformat(),
                'hub_id': hub_id
            }
            
            # Store instance data
            key = self._instance_key(instance.id)
            await self.redis.set(key, json.dumps(instance_data))
            
            # Add to hub's instance set
            hub_key = self._hub_instances_key(hub_id)
            await self.redis.sadd(hub_key, instance.id)
            
            # Set expiration (24 hours) to auto-cleanup stale instances
            await self.redis.expire(key, 86400)
            
            logger.debug(f"Saved instance {instance.id} to Redis")
            
        except Exception as e:
            logger.error(f"Failed to save instance {instance.id}: {e}")
            raise
    
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Load resource instance from storage"""
        if not self.redis:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            key = self._instance_key(instance_id)
            data = await self.redis.get(key)
            
            if data:
                return json.loads(data)
            return None
            
        except Exception as e:
            logger.error(f"Failed to load instance {instance_id}: {e}")
            return None
    
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
        """List all instances for a hub"""
        if not self.redis:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            # Get all instance IDs for this hub
            hub_key = self._hub_instances_key(hub_id)
            instance_ids = await self.redis.smembers(hub_key)
            
            # Load each instance
            instances = []
            for instance_id in instance_ids:
                instance_data = await self.load_instance(instance_id)
                if instance_data:
                    instances.append(instance_data)
                else:
                    # Remove stale reference
                    await self.redis.srem(hub_key, instance_id)
            
            return instances
            
        except Exception as e:
            logger.error(f"Failed to list instances for hub {hub_id}: {e}")
            return []
    
    async def delete_instance(self, instance_id: str) -> None:
        """Remove instance from storage"""
        if not self.redis:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            # Load instance to get hub_id
            instance_data = await self.load_instance(instance_id)
            
            # Delete instance key
            key = self._instance_key(instance_id)
            await self.redis.delete(key)
            
            # Remove from hub's instance set
            if instance_data and 'hub_id' in instance_data:
                hub_key = self._hub_instances_key(instance_data['hub_id'])
                await self.redis.srem(hub_key, instance_id)
            
            # Delete associated metrics
            metrics_key = self._metrics_key(instance_id)
            await self.redis.delete(metrics_key)
            
            logger.debug(f"Deleted instance {instance_id} from Redis")
            
        except Exception as e:
            logger.error(f"Failed to delete instance {instance_id}: {e}")
    
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        """Store metrics snapshot in time series"""
        if not self.redis:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            key = self._metrics_key(instance_id)
            timestamp = int(datetime.utcnow().timestamp())
            
            # Convert metrics to dict
            metrics_data = metrics.to_dict()
            metrics_data['timestamp'] = timestamp
            
            # Add to sorted set (score is timestamp)
            await self.redis.zadd(key, {json.dumps(metrics_data): timestamp})
            
            # Trim old metrics (keep last 24 hours)
            cutoff = timestamp - (24 * 3600)
            await self.redis.zremrangebyscore(key, '-inf', cutoff)
            
            # Set expiration on metrics key
            await self.redis.expire(key, 86400)
            
            logger.debug(f"Saved metrics for instance {instance_id}")
            
        except Exception as e:
            logger.error(f"Failed to save metrics for {instance_id}: {e}")
    
    async def get_metrics_history(
        self, 
        instance_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Retrieve historical metrics"""
        if not self.redis:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            key = self._metrics_key(instance_id)
            start_ts = int(start_time.timestamp())
            end_ts = int(end_time.timestamp())
            
            # Get metrics in time range
            results = await self.redis.zrangebyscore(key, start_ts, end_ts)
            
            # Parse results
            metrics_list = []
            for item in results:
                try:
                    metrics_data = json.loads(item)
                    metrics_list.append(metrics_data)
                except json.JSONDecodeError:
                    continue
            
            return metrics_list
            
        except Exception as e:
            logger.error(f"Failed to get metrics history for {instance_id}: {e}")
            return []
    
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Acquire distributed lock using Redis SET NX"""
        if not self.redis:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            key = self._lock_key(resource_id)
            # SET NX (set if not exists) with expiration
            result = await self.redis.set(key, owner_id, nx=True, ex=timeout)
            
            if result:
                logger.debug(f"Acquired lock for {resource_id} by {owner_id}")
            
            return bool(result)
            
        except Exception as e:
            logger.error(f"Failed to acquire lock for {resource_id}: {e}")
            return False
    
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        """Release distributed lock if owned"""
        if not self.redis:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            key = self._lock_key(resource_id)
            
            # Check if we own the lock
            current_owner = await self.redis.get(key)
            if current_owner == owner_id:
                await self.redis.delete(key)
                logger.debug(f"Released lock for {resource_id} by {owner_id}")
            else:
                logger.warning(f"Cannot release lock for {resource_id}: owned by {current_owner}, not {owner_id}")
                
        except Exception as e:
            logger.error(f"Failed to release lock for {resource_id}: {e}")
    
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Extend lock timeout if owned"""
        if not self.redis:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            key = self._lock_key(resource_id)
            
            # Check if we own the lock
            current_owner = await self.redis.get(key)
            if current_owner == owner_id:
                await self.redis.expire(key, timeout)
                logger.debug(f"Extended lock for {resource_id} by {owner_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to extend lock for {resource_id}: {e}")
            return False
    
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        """Get current lock owner"""
        if not self.redis:
            raise RuntimeError("Redis adapter not initialized")
        
        try:
            key = self._lock_key(resource_id)
            return await self.redis.get(key)
            
        except Exception as e:
            logger.error(f"Failed to get lock owner for {resource_id}: {e}")
            return None


class InMemoryHubAdapter(HubPersistenceAdapter):
    """In-memory persistence adapter for testing"""
    
    def __init__(self):
        self.instances: Dict[str, Dict[str, Any]] = {}
        self.hub_instances: Dict[str, set] = {}
        self.metrics: Dict[str, List[Dict[str, Any]]] = {}
        self.locks: Dict[str, tuple[str, datetime]] = {}  # resource_id -> (owner_id, expiry)
    
    async def initialize(self) -> None:
        """No-op for in-memory adapter"""
        logger.info("In-memory hub adapter initialized")
    
    async def shutdown(self) -> None:
        """Clear all data"""
        self.instances.clear()
        self.hub_instances.clear()
        self.metrics.clear()
        self.locks.clear()
        logger.info("In-memory hub adapter shut down")
    
    async def save_instance(self, hub_id: str, instance: ResourceInstance) -> None:
        """Save instance in memory"""
        instance_data = {
            'id': instance.id,
            'name': instance.name,
            'type': instance.type.value if isinstance(instance.type, ResourceType) else instance.type,
            'endpoint': instance.endpoint,
            'status': instance.status.value if isinstance(instance.status, ResourceStatus) else instance.status,
            'metadata': instance.metadata,
            'tags': list(instance.tags),
            'capabilities': list(instance.capabilities),
            'hub_id': hub_id
        }
        
        self.instances[instance.id] = instance_data
        
        if hub_id not in self.hub_instances:
            self.hub_instances[hub_id] = set()
        self.hub_instances[hub_id].add(instance.id)
    
    async def load_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Load instance from memory"""
        return self.instances.get(instance_id)
    
    async def list_instances(self, hub_id: str) -> List[Dict[str, Any]]:
        """List instances for hub"""
        instance_ids = self.hub_instances.get(hub_id, set())
        return [self.instances[iid] for iid in instance_ids if iid in self.instances]
    
    async def delete_instance(self, instance_id: str) -> None:
        """Delete instance from memory"""
        if instance_id in self.instances:
            instance = self.instances[instance_id]
            hub_id = instance.get('hub_id')
            del self.instances[instance_id]
            
            if hub_id and hub_id in self.hub_instances:
                self.hub_instances[hub_id].discard(instance_id)
    
    async def save_metrics(self, instance_id: str, metrics: ResourceMetrics) -> None:
        """Save metrics in memory"""
        if instance_id not in self.metrics:
            self.metrics[instance_id] = []
        
        metrics_data = metrics.to_dict()
        metrics_data['timestamp'] = datetime.utcnow().isoformat()
        self.metrics[instance_id].append(metrics_data)
        
        # Keep only last 100 entries
        self.metrics[instance_id] = self.metrics[instance_id][-100:]
    
    async def get_metrics_history(
        self, 
        instance_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Get metrics history from memory"""
        if instance_id not in self.metrics:
            return []
        
        # Filter by time range
        result = []
        for m in self.metrics[instance_id]:
            if 'timestamp' in m:
                ts = datetime.fromisoformat(m['timestamp'])
                if start_time <= ts <= end_time:
                    result.append(m)
        return result
    
    async def acquire_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Acquire lock in memory"""
        now = datetime.utcnow()
        
        # Check if lock exists and is not expired
        if resource_id in self.locks:
            current_owner, expiry = self.locks[resource_id]
            if expiry > now:
                return False  # Lock held by someone
        
        # Acquire lock
        self.locks[resource_id] = (owner_id, now + timedelta(seconds=timeout))
        return True
    
    async def release_lock(self, resource_id: str, owner_id: str) -> None:
        """Release lock if owned"""
        if resource_id in self.locks:
            current_owner, _ = self.locks[resource_id]
            if current_owner == owner_id:
                del self.locks[resource_id]
    
    async def extend_lock(self, resource_id: str, owner_id: str, timeout: int = 30) -> bool:
        """Extend lock if owned"""
        if resource_id in self.locks:
            current_owner, _ = self.locks[resource_id]
            if current_owner == owner_id:
                self.locks[resource_id] = (owner_id, datetime.utcnow() + timedelta(seconds=timeout))
                return True
        return False
    
    async def get_lock_owner(self, resource_id: str) -> Optional[str]:
        """Get lock owner"""
        if resource_id in self.locks:
            owner, expiry = self.locks[resource_id]
            if expiry > datetime.utcnow():
                return owner
            else:
                # Lock expired
                del self.locks[resource_id]
        return None