"""
Shared dependency injection for distributed API instances.

This module provides shared client pool management using persistence
backend for coordination across multiple API instances.
"""

import asyncio
import logging
import json
from typing import Optional, AsyncGenerator, Dict, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import Depends, Request, HTTPException
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.core.errors import (
    ClientPoolError, ClientPoolExhaustedError, PersistenceError,
    SharedResourceError
)

logger = logging.getLogger(__name__)


class SharedClientPool:
    """
    Distributed client pool that coordinates across API instances.
    
    Uses persistence backend to manage pool state and coordinate
    client allocation across multiple API servers.
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        instance_id: str,
        max_size: int = 20,
        mode: ClientMode = ClientMode.NATIVE,
        idle_timeout: int = 300,
        system_manager: Optional[Any] = None
    ):
        """
        Initialize shared client pool with stream integration.

        Args:
            persistence: Backend for pool coordination
            instance_id: Unique API instance identifier
            max_size: Maximum total clients across all instances
            mode: Client mode for all pooled clients
            idle_timeout: Seconds before idle client cleanup
            system_manager: System manager (preferably StreamSystemManager)
        """
        self.persistence = persistence
        self.instance_id = instance_id
        self.max_size = max_size
        self.mode = mode
        self.idle_timeout = idle_timeout
        self.system_manager = system_manager  # System manager for Native mode

        # Stream integration
        self._is_stream_enabled = False
        if system_manager and hasattr(system_manager, '__class__'):
            self._is_stream_enabled = 'Stream' in system_manager.__class__.__name__
        
        self._prefix = "api:client_pool:"
        self._local_clients: Dict[str, GleitzeitClient] = {}
        self._lock = asyncio.Lock()
        self._initialized = False
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def _key(self, *parts) -> str:
        """Build storage key."""
        return self._prefix + ":".join(parts)
    
    async def initialize(self):
        """Initialize the shared pool."""
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            # Register this instance
            await self._register_instance()

            # Start cleanup task
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

            self._initialized = True
            stream_status = "stream-enabled" if self._is_stream_enabled else "standard"
            logger.info(f"SharedClientPool initialized for instance {self.instance_id} ({stream_status})")
    
    async def _register_instance(self):
        """Register this API instance in the pool registry."""
        instance_key = self._key("instance", self.instance_id)
        instance_info = {
            "instance_id": self.instance_id,
            "registered_at": datetime.utcnow().isoformat(),
            "last_heartbeat": datetime.utcnow().isoformat(),
            "max_local_clients": self.max_size // 4,  # Each instance gets a portion
            "stream_enabled": self._is_stream_enabled,
            "system_manager_type": self.system_manager.__class__.__name__ if self.system_manager else "none"
        }
        await self.persistence.set(instance_key, json.dumps(instance_info))
        
        # Add to active instances set
        instances_key = self._key("active_instances")
        instances = await self._get_list(instances_key)
        if self.instance_id not in instances:
            instances.append(self.instance_id)
            await self.persistence.set(instances_key, json.dumps(instances))
    
    async def acquire(self) -> GleitzeitClient:
        """
        Acquire a client from the shared pool.
        
        Returns:
            An initialized GleitzeitClient instance
        """
        if not self._initialized:
            await self.initialize()
        
        # First try to get a local client
        client = await self._acquire_local()
        if client:
            return client
        
        # Try to acquire from shared pool
        client = await self._acquire_shared()
        if client:
            return client
        
        # Create new if under limit
        if await self._can_create_client():
            return await self._create_and_register()
        
        # Pool is exhausted
        raise ClientPoolExhaustedError(self.instance_id, self.max_size)
    
    async def _acquire_local(self) -> Optional[GleitzeitClient]:
        """Try to acquire from local cache."""
        async with self._lock:
            # Find an available local client
            for client_id, client in list(self._local_clients.items()):
                if client.is_initialized():
                    # Mark as in-use
                    await self._mark_client_in_use(client_id)
                    return client
                else:
                    # Remove dead client
                    del self._local_clients[client_id]
        return None
    
    async def _acquire_shared(self) -> Optional[GleitzeitClient]:
        """Try to acquire from shared pool."""
        # Get list of available clients
        available_key = self._key("available")
        available = await self._get_list(available_key)
        
        for client_id in available:
            # Try to claim this client
            if await self._claim_client(client_id):
                # Load or create the client locally
                client = await self._load_or_create_client(client_id)
                if client:
                    self._local_clients[client_id] = client
                    return client
        
        return None
    
    async def _can_create_client(self) -> bool:
        """Check if we can create a new client."""
        # Count total clients across all instances
        total_key = self._key("total_count")
        count = await self.persistence.get(total_key)
        current_count = int(count) if count else 0
        return current_count < self.max_size
    
    async def _create_and_register(self) -> GleitzeitClient:
        """Create and register a new client."""
        import uuid
        client_id = f"client_{uuid.uuid4().hex[:12]}"
        
        # Register in persistence
        client_info = {
            "client_id": client_id,
            "instance_id": self.instance_id,
            "created_at": datetime.utcnow().isoformat(),
            "last_used": datetime.utcnow().isoformat(),
            "status": "in_use"
        }
        client_key = self._key("client", client_id)
        await self.persistence.set(client_key, json.dumps(client_info))
        
        # Increment total count
        total_key = self._key("total_count")
        if hasattr(self.persistence, 'incr'):
            await self.persistence.incr(total_key)
        else:
            count = await self.persistence.get(total_key)
            await self.persistence.set(total_key, str((int(count) if count else 0) + 1))
        
        # Create actual client
        # Pass system_manager if using NATIVE mode
        client_kwargs = {'mode': self.mode, 'event_mode': 'direct'}
        if self.mode == ClientMode.NATIVE and self.system_manager:
            client_kwargs['system_manager'] = self.system_manager
        
        # STATELESS: Each client will discover SystemManager through persistence
        # We don't pass instances - that violates stateless architecture
        client = GleitzeitClient(**client_kwargs)
        await client.initialize()
        
        # The NativeAdapter will connect to the distributed system via persistence
        logger.debug(f"Created stateless client {client_id}")
        
        self._local_clients[client_id] = client
        logger.debug(f"Created new client {client_id}")
        
        return client
    
    async def release(self, client: GleitzeitClient):
        """
        Return a client to the shared pool.
        
        Args:
            client: The client to return to the pool
        """
        # Find client ID
        client_id = None
        for cid, c in self._local_clients.items():
            if c == client:
                client_id = cid
                break
        
        if not client_id:
            # Unknown client, just shut it down
            try:
                await client.shutdown()
            except:
                pass
            return
        
        # Mark as available if still healthy
        if client.is_initialized():
            await self._mark_client_available(client_id)
        else:
            # Remove unhealthy client
            await self._remove_client(client_id)
    
    async def _mark_client_in_use(self, client_id: str):
        """Mark a client as in use."""
        # Update client info
        client_key = self._key("client", client_id)
        client_data = await self.persistence.get(client_key)
        if client_data:
            # Handle both JSON string and dict returns
            if isinstance(client_data, dict):
                info = client_data
            else:
                info = json.loads(client_data)
            info["status"] = "in_use"
            info["last_used"] = datetime.utcnow().isoformat()
            info["instance_id"] = self.instance_id
            await self.persistence.set(client_key, json.dumps(info))
        
        # Remove from available list
        available_key = self._key("available")
        available = await self._get_list(available_key)
        if client_id in available:
            available.remove(client_id)
            await self.persistence.set(available_key, json.dumps(available))
    
    async def _mark_client_available(self, client_id: str):
        """Mark a client as available."""
        # Update client info
        client_key = self._key("client", client_id)
        client_data = await self.persistence.get(client_key)
        if client_data:
            # Handle both JSON string and dict returns
            if isinstance(client_data, dict):
                info = client_data
            else:
                info = json.loads(client_data)
            info["status"] = "available"
            info["last_used"] = datetime.utcnow().isoformat()
            await self.persistence.set(client_key, json.dumps(info))
        
        # Add to available list
        available_key = self._key("available")
        available = await self._get_list(available_key)
        if client_id not in available:
            available.append(client_id)
            await self.persistence.set(available_key, json.dumps(available))
    
    async def _claim_client(self, client_id: str) -> bool:
        """Try to claim a client atomically."""
        client_key = self._key("client", client_id)
        client_data = await self.persistence.get(client_key)
        
        if not client_data:
            return False
        
        # Handle both JSON string and dict returns
        if isinstance(client_data, dict):
            info = client_data
        else:
            info = json.loads(client_data)
        
        # Check if available
        if info.get("status") != "available":
            return False
        
        # Try to claim (this should be atomic in production with Redis)
        info["status"] = "in_use"
        info["instance_id"] = self.instance_id
        info["last_used"] = datetime.utcnow().isoformat()
        await self.persistence.set(client_key, json.dumps(info))
        
        # Remove from available list
        available_key = self._key("available")
        available = await self._get_list(available_key)
        if client_id in available:
            available.remove(client_id)
            await self.persistence.set(available_key, json.dumps(available))
        
        return True
    
    async def _load_or_create_client(self, client_id: str) -> Optional[GleitzeitClient]:
        """Load existing client or create new one."""
        # Check if we have it locally
        if client_id in self._local_clients:
            return self._local_clients[client_id]
        
        # Create new client instance
        # Pass system_manager if using NATIVE mode
        client_kwargs = {'mode': self.mode, 'event_mode': 'direct'}
        if self.mode == ClientMode.NATIVE and self.system_manager:
            client_kwargs['system_manager'] = self.system_manager
        
        client = GleitzeitClient(**client_kwargs)
        try:
            await client.initialize()
            
            # Set SystemManager on native adapter if available
            if self.system_manager and self.mode == ClientMode.NATIVE:
                if hasattr(client, '_adapter') and hasattr(client._adapter, 'set_system_manager'):
                    client._adapter.set_system_manager(self.system_manager)
                    logger.debug(f"Set SystemManager on client {client_id}")
            
            return client
        except ClientPoolError as e:
            logger.error(f"Failed to create client {client_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating client {client_id}: {e}")
            raise ClientPoolError(f"Failed to create client {client_id}", cause=e)
    
    async def _remove_client(self, client_id: str):
        """Remove a client from the pool."""
        # Shutdown local client
        if client_id in self._local_clients:
            try:
                await self._local_clients[client_id].shutdown()
            except:
                pass
            del self._local_clients[client_id]
        
        # Remove from persistence
        client_key = self._key("client", client_id)
        await self.persistence.delete(client_key)
        
        # Remove from available list
        available_key = self._key("available")
        available = await self._get_list(available_key)
        if client_id in available:
            available.remove(client_id)
            await self.persistence.set(available_key, json.dumps(available))
        
        # Decrement total count
        total_key = self._key("total_count")
        count = await self.persistence.get(total_key)
        if count:
            new_count = max(0, int(count) - 1)
            await self.persistence.set(total_key, str(new_count))
    
    async def _cleanup_loop(self):
        """Periodically clean up idle clients."""
        while self._initialized:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_idle_clients()
                await self._update_heartbeat()
            except (PersistenceError, SharedResourceError) as e:
                logger.error(f"Error in cleanup loop: {e}")
            except Exception as e:
                logger.error(f"Unexpected error in cleanup loop: {e}")
                # Don't raise in background loop
    
    async def _cleanup_idle_clients(self):
        """Remove clients that have been idle too long."""
        available_key = self._key("available")
        available = await self._get_list(available_key)
        
        now = datetime.utcnow()
        removed = []
        
        for client_id in available:
            client_key = self._key("client", client_id)
            client_data = await self.persistence.get(client_key)
            
            if client_data:
                # Handle both JSON string and dict returns
                if isinstance(client_data, dict):
                    info = client_data
                else:
                    info = json.loads(client_data)
                last_used = datetime.fromisoformat(info["last_used"])
                
                if (now - last_used).total_seconds() > self.idle_timeout:
                    await self._remove_client(client_id)
                    removed.append(client_id)
        
        if removed:
            logger.info(f"Cleaned up {len(removed)} idle clients")
    
    async def _update_heartbeat(self):
        """Update instance heartbeat."""
        instance_key = self._key("instance", self.instance_id)
        instance_data = await self.persistence.get(instance_key)
        
        if instance_data:
            # Handle both JSON string and dict returns
            if isinstance(instance_data, dict):
                info = instance_data
            else:
                info = json.loads(instance_data)
            info["last_heartbeat"] = datetime.utcnow().isoformat()
            await self.persistence.set(instance_key, json.dumps(info))
    
    async def _get_list(self, key: str) -> list:
        """Get a JSON list from persistence."""
        data = await self.persistence.get(key)
        if data is None:
            return []
        # Handle both JSON string and direct list returns
        if isinstance(data, list):
            return data
        return json.loads(data)
    
    async def shutdown(self):
        """Shutdown the shared pool."""
        logger.info(f"Shutting down SharedClientPool for instance {self.instance_id}")
        
        # Stop cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Release all local clients
        async with self._lock:
            for client_id, client in self._local_clients.items():
                try:
                    await self._mark_client_available(client_id)
                    await client.shutdown()
                except Exception as e:
                    logger.error(f"Error shutting down client {client_id}: {e}")
            
            self._local_clients.clear()
        
        # Unregister instance
        instance_key = self._key("instance", self.instance_id)
        await self.persistence.delete(instance_key)
        
        # Remove from active instances
        instances_key = self._key("active_instances")
        instances = await self._get_list(instances_key)
        if self.instance_id in instances:
            instances.remove(self.instance_id)
            await self.persistence.set(instances_key, json.dumps(instances))
        
        self._initialized = False
        logger.info("SharedClientPool shutdown complete")

    def is_stream_enabled(self) -> bool:
        """Check if this pool uses stream-enabled system manager."""
        return self._is_stream_enabled

    async def get_stream_health(self) -> Dict[str, Any]:
        """Get stream system health if available."""
        if not self._is_stream_enabled or not self.system_manager:
            return {"error": "Stream integration not available"}

        try:
            if hasattr(self.system_manager, 'get_system_health'):
                return await self.system_manager.get_system_health()
            else:
                return {"error": "System manager does not support stream health"}
        except Exception as e:
            logger.error(f"Error getting stream health from SharedClientPool: {e}")
            return {"error": str(e)}

    async def get_pool_statistics(self) -> Dict[str, Any]:
        """Get pool statistics including stream integration status."""
        try:
            # Get basic pool stats
            stats = {
                "instance_id": self.instance_id,
                "max_size": self.max_size,
                "mode": self.mode.value,
                "local_clients": len(self._local_clients),
                "stream_enabled": self._is_stream_enabled,
                "system_manager_type": self.system_manager.__class__.__name__ if self.system_manager else None
            }

            # Add stream-specific stats if available
            if self._is_stream_enabled and self.system_manager:
                try:
                    if hasattr(self.system_manager, 'get_stream_statistics'):
                        stream_stats = await self.system_manager.get_stream_statistics()
                        stats["stream_statistics"] = stream_stats
                except Exception as e:
                    logger.debug(f"Could not get stream statistics: {e}")

            return stats

        except Exception as e:
            logger.error(f"Error getting pool statistics: {e}")
            return {"error": str(e)}


# Global shared pool instance
_shared_pool: Optional[SharedClientPool] = None
_persistence: Optional[PersistenceBackend] = None


async def get_shared_pool() -> SharedClientPool:
    """
    Get or create the shared client pool.
    
    Returns:
        The initialized shared client pool
    """
    global _shared_pool, _persistence
    
    if _shared_pool is None:
        # Get persistence backend
        if _persistence is None:
            _persistence = await PersistenceFactory.create()
        
        # Generate instance ID
        import socket
        import os
        instance_id = f"{socket.gethostname()}_{os.getpid()}"
        
        _shared_pool = SharedClientPool(
            persistence=_persistence,
            instance_id=instance_id,
            max_size=20,  # Total across all instances
            mode=ClientMode.NATIVE
        )
        await _shared_pool.initialize()
    
    return _shared_pool


async def get_shared_client() -> AsyncGenerator[GleitzeitClient, None]:
    """
    FastAPI dependency that provides a client from the shared pool.
    
    This dependency acquires a client from the distributed pool
    and returns it when the request completes.
    
    Yields:
        An initialized GleitzeitClient instance
    """
    pool = await get_shared_pool()
    client = await pool.acquire()
    
    try:
        yield client
    finally:
        await pool.release(client)


@asynccontextmanager
async def shared_client_lifespan():
    """
    Manage shared client pool lifecycle for the application.
    
    This should be used in the FastAPI lifespan context.
    """
    # Startup
    pool = await get_shared_pool()
    logger.info("Shared client pool initialized for API")
    
    yield
    
    # Shutdown
    if _shared_pool:
        await _shared_pool.shutdown()
        logger.info("Shared client pool shutdown complete")


# Export for use in routes
get_client = get_shared_client  # Use shared pool by default


# System Manager dependency - gets from shared pool client
async def get_system_manager():
    """
    Get SystemManager instance from shared client pool.

    This dependency extracts the SystemManager from a pooled client
    for use in API routes that need direct system access.

    Returns:
        SystemManager instance
    """
    pool = await get_shared_pool()
    client = await pool.acquire()

    try:
        # Get system manager from the client's adapter
        if hasattr(client, '_adapter') and hasattr(client._adapter, 'system_manager'):
            return client._adapter.system_manager
        elif hasattr(client, '_adapter') and hasattr(client._adapter, 'execution_engine'):
            # For API clients, get via execution engine
            return client._adapter.execution_engine.system_manager
        else:
            # Fallback - try to get the system manager from the shared pool
            if hasattr(pool, 'system_manager'):
                return pool.system_manager
            else:
                raise HTTPException(
                    status_code=503,
                    detail="SystemManager not available in current configuration"
                )
    finally:
        await pool.release(client)


# Auth dependencies placeholders
async def get_current_user_optional():
    """
    Optional authentication dependency.

    Returns None if no user is authenticated, or user info if authenticated.
    This is a placeholder implementation.
    """
    # TODO: Implement proper authentication
    return None


async def require_admin():
    """
    Require admin authentication dependency.

    This is a placeholder implementation that allows all access.
    In production, this should validate admin credentials.
    """
    # TODO: Implement proper admin authentication
    return {"username": "admin", "role": "admin"}