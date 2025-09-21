"""
Dependency injection for Gleitzeit API.

This module provides FastAPI dependencies for injecting shared resources
like client pools into route handlers, enabling stateless operation.
"""

import socket
import logging
from typing import AsyncGenerator, Optional, TYPE_CHECKING
from contextlib import asynccontextmanager

from fastapi import Request, Depends
from fastapi.security import HTTPAuthorizationCredentials
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.core.errors import SystemError, ErrorCode

if TYPE_CHECKING:
    from gleitzeit.core.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)

# Global reference to shared client pool
_shared_client_pool = None
# Global reference to shared SystemManager
_shared_system_manager = None


async def _get_or_create_system_manager(persistence):
    """
    Get or create a StreamSystemManager for this API instance.

    Uses the StreamSystemManager.get_or_create() which provides
    enterprise-scale stream-based processing capabilities.

    Args:
        persistence: The persistence backend to use

    Returns:
        StreamSystemManager instance or None
    """
    global _shared_system_manager

    if _shared_system_manager is not None:
        return _shared_system_manager

    from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
    from gleitzeit.system.models import SystemConfig, DeploymentMode

    # Use the new modular stream-based system manager
    logger.info("Getting or creating ModularStreamSystemManager for API instance")

    # Create system config
    config = SystemConfig()
    config.deployment_mode = DeploymentMode.PRODUCTION

    system_manager = await ModularStreamSystemManager.create(
        config=config,
        persistence=persistence,
        stream_config={
            "total_shards": 64,
            "consumer_group": "gleitzeit-api-processors",
            "monitoring_interval": 30
        },
        create_if_missing=True,
        start_system=False  # Don't auto-start to avoid blocking
    )

    # Start system after creation
    if system_manager:
        await system_manager.start_system()

    if system_manager:
        logger.info("ModularStreamSystemManager ready for API")
        _shared_system_manager = system_manager
    else:
        logger.error("Could not get or create ModularStreamSystemManager")
        raise SystemError(
            message="Failed to initialize ModularStreamSystemManager",
            code=ErrorCode.SYSTEM_NOT_INITIALIZED
        )

    return system_manager


async def get_shared_client_pool(request: Optional[Request] = None):
    """
    Get or create the shared client pool instance.
    
    This creates a distributed client pool that coordinates
    across multiple API instances using the persistence backend.
    
    Args:
        request: Optional FastAPI request to get service token from app state
    
    Returns:
        SharedClientPool instance
    """
    global _shared_client_pool
    
    if _shared_client_pool is None:
        # Import here to avoid circular imports
        from gleitzeit.api.shared_dependencies import SharedClientPool
        from gleitzeit.client import GleitzeitClient
        import os
        
        # Get persistence backend (shared with SystemManager)
        persistence = await PersistenceFactory.create()
        
        # Try to discover existing SystemManager or create a new one
        system_manager = await _get_or_create_system_manager(persistence)
        
        # Create connection to shared pool
        instance_id = f"api_{socket.gethostname()}_{os.getpid()}"
        
        _shared_client_pool = SharedClientPool(
            persistence=persistence,
            instance_id=instance_id,
            max_size=20,  # Total across all API instances
            mode=ClientMode.NATIVE,  # Use NATIVE mode to avoid circular deps
            system_manager=system_manager  # Pass system manager for direct access
        )
        await _shared_client_pool.initialize()
    
    return _shared_client_pool


async def get_client_pool():
    """
    Compatibility wrapper - returns SharedClientPool.
    
    Returns:
        The SharedClientPool instance
    """
    return await get_shared_client_pool()


async def get_pooled_client() -> AsyncGenerator[GleitzeitClient, None]:
    """
    FastAPI dependency that provides a pooled client.
    
    This dependency acquires a client from the pool for the request
    and returns it to the pool when the request completes.
    
    Yields:
        An initialized GleitzeitClient instance
    """
    pool = await get_client_pool()
    client = await pool.acquire()
    
    try:
        yield client
    finally:
        await pool.release(client)


async def get_request_client(request: Request) -> GleitzeitClient:
    """
    FastAPI dependency that provides a per-request client.
    
    This creates a new client for each request and stores it
    in the request state for reuse within the same request.
    
    Args:
        request: The FastAPI request object
        
    Returns:
        An initialized GleitzeitClient instance
    """
    # Check if we already have a client for this request
    if hasattr(request.state, 'gleitzeit_client'):
        return request.state.gleitzeit_client
    
    # Create a new client for this request
    # Get system manager for NATIVE mode
    system_manager = get_system_manager()
    
    client = GleitzeitClient(
        mode=ClientMode.NATIVE,  # Use NATIVE mode for direct access
        event_mode='direct',
        system_manager=system_manager  # Pass system manager for direct access
    )
    await client.initialize()
    
    # Store in request state for reuse
    request.state.gleitzeit_client = client
    
    # Register cleanup
    request.state.cleanup_tasks = getattr(request.state, 'cleanup_tasks', [])
    request.state.cleanup_tasks.append(client.shutdown)
    
    return client


# Original pooled client dependency (without user context)
get_client_without_auth = get_pooled_client

async def get_client_with_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None,
    client: GleitzeitClient = Depends(get_pooled_client)
) -> GleitzeitClient:
    """
    Get a pooled client with user context set for authorization.
    
    This dependency:
    1. Gets a pooled client
    2. Gets the current user context
    3. Sets the user context on the client (for Native adapter auth)
    4. Returns the configured client
    """
    # Import here to avoid circular dependency
    from .routes.auth import get_current_user_helper
    
    # Get system manager
    system_manager = await get_system_manager()
    
    # Get current user context
    user_context = await get_current_user_helper(request, credentials, system_manager)
    
    # Set user context on the client for authorization
    if hasattr(client, 'set_user_context'):
        client.set_user_context(user_context)
    
    return client

# Convenience alias for the preferred dependency
get_client = get_client_with_auth  # Use auth-aware clients by default


@asynccontextmanager
async def client_lifespan():
    """
    Manage client pool lifecycle for the application.
    
    This context manager initializes the client pool on startup
    and shuts it down on application shutdown.
    
    Usage:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with client_lifespan():
                yield
    """
    # Startup
    pool = await get_client_pool()
    logger.info("Client pool initialized for API")
    
    yield
    
    # Shutdown
    if pool:
        await pool.shutdown()
        logger.info("Client pool shutdown complete")


async def initialize_client_pool():
    """Initialize the client pool (for backward compatibility)."""
    await get_client_pool()


async def shutdown_client_pool():
    """Shutdown the client pool (for backward compatibility)."""
    global _shared_client_pool, _shared_system_manager
    
    if _shared_client_pool:
        await _shared_client_pool.shutdown()
        _shared_client_pool = None
    
    # Only shutdown SystemManager if we created it (not if we're using an existing one)
    if _shared_system_manager:
        try:
            await _shared_system_manager.shutdown_system()
            await _shared_system_manager.shutdown()
            logger.info("SystemManager shutdown complete")
        except Exception as e:
            logger.error(f"Error shutting down SystemManager: {e}")
        _shared_system_manager = None


async def get_system_manager():
    """
    Get the shared SystemManager instance.
    
    Returns:
        SystemManager instance or None if unavailable
    """
    global _shared_system_manager
    
    if _shared_system_manager is None:
        # Initialize the shared client pool which creates the SystemManager
        await get_shared_client_pool()
    
    return _shared_system_manager


async def get_workflow_manager(
    client: GleitzeitClient = Depends(get_pooled_client)
) -> Optional["WorkflowManager"]:
    """
    Get WorkflowManager instance via StreamSystemManager.

    This dependency provides access to the WorkflowManager for advanced
    workflow operations like templates, scheduling, and execution policies.
    Uses StreamSystemManager for pure stream-based event flow.

    Args:
        client: Pooled client instance

    Returns:
        WorkflowManager instance or None if unavailable
    """
    try:
        # Get StreamSystemManager as primary coordinator
        system_manager = await get_system_manager()
        if system_manager:
            # Use the system manager's workflow manager which has the correct execution engine
            workflow_manager = system_manager.workflow_manager
            if workflow_manager:
                logger.debug("Got WorkflowManager from StreamSystemManager")
                return workflow_manager

            # If no workflow manager exists, create one from system manager using streams
            from gleitzeit.core.workflow_manager_factory import WorkflowManagerFactory
            workflow_manager = await WorkflowManagerFactory.create_from_system_manager(system_manager)
            logger.info("Created WorkflowManager from StreamSystemManager")
            return workflow_manager

        # Fallback: create with direct stream integration (no EventBus wrapper)
        from gleitzeit.core.workflow_manager_factory import WorkflowManagerFactory
        persistence = await PersistenceFactory.create()

        # Get StreamSystemManager for direct stream integration
        stream_manager = await _get_or_create_system_manager(persistence)

        workflow_manager = await WorkflowManagerFactory.create(
            persistence=persistence,
            event_bus=stream_manager,  # Use StreamSystemManager directly
            execution_engine=None,
            dependency_resolver=None
        )
        logger.info("Created WorkflowManager with direct StreamSystemManager integration")
        return workflow_manager

    except Exception as e:
        logger.error(f"Error getting WorkflowManager: {e}")
        return None


