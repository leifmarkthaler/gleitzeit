"""
Unified shutdown utilities for Gleitzeit components

Provides a consistent shutdown sequence for CLI, API, and Client components.
"""

import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


async def unified_shutdown(
    execution_engine: Optional[Any] = None,
    resource_manager: Optional[Any] = None,
    persistence_backend: Optional[Any] = None,
    registry: Optional[Any] = None,
    verbose: bool = False
) -> None:
    """
    Unified shutdown sequence for all Gleitzeit components.
    
    Shutdown order:
    1. Stop execution engine (stops accepting new tasks)
    2. Shutdown all providers (clean up connections)
    3. Stop resource manager and hubs (release resources)
    4. Shutdown persistence backend (close DB connections)
    
    Args:
        execution_engine: ExecutionEngine instance to stop
        resource_manager: ResourceManager instance to stop
        persistence_backend: Persistence adapter to shutdown
        registry: Optional registry to get providers from (if not in engine)
        verbose: Whether to log info messages (not just warnings)
    """
    
    # Step 1: Stop execution engine if running
    if execution_engine and hasattr(execution_engine, 'stop'):
        try:
            await execution_engine.stop()
            if verbose:
                logger.info("Execution engine stopped")
        except Exception as e:
            logger.warning(f"Failed to stop execution engine: {e}")
    
    # Step 2: Shutdown all providers
    # Try to get registry from execution engine first
    if not registry and execution_engine and hasattr(execution_engine, 'registry'):
        registry = execution_engine.registry
    
    if registry and hasattr(registry, 'provider_instances'):
        for provider_id, provider in registry.provider_instances.items():
            try:
                if hasattr(provider, 'shutdown'):
                    await provider.shutdown()
                elif hasattr(provider, 'cleanup'):
                    await provider.cleanup()
                if verbose:
                    logger.info(f"Provider {provider_id} shut down")
            except Exception as e:
                logger.warning(f"Failed to shutdown provider {provider_id}: {e}")
    
    # Step 3: Shutdown resource manager and hubs
    if resource_manager:
        try:
            await resource_manager.stop()
            if verbose:
                logger.info("Resource manager stopped")
        except Exception as e:
            logger.warning(f"Failed to stop resource manager: {e}")
    
    # Step 4: Shutdown persistence backend
    if persistence_backend:
        try:
            await persistence_backend.shutdown()
            if verbose:
                logger.info("Persistence backend shut down")
        except Exception as e:
            logger.warning(f"Failed to shutdown persistence: {e}")


async def emergency_shutdown(**components) -> None:
    """
    Emergency shutdown that attempts to stop all components without raising exceptions.
    
    Use this when you need to ensure cleanup happens even in error scenarios.
    
    Args:
        **components: Keyword arguments with component names and instances
    """
    for name, component in components.items():
        if not component:
            continue
            
        try:
            # Try various shutdown methods
            if hasattr(component, 'shutdown'):
                await component.shutdown()
            elif hasattr(component, 'stop'):
                await component.stop()
            elif hasattr(component, 'cleanup'):
                await component.cleanup()
            elif hasattr(component, 'close'):
                await component.close()
            logger.debug(f"Emergency shutdown completed for {name}")
        except Exception as e:
            logger.error(f"Emergency shutdown failed for {name}: {e}")