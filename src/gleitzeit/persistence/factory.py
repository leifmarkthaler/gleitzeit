"""
Persistence Factory for Redis-only persistence

Provides a factory for creating Redis persistence adapters.
Redis is required - no fallbacks to in-memory or other backends.

This ensures consistent distributed state management across all instances.
"""

import os
import logging
from typing import Optional, Dict, Any
from enum import Enum

from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.errors import (
    PersistenceError,
    ConfigurationError,
    ErrorCode,
    PersistenceConnectionError
)

logger = logging.getLogger(__name__)


class PersistenceType(Enum):
    """Available persistence types"""
    REDIS = "redis"
    AUTO = "auto"  # Default to Redis


class PersistenceFactory:
    """
    Factory for creating Redis persistence adapters
    
    Redis is required for Gleitzeit to ensure distributed state consistency.
    No fallback to in-memory or other backends is provided.
    
    Usage:
        # Create Redis adapter (default)
        adapter = await PersistenceFactory.create()
        
        # Custom Redis configuration
        adapter = await PersistenceFactory.create(
            redis_url="redis://localhost:6379/1"
        )
    """
    
    @classmethod
    async def create(
        cls,
        persistence_type: Optional[PersistenceType] = None,
        redis_url: Optional[str] = None,
        sql_connection: Optional[str] = None,
        sql_db_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        event_bus: Optional[Any] = None
    ) -> UnifiedPersistenceAdapter:
        """
        Create a Redis persistence adapter
        
        Args:
            persistence_type: Must be REDIS or AUTO (both use Redis)
            redis_url: Redis connection URL (default: from env or localhost)
            sql_connection: Deprecated - not used
            sql_db_path: Deprecated - not used
            config: Additional configuration dictionary
            event_bus: Deprecated - not used
            
        Returns:
            Initialized UnifiedRedisAdapter
            
        Raises:
            PersistenceConnectionError: If Redis connection fails
            ConfigurationError: If configuration is invalid
        """
        # Get persistence type from environment or use AUTO
        if persistence_type is None:
            env_type = os.environ.get("GLEITZEIT_PERSISTENCE_TYPE", "auto").lower()
            try:
                persistence_type = PersistenceType(env_type)
            except ValueError:
                logger.warning(f"Unknown persistence type '{env_type}', using AUTO")
                persistence_type = PersistenceType.AUTO
        
        # Get configuration from environment or defaults
        if redis_url is None:
            redis_url = os.environ.get("GLEITZEIT_REDIS_URL", "redis://localhost:6379/0")
        
        if sql_connection is None:
            sql_connection = os.environ.get("GLEITZEIT_SQL_CONNECTION")
        
        if sql_db_path is None:
            sql_db_path = os.environ.get("GLEITZEIT_DB_PATH", "gleitzeit.db")
        
        # Merge config with defaults
        final_config = config or {}
        
        # Always use Redis - no other backends supported
        if persistence_type in [PersistenceType.REDIS, PersistenceType.AUTO]:
            return await cls._create_redis(redis_url, final_config)
        
        # Should never reach here
        raise ConfigurationError(
            f"Unknown persistence type: {persistence_type}. Only Redis is supported.",
            code=ErrorCode.CONFIGURATION_ERROR
        )
    
    @classmethod
    async def _create_redis(
        cls,
        redis_url: str,
        config: Dict[str, Any]
    ) -> UnifiedRedisAdapter:
        """Create Redis adapter or raise exception"""
        try:
            logger.info(f"Connecting to Redis at {redis_url}")
            
            # Always use UnifiedRedisAdapter - the only supported implementation
            adapter = UnifiedRedisAdapter(
                redis_url=redis_url,
                key_prefix=config.get("redis_key_prefix", "gleitzeit"),
                max_connections=config.get("redis_max_connections", 50),
                socket_timeout=config.get("redis_socket_timeout", 5),
                socket_connect_timeout=config.get("redis_connect_timeout", 5),
                retry_on_timeout=config.get("redis_retry_on_timeout", True),
                health_check_interval=config.get("redis_health_check_interval", 30)
            )
            
            # Initialize and test connection
            await adapter.initialize()
            
            # Verify Redis is working with a simple operation
            test_key = f"{adapter.key_prefix}:connection_test"
            await adapter._execute("SET", test_key, "test", "EX", 1)
            result = await adapter._execute("GET", test_key)
            
            if result == "test":
                logger.info("Successfully connected to Redis persistence")
                return adapter
            else:
                raise PersistenceConnectionError(
                    "Redis connection test failed",
                    code=ErrorCode.PERSISTENCE_CONNECTION_FAILED,
                    backend="redis"
                )
                
        except PersistenceConnectionError:
            raise
        except Exception as e:
            logger.error(f"Failed to create Redis adapter: {e}")
            raise PersistenceConnectionError(
                f"Redis connection failed: {e}",
                code=ErrorCode.PERSISTENCE_CONNECTION_FAILED,
                backend="redis",
                cause=e
            )
    
    
    
    @classmethod
    async def create_for_testing(cls) -> UnifiedRedisAdapter:
        """
        Create a Redis adapter for testing
        
        Tests should use a separate Redis database or key prefix
        to avoid conflicts with production data.
        
        Returns:
            Redis adapter configured for testing
            
        Raises:
            PersistenceConnectionError: If Redis is not available
        """
        # Use test database (db 15) or test prefix
        test_redis_url = os.environ.get("GLEITZEIT_TEST_REDIS_URL", "redis://localhost:6379/15")
        return await cls._create_redis(
            redis_url=test_redis_url,
            config={"redis_key_prefix": "gleitzeit_test"}
        )


class PersistenceManager:
    """
    Singleton manager for the application's persistence adapter
    
    This ensures all components use the same persistence adapter instance.
    
    Usage:
        # Initialize once at startup
        await PersistenceManager.initialize()
        
        # Get adapter anywhere in the application
        adapter = PersistenceManager.get_adapter()
        
        # Shutdown at application exit
        await PersistenceManager.shutdown()
    """
    
    _adapter: Optional[UnifiedPersistenceAdapter] = None
    _initialized: bool = False
    
    @classmethod
    async def initialize(
        cls,
        persistence_type: Optional[PersistenceType] = None,
        **kwargs
    ) -> UnifiedPersistenceAdapter:
        """
        Initialize the global persistence adapter
        
        Args:
            persistence_type: Force specific persistence type
            **kwargs: Additional arguments passed to PersistenceFactory.create()
            
        Returns:
            The initialized adapter
            
        Raises:
            RuntimeError: If already initialized
        """
        if cls._initialized:
            raise PersistenceError("PersistenceManager already initialized")
        
        cls._adapter = await PersistenceFactory.create(
            persistence_type=persistence_type,
            **kwargs
        )
        cls._initialized = True
        
        logger.info(f"PersistenceManager initialized with {type(cls._adapter).__name__}")
        return cls._adapter
    
    @classmethod
    def get_adapter(cls) -> UnifiedPersistenceAdapter:
        """
        Get the global persistence adapter
        
        Returns:
            The persistence adapter
            
        Raises:
            RuntimeError: If not initialized
        """
        if not cls._initialized or not cls._adapter:
            raise PersistenceError("PersistenceManager not initialized. Call initialize() first.")
        return cls._adapter
    
    @classmethod
    async def shutdown(cls) -> None:
        """Shutdown the global persistence adapter"""
        if cls._adapter:
            await cls._adapter.shutdown()
            cls._adapter = None
            cls._initialized = False
            logger.info("PersistenceManager shut down")
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if the manager is initialized"""
        return cls._initialized
    
    @classmethod
    def get_adapter_type(cls) -> Optional[str]:
        """Get the type of the current adapter"""
        if cls._adapter:
            return type(cls._adapter).__name__
        return None


# Convenience functions for backward compatibility
async def create_persistence(
    persistence_type: str = "auto",
    **kwargs
) -> UnifiedPersistenceAdapter:
    """
    Create a persistence adapter (backward compatibility)
    
    Args:
        persistence_type: Type string ("redis", "sql", "memory", "auto", "scaling", "simple")
        **kwargs: Additional configuration
        
    Returns:
        Initialized persistence adapter
    """
    try:
        ptype = PersistenceType(persistence_type.lower())
    except ValueError:
        logger.warning(f"Unknown persistence type '{persistence_type}', using AUTO")
        ptype = PersistenceType.AUTO
    
    return await PersistenceFactory.create(persistence_type=ptype, **kwargs)


async def get_default_persistence() -> UnifiedRedisAdapter:
    """
    Get the default Redis persistence adapter
    
    Returns:
        Initialized Redis adapter
        
    Raises:
        PersistenceConnectionError: If Redis is not available
    """
    return await PersistenceFactory.create()