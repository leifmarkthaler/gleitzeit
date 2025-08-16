"""
Persistent Hub Provider with Redis/SQL backend support

Extends HubProvider with state persistence, distributed coordination,
and metrics history capabilities.
"""

import logging
import asyncio
import uuid
from typing import Dict, Any, Optional, List, TypeVar, Generic, Type
from datetime import datetime, timedelta

from gleitzeit.providers.hub_provider import HubProvider
from gleitzeit.hub.base import ResourceInstance, ResourceStatus
from gleitzeit.hub.persistence import HubPersistenceAdapter, RedisHubAdapter, InMemoryHubAdapter
from gleitzeit.common.load_balancer import LoadBalancingStrategy

logger = logging.getLogger(__name__)

T = TypeVar('T')


class PersistentHubProvider(HubProvider[T]):
    """
    Hub provider with persistence support for state management and distributed coordination.
    
    Features:
    - State persistence across restarts
    - Distributed resource locking
    - Metrics history storage
    - Shared resource pools across instances
    """
    
    def __init__(
        self,
        provider_id: str,
        protocol_id: str,
        name: str,
        description: str,
        resource_config_class: Type[T],
        persistence_adapter: Optional[HubPersistenceAdapter] = None,
        enable_persistence: bool = False,
        persistence_interval: int = 60,  # seconds
        lock_timeout: int = 30,  # seconds
        enable_distributed_locking: bool = True,
        instance_id: Optional[str] = None,  # Unique ID for this provider instance
        **kwargs
    ):
        """
        Initialize persistent hub provider.
        
        Args:
            provider_id: Provider identifier (shared across instances for pooling)
            persistence_adapter: Persistence backend adapter
            enable_persistence: Enable state persistence
            persistence_interval: How often to persist state (seconds)
            lock_timeout: Resource lock timeout (seconds)
            enable_distributed_locking: Use distributed locks for resource allocation
            instance_id: Unique ID for this provider instance (auto-generated if not provided)
            **kwargs: Additional arguments for HubProvider
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id=protocol_id,
            name=name,
            description=description,
            resource_config_class=resource_config_class,
            **kwargs
        )
        
        # Persistence configuration
        self.persistence = persistence_adapter
        self.enable_persistence = enable_persistence and persistence_adapter is not None
        self.persistence_interval = persistence_interval
        self.lock_timeout = lock_timeout
        self.enable_distributed_locking = enable_distributed_locking
        
        # Unique instance ID for distributed coordination
        self.instance_id = instance_id or f"{provider_id}-{uuid.uuid4().hex[:8]}"
        
        # Background tasks
        self._persistence_task: Optional[asyncio.Task] = None
        self._lock_refresh_task: Optional[asyncio.Task] = None
        
        # Track locked resources
        self._locked_resources: Dict[str, datetime] = {}
        
        logger.info(f"Initialized PersistentHubProvider: {provider_id} (instance: {self.instance_id})")
    
    async def initialize(self):
        """Initialize provider with persistence support"""
        # Initialize persistence adapter
        if self.persistence:
            await self.persistence.initialize()
            logger.info(f"Persistence adapter initialized for {self.provider_id}")
        
        # Load persisted state before normal initialization
        if self.enable_persistence:
            await self._load_persisted_state()
        
        # Normal initialization
        await super().initialize()
        
        # Start background tasks
        if self.enable_persistence:
            self._persistence_task = asyncio.create_task(self._persistence_loop())
            logger.info(f"Started persistence loop for {self.provider_id}")
        
        if self.enable_distributed_locking and self.persistence:
            self._lock_refresh_task = asyncio.create_task(self._lock_refresh_loop())
            logger.info(f"Started lock refresh loop for {self.provider_id}")
    
    async def shutdown(self):
        """Shutdown provider and cleanup"""
        logger.info(f"Shutting down PersistentHubProvider: {self.provider_id}")
        
        # Stop background tasks
        if self._persistence_task:
            self._persistence_task.cancel()
            try:
                await self._persistence_task
            except asyncio.CancelledError:
                pass
        
        if self._lock_refresh_task:
            self._lock_refresh_task.cancel()
            try:
                await self._lock_refresh_task
            except asyncio.CancelledError:
                pass
        
        # Final state persistence
        if self.enable_persistence:
            await self._persist_current_state()
        
        # Release all locks
        await self._release_all_locks()
        
        # Normal shutdown
        await super().shutdown()
        
        # Shutdown persistence adapter
        if self.persistence:
            await self.persistence.shutdown()
    
    async def _load_persisted_state(self):
        """Restore state from persistence"""
        if not self.persistence:
            return
        
        try:
            logger.info(f"Loading persisted state for {self.provider_id}")
            
            # Load instances
            persisted_instances = await self.persistence.list_instances(self.provider_id)
            
            for instance_data in persisted_instances:
                try:
                    # Reconstruct instance
                    instance = await self._reconstruct_instance(instance_data)
                    
                    if instance:
                        # Verify instance is still valid
                        if await self.check_resource_health(instance):
                            instance.status = ResourceStatus.HEALTHY
                            self.instances[instance.id] = instance
                            logger.info(f"Restored healthy instance: {instance.id}")
                        else:
                            # Mark as unhealthy but keep it
                            instance.status = ResourceStatus.UNHEALTHY
                            self.instances[instance.id] = instance
                            logger.warning(f"Restored unhealthy instance: {instance.id}")
                    
                except Exception as e:
                    logger.error(f"Failed to restore instance {instance_data.get('id')}: {e}")
            
            logger.info(f"Loaded {len(self.instances)} instances from persistence")
            
        except Exception as e:
            logger.error(f"Failed to load persisted state: {e}")
    
    async def _reconstruct_instance(self, instance_data: Dict[str, Any]) -> Optional[ResourceInstance]:
        """Reconstruct instance from persisted data"""
        try:
            from gleitzeit.hub.base import ResourceType
            
            # Create instance
            instance = ResourceInstance(
                id=instance_data['id'],
                name=instance_data['name'],
                type=ResourceType[instance_data['type'].upper()] if isinstance(instance_data['type'], str) else instance_data['type'],
                endpoint=instance_data['endpoint'],
                status=ResourceStatus[instance_data['status'].upper()] if isinstance(instance_data['status'], str) else ResourceStatus.UNKNOWN,
                metadata=instance_data.get('metadata', {}),
                tags=set(instance_data.get('tags', [])),
                capabilities=set(instance_data.get('capabilities', [])),
                config=None  # Config reconstruction depends on provider implementation
            )
            
            return instance
            
        except Exception as e:
            logger.error(f"Failed to reconstruct instance: {e}")
            return None
    
    async def _persist_current_state(self):
        """Save current state to persistence"""
        if not self.persistence:
            return
        
        try:
            for instance in self.instances.values():
                # Save instance state
                await self.persistence.save_instance(self.provider_id, instance)
                
                # Save current metrics
                await self.persistence.save_metrics(instance.id, instance.metrics)
            
            logger.debug(f"Persisted state for {len(self.instances)} instances")
            
        except Exception as e:
            logger.error(f"Failed to persist state: {e}")
    
    async def _persistence_loop(self):
        """Periodically persist state"""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(self.persistence_interval)
                await self._persist_current_state()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in persistence loop: {e}")
    
    async def _lock_refresh_loop(self):
        """Refresh locks for resources we're using"""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(self.lock_timeout / 2)  # Refresh at half timeout
                await self._refresh_locks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in lock refresh loop: {e}")
    
    async def _refresh_locks(self):
        """Refresh all held locks"""
        if not self.persistence:
            return
        
        for resource_id in list(self._locked_resources.keys()):
            try:
                success = await self.persistence.extend_lock(
                    resource_id, 
                    self.instance_id, 
                    self.lock_timeout
                )
                if success:
                    self._locked_resources[resource_id] = datetime.utcnow()
                else:
                    # Lost the lock
                    del self._locked_resources[resource_id]
                    logger.warning(f"Lost lock for resource {resource_id}")
                    
            except Exception as e:
                logger.error(f"Failed to refresh lock for {resource_id}: {e}")
    
    async def _release_all_locks(self):
        """Release all held locks"""
        if not self.persistence:
            return
        
        for resource_id in list(self._locked_resources.keys()):
            try:
                await self.persistence.release_lock(resource_id, self.instance_id)
                del self._locked_resources[resource_id]
            except Exception as e:
                logger.error(f"Failed to release lock for {resource_id}: {e}")
    
    async def register_instance(self, instance: ResourceInstance[T]):
        """Register instance with persistence"""
        await super().register_instance(instance)
        
        # Persist immediately
        if self.enable_persistence and self.persistence:
            await self.persistence.save_instance(self.provider_id, instance)
    
    async def unregister_instance(self, instance_id: str):
        """Unregister instance and remove from persistence"""
        instance = await super().unregister_instance(instance_id)
        
        # Remove from persistence
        if instance and self.enable_persistence and self.persistence:
            await self.persistence.delete_instance(instance_id)
        
        return instance
    
    async def get_instance(
        self,
        requirements: Optional[Dict[str, Any]] = None,
        strategy: Optional[LoadBalancingStrategy] = None
    ) -> Optional[ResourceInstance[T]]:
        """Get instance with distributed locking support"""
        
        # Try multiple times to get a locked resource
        max_attempts = 3
        for attempt in range(max_attempts):
            # Get instance using normal selection
            instance = await super().get_instance(requirements, strategy)
            
            if not instance:
                return None
            
            # If distributed locking is disabled, return immediately
            if not self.enable_distributed_locking or not self.persistence:
                return instance
            
            # Try to acquire lock
            lock_acquired = await self.persistence.acquire_lock(
                instance.id,
                self.instance_id,
                self.lock_timeout
            )
            
            if lock_acquired:
                self._locked_resources[instance.id] = datetime.utcnow()
                logger.debug(f"Acquired lock for instance {instance.id}")
                return instance
            
            # Check who owns the lock
            owner = await self.persistence.get_lock_owner(instance.id)
            if owner == self.instance_id:
                # We already own it
                return instance
            
            logger.debug(f"Instance {instance.id} locked by {owner}, trying another")
        
        logger.warning(f"Failed to get unlocked instance after {max_attempts} attempts")
        return None
    
    async def release_instance(self, instance_id: str):
        """Release instance and its lock"""
        if instance_id in self._locked_resources and self.persistence:
            await self.persistence.release_lock(instance_id, self.instance_id)
            del self._locked_resources[instance_id]
            logger.debug(f"Released lock for instance {instance_id}")
    
    async def get_metrics_history(
        self,
        instance_id: str,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Get historical metrics for an instance"""
        if not self.persistence:
            return []
        
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)
        
        return await self.persistence.get_metrics_history(
            instance_id,
            start_time,
            end_time
        )
    
    async def get_all_metrics_history(self, hours: int = 24) -> Dict[str, List[Dict[str, Any]]]:
        """Get historical metrics for all instances"""
        result = {}
        
        for instance_id in self.instances.keys():
            result[instance_id] = await self.get_metrics_history(instance_id, hours)
        
        return result
    
    async def get_distributed_status(self) -> Dict[str, Any]:
        """Get status including distributed lock information"""
        status = await self.get_status()
        
        # Add persistence info
        status['persistence'] = {
            'enabled': self.enable_persistence,
            'adapter': self.persistence.__class__.__name__ if self.persistence else None,
            'distributed_locking': self.enable_distributed_locking,
            'locked_resources': len(self._locked_resources),
            'instance_id': self.instance_id
        }
        
        # Add lock status for each instance
        if self.persistence and self.enable_distributed_locking:
            for instance_id, instance_status in status['instances'].items():
                owner = await self.persistence.get_lock_owner(instance_id)
                instance_status['lock'] = {
                    'locked': owner is not None,
                    'owner': owner,
                    'owned_by_us': owner == self.instance_id
                }
        
        return status