"""
Unified SystemManager discovery and management.

This module provides a centralized way to get or create the SystemManager
instance, ensuring consistent discovery across API, CLI, and SDK contexts.
"""

import logging
from typing import Optional
from .modular_stream_system_manager import ModularStreamSystemManager as SystemManager
from .models import SystemConfig, DeploymentMode
from gleitzeit.core.errors import SystemManagerError

logger = logging.getLogger(__name__)

# Global SystemManager instance (singleton pattern)
_system_manager_instance: Optional[SystemManager] = None


def get_system_manager() -> Optional[SystemManager]:
    """
    Get the global SystemManager instance.
    
    This function provides unified discovery of the SystemManager:
    - Returns existing instance if available
    - Returns None if no SystemManager is initialized
    
    This is used by:
    - API server (creates and manages the instance)
    - Native client (discovers existing instance)
    - CLI (discovers or creates instance)
    
    Returns:
        SystemManager instance or None if not available
    """
    global _system_manager_instance
    return _system_manager_instance


def set_system_manager(manager: Optional[SystemManager]) -> None:
    """
    Set the global SystemManager instance.
    
    This should only be called by the component that creates
    and manages the SystemManager (typically the API server).
    
    Args:
        manager: SystemManager instance or None to clear
    """
    global _system_manager_instance
    _system_manager_instance = manager
    if manager:
        logger.info(f"SystemManager registered globally: {manager.instance_id}")
    else:
        logger.info("SystemManager cleared from global registry")


async def create_system_manager(persistence=None) -> SystemManager:
    """
    Create and register a new SystemManager instance.
    
    This creates a new SystemManager and registers it globally.
    Should only be called by the component that will manage
    the SystemManager lifecycle (typically the API server).
    
    Args:
        persistence: Optional persistence backend to use
        
    Returns:
        Newly created SystemManager instance
        
    Raises:
        RuntimeError: If a SystemManager already exists
    """
    global _system_manager_instance
    
    if _system_manager_instance is not None:
        raise SystemManagerError(
            "SystemManager already exists. Use get_system_manager() to access it."
        )
    
    # Create persistence if not provided
    if persistence is None:
        from gleitzeit.persistence.factory import PersistenceFactory
        persistence = await PersistenceFactory.create()

    # Create system config
    config = SystemConfig()
    config.deployment_mode = DeploymentMode.PRODUCTION

    # Create new ModularStreamSystemManager (don't auto-start)
    manager = await SystemManager.create(
        config=config,
        persistence=persistence,
        create_if_missing=True,
        start_system=False  # Don't auto-start, let caller decide
    )

    if not manager:
        raise SystemManagerError("Failed to create ModularStreamSystemManager")

    # Register globally
    set_system_manager(manager)

    logger.info(f"Created and registered ModularStreamSystemManager: {manager.instance_id}")
    return manager


async def ensure_system_manager(persistence=None) -> SystemManager:
    """
    Get existing SystemManager or create a new one if needed.
    
    This is a convenience function that:
    - Returns existing SystemManager if available
    - Creates new SystemManager if none exists
    
    Args:
        persistence: Optional persistence backend (used only if creating new)
        
    Returns:
        SystemManager instance (existing or newly created)
    """
    manager = get_system_manager()
    if manager is None:
        manager = await create_system_manager(persistence)
    return manager