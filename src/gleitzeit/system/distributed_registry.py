"""
Distributed Component Registry for Stateless SystemManager.

Stores all component metadata in Redis/persistence layer for
shared access across multiple SystemManager instances.
"""

import json
import logging
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

from ..persistence.base import PersistenceBackend
from ..core.errors import (
    DistributedRegistryError, PersistenceError, SystemManagerError
)

logger = logging.getLogger(__name__)


@dataclass
class ComponentInfo:
    """Information about a registered component."""
    component_id: str
    component_type: str  # provider, hub, worker
    instance_id: str  # SystemManager instance that registered it
    metadata: Dict[str, Any]
    registered_at: str
    last_heartbeat: str
    status: str = "active"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ComponentInfo':
        """Create from dictionary."""
        return cls(**data)


class DistributedComponentRegistry:
    """
    Distributed registry for system components using persistence backend.
    
    Features:
    - All component state stored in Redis/persistence
    - Support for multiple SystemManager instances
    - Automatic cleanup of stale components
    - Leader election support
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        instance_id: str,
        heartbeat_interval: int = 30,
        component_timeout: int = 120
    ):
        """
        Initialize distributed registry.
        
        Args:
            persistence: Backend for storing registry data
            instance_id: Unique identifier for this SystemManager instance
            heartbeat_interval: How often to update heartbeats (seconds)
            component_timeout: When to consider a component stale (seconds)
        """
        self.persistence = persistence
        self.instance_id = instance_id
        self.heartbeat_interval = heartbeat_interval
        self.component_timeout = component_timeout
        self._prefix = "system:registry:"
        
    def _key(self, *parts) -> str:
        """Build storage key."""
        return self._prefix + ":".join(parts)
    
    async def register_component(
        self,
        component_id: str,
        component_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Register a component in the distributed registry.
        
        Args:
            component_id: Unique component identifier
            component_type: Type of component (provider, hub, worker)
            metadata: Optional component metadata
            
        Returns:
            True if registered successfully
        """
        try:
            now = datetime.utcnow().isoformat()
            
            component = ComponentInfo(
                component_id=component_id,
                component_type=component_type,
                instance_id=self.instance_id,
                metadata=metadata or {},
                registered_at=now,
                last_heartbeat=now,
                status="active"
            )
            
            # Store component info
            key = self._key("component", component_id)
            await self.persistence.set(key, json.dumps(component.to_dict()))
            
            # Add to type index
            type_key = self._key("type", component_type)
            components = await self._get_list(type_key)
            if component_id not in components:
                components.append(component_id)
                await self.persistence.set(type_key, json.dumps(components))
            
            # Add to instance index
            instance_key = self._key("instance", self.instance_id)
            instance_components = await self._get_list(instance_key)
            if component_id not in instance_components:
                instance_components.append(component_id)
                await self.persistence.set(instance_key, json.dumps(instance_components))
            
            # Add to global all components index
            all_key = self._key("all_components")
            all_components = await self._get_list(all_key)
            if component_id not in all_components:
                all_components.append(component_id)
                await self.persistence.set(all_key, json.dumps(all_components))
            
            logger.info(f"Registered component {component_id} ({component_type}) for instance {self.instance_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register component {component_id}: {e}")
            return False
    
    async def unregister_component(self, component_id: str) -> bool:
        """
        Unregister a component from the registry.
        
        Args:
            component_id: Component to unregister
            
        Returns:
            True if unregistered successfully
        """
        try:
            # Get component info
            component = await self.get_component(component_id)
            if not component:
                return False
            
            # Remove from type index
            type_key = self._key("type", component.component_type)
            components = await self._get_list(type_key)
            if component_id in components:
                components.remove(component_id)
                await self.persistence.set(type_key, json.dumps(components))
            
            # Remove from instance index
            instance_key = self._key("instance", component.instance_id)
            instance_components = await self._get_list(instance_key)
            if component_id in instance_components:
                instance_components.remove(component_id)
                await self.persistence.set(instance_key, json.dumps(instance_components))
            
            # Remove from global all components index
            all_key = self._key("all_components")
            all_components = await self._get_list(all_key)
            if component_id in all_components:
                all_components.remove(component_id)
                await self.persistence.set(all_key, json.dumps(all_components))
            
            # Remove component info
            key = self._key("component", component_id)
            await self.persistence.delete(key)
            
            logger.info(f"Unregistered component {component_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to unregister component {component_id}: {e}")
            return False
    
    async def get_component(self, component_id: str) -> Optional[ComponentInfo]:
        """
        Get component information.
        
        Args:
            component_id: Component to get
            
        Returns:
            Component info or None if not found
        """
        key = self._key("component", component_id)
        data = await self.persistence.get(key)
        
        if data:
            # Handle both dict and string formats
            if isinstance(data, dict):
                return ComponentInfo.from_dict(data)
            else:
                return ComponentInfo.from_dict(json.loads(data))
        return None
    
    async def list_components(
        self,
        component_type: Optional[str] = None,
        instance_id: Optional[str] = None,
        active_only: bool = True
    ) -> List[ComponentInfo]:
        """
        List registered components with optional filtering.
        
        Args:
            component_type: Filter by component type
            instance_id: Filter by instance ID
            active_only: Only return active components
            
        Returns:
            List of component information
        """
        components = []
        
        # Get component IDs to check
        if component_type:
            type_key = self._key("type", component_type)
            component_ids = await self._get_list(type_key)
        elif instance_id:
            instance_key = self._key("instance", instance_id)
            component_ids = await self._get_list(instance_key)
        else:
            # Get all components from global index
            all_key = self._key("all_components")
            component_ids = await self._get_list(all_key)
        
        # Get component info for each ID
        for component_id in component_ids:
            component = await self.get_component(component_id)
            if component:
                # Apply filters
                if instance_id and component.instance_id != instance_id:
                    continue
                if active_only and not await self._is_active(component):
                    continue
                components.append(component)
        
        return components
    
    async def update_heartbeat(self, component_id: str) -> bool:
        """
        Update component heartbeat timestamp.
        
        Args:
            component_id: Component to update
            
        Returns:
            True if updated successfully
        """
        component = await self.get_component(component_id)
        if not component:
            return False
        
        component.last_heartbeat = datetime.utcnow().isoformat()
        
        key = self._key("component", component_id)
        await self.persistence.set(key, json.dumps(component.to_dict()))
        return True
    
    async def update_all_heartbeats(self) -> int:
        """
        Update heartbeats for all components owned by this instance.
        
        Returns:
            Number of components updated
        """
        instance_key = self._key("instance", self.instance_id)
        component_ids = await self._get_list(instance_key)
        
        count = 0
        for component_id in component_ids:
            if await self.update_heartbeat(component_id):
                count += 1
        
        return count
    
    async def cleanup_stale_components(self) -> int:
        """
        Remove components that haven't sent heartbeat recently.
        
        Returns:
            Number of components removed
        """
        all_components = await self.list_components(active_only=False)
        removed = 0
        
        for component in all_components:
            if not await self._is_active(component):
                if await self.unregister_component(component.component_id):
                    removed += 1
                    logger.info(f"Removed stale component {component.component_id}")
        
        return removed
    
    async def get_component_counts(self) -> Dict[str, int]:
        """
        Get count of components by type.
        
        Returns:
            Dictionary of type -> count
        """
        counts = {}
        for comp_type in ["provider", "hub", "worker"]:
            components = await self.list_components(component_type=comp_type)
            counts[comp_type] = len(components)
        return counts
    
    async def transfer_ownership(self, component_id: str, new_instance_id: str) -> bool:
        """
        Transfer component ownership to another instance.
        
        Args:
            component_id: Component to transfer
            new_instance_id: New owner instance
            
        Returns:
            True if transferred successfully
        """
        component = await self.get_component(component_id)
        if not component:
            return False
        
        old_instance_id = component.instance_id
        
        # Update instance ID
        component.instance_id = new_instance_id
        
        # Update component info
        key = self._key("component", component_id)
        await self.persistence.set(key, json.dumps(component.to_dict()))
        
        # Update instance indexes
        old_key = self._key("instance", old_instance_id)
        old_components = await self._get_list(old_key)
        if component_id in old_components:
            old_components.remove(component_id)
            await self.persistence.set(old_key, json.dumps(old_components))
        
        new_key = self._key("instance", new_instance_id)
        new_components = await self._get_list(new_key)
        if component_id not in new_components:
            new_components.append(component_id)
            await self.persistence.set(new_key, json.dumps(new_components))
        
        logger.info(f"Transferred component {component_id} from {old_instance_id} to {new_instance_id}")
        return True
    
    async def clear_instance(self, instance_id: Optional[str] = None) -> int:
        """
        Clear all components for an instance.
        
        Args:
            instance_id: Instance to clear (defaults to current)
            
        Returns:
            Number of components removed
        """
        target_instance = instance_id or self.instance_id
        components = await self.list_components(instance_id=target_instance, active_only=False)
        
        removed = 0
        for component in components:
            if await self.unregister_component(component.component_id):
                removed += 1
        
        # Clear instance index
        instance_key = self._key("instance", target_instance)
        await self.persistence.delete(instance_key)
        
        logger.info(f"Cleared {removed} components for instance {target_instance}")
        return removed
    
    # Helper methods
    
    async def _get_list(self, key: str) -> List[str]:
        """Get a JSON list from storage."""
        data = await self.persistence.get(key)
        if data:
            # Handle different data formats
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # Shouldn't be a dict, but handle gracefully
                return []
            elif isinstance(data, bytes):
                return json.loads(data.decode())
            else:
                return json.loads(data)
        return []
    
    async def _scan_keys(self, pattern: str) -> List[str]:
        """Scan for keys matching pattern."""
        # Use the persistence adapter's scan method
        if hasattr(self.persistence, 'scan'):
            keys = []
            cursor = 0
            while True:
                cursor, batch = await self.persistence.scan(cursor, match=pattern, count=100)
                keys.extend(batch)
                if cursor == 0:
                    break
            return keys
        else:
            # Fallback: try to list all keys (less efficient)
            if hasattr(self.persistence, 'list_keys'):
                return await self.persistence.list_keys(pattern)
            return []
    
    async def _is_active(self, component: ComponentInfo) -> bool:
        """Check if a component is still active."""
        if component.status != "active":
            return False
        
        last_heartbeat = datetime.fromisoformat(component.last_heartbeat)
        timeout = timedelta(seconds=self.component_timeout)
        
        return datetime.utcnow() - last_heartbeat < timeout