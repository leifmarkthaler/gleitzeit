"""
Persistence Factory with automatic fallback chain

Provides a factory for creating persistence adapters with automatic fallback:
1. Redis (default) - High performance distributed persistence
2. SQL (fallback) - If Redis is not available
3. In-Memory (final fallback) - If SQL fails or for testing

This ensures the system always has a working persistence layer.
"""

import os
import logging
from typing import Optional, Dict, Any
from enum import Enum

from gleitzeit.persistence.unified_persistence import UnifiedPersistenceAdapter, UnifiedInMemoryAdapter
from gleitzeit.persistence.unified_sqlalchemy import UnifiedSQLAlchemyAdapter
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter

logger = logging.getLogger(__name__)


class PersistenceType(Enum):
    """Available persistence types"""
    REDIS = "redis"
    SQL = "sql"
    MEMORY = "memory"
    AUTO = "auto"  # Use automatic fallback chain


class PersistenceFactory:
    """
    Factory for creating persistence adapters with automatic fallback
    
    The factory attempts to create adapters in the following order:
    1. Redis - Fast, distributed, production-ready
    2. SQLAlchemy - Reliable, ACID compliant fallback
    3. In-Memory - Always works, useful for testing
    
    Usage:
        # Automatic fallback (Redis -> SQL -> Memory)
        adapter = await PersistenceFactory.create()
        
        # Force specific type
        adapter = await PersistenceFactory.create(persistence_type=PersistenceType.SQL)
        
        # Custom configuration
        adapter = await PersistenceFactory.create(
            redis_url="redis://localhost:6379/1",
            sql_connection="postgresql://user:pass@localhost/db"
        )
    """
    
    @classmethod
    async def create(
        cls,
        persistence_type: Optional[PersistenceType] = None,
        redis_url: Optional[str] = None,
        sql_connection: Optional[str] = None,
        sql_db_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> UnifiedPersistenceAdapter:
        """
        Create a persistence adapter with automatic fallback
        
        Args:
            persistence_type: Force a specific persistence type (default: AUTO)
            redis_url: Redis connection URL (default: from env or localhost)
            sql_connection: SQL connection string (default: from env or SQLite)
            sql_db_path: SQLite database path (default: from env or gleitzeit.db)
            config: Additional configuration dictionary
            
        Returns:
            Initialized UnifiedPersistenceAdapter
            
        Raises:
            RuntimeError: If no persistence adapter could be created (should never happen)
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
        
        # Handle specific persistence types
        if persistence_type == PersistenceType.REDIS:
            return await cls._create_redis(redis_url, final_config)
        
        elif persistence_type == PersistenceType.SQL:
            return await cls._create_sql(sql_connection, sql_db_path, final_config)
        
        elif persistence_type == PersistenceType.MEMORY:
            return await cls._create_memory(final_config)
        
        elif persistence_type == PersistenceType.AUTO:
            # Try Redis first
            adapter = await cls._try_redis(redis_url, final_config)
            if adapter:
                return adapter
            
            # Fall back to SQL
            adapter = await cls._try_sql(sql_connection, sql_db_path, final_config)
            if adapter:
                return adapter
            
            # Final fallback to in-memory
            logger.warning("Redis and SQL both failed, using in-memory persistence")
            return await cls._create_memory(final_config)
        
        # Should never reach here
        raise RuntimeError(f"Unknown persistence type: {persistence_type}")
    
    @classmethod
    async def _try_redis(
        cls,
        redis_url: str,
        config: Dict[str, Any]
    ) -> Optional[UnifiedRedisAdapter]:
        """Try to create Redis adapter, return None if fails"""
        try:
            logger.info(f"Attempting to connect to Redis at {redis_url}")
            
            adapter = UnifiedRedisAdapter(
                redis_url=redis_url,
                key_prefix=config.get("redis_key_prefix", "gleitzeit"),
                max_connections=config.get("redis_max_connections", 50),
                socket_timeout=config.get("redis_socket_timeout", 5),
                socket_connect_timeout=config.get("redis_connect_timeout", 5),
                retry_on_timeout=config.get("redis_retry_on_timeout", True),
                health_check_interval=config.get("redis_health_check_interval", 30)
            )
            
            # Test connection
            await adapter.initialize()
            
            # Verify it's working with a simple operation
            test_key = f"{adapter.key_prefix}:connection_test"
            await adapter._execute("SET", test_key, "test", "EX", 1)
            result = await adapter._execute("GET", test_key)
            
            if result == "test":
                logger.info("Successfully connected to Redis persistence")
                return adapter
            else:
                logger.warning("Redis connection test failed")
                await adapter.shutdown()
                return None
                
        except Exception as e:
            logger.warning(f"Failed to create Redis adapter: {e}")
            return None
    
    @classmethod
    async def _try_sql(
        cls,
        sql_connection: Optional[str],
        sql_db_path: str,
        config: Dict[str, Any]
    ) -> Optional[UnifiedSQLAlchemyAdapter]:
        """Try to create SQL adapter, return None if fails"""
        try:
            if sql_connection:
                logger.info(f"Attempting to connect to SQL database: {sql_connection}")
                adapter = UnifiedSQLAlchemyAdapter(
                    connection_string=sql_connection,
                    echo=config.get("sql_echo", False),
                    pool_size=config.get("sql_pool_size", 20),
                    max_overflow=config.get("sql_max_overflow", 40),
                    pool_timeout=config.get("sql_pool_timeout", 30),
                    pool_recycle=config.get("sql_pool_recycle", 3600)
                )
            else:
                logger.info(f"Attempting to use SQLite database: {sql_db_path}")
                adapter = UnifiedSQLAlchemyAdapter(
                    db_path=sql_db_path,
                    echo=config.get("sql_echo", False)
                )
            
            # Test connection
            await adapter.initialize()
            
            # Verify with a simple operation
            from gleitzeit.core.models import Task
            test_task = Task(
                id="__test_task__",
                name="Connection Test",
                protocol="test",
                method="test",
                params={},
                priority="normal"
            )
            
            await adapter.save_task(test_task)
            retrieved = await adapter.get_task("__test_task__")
            await adapter.delete_task("__test_task__")
            
            if retrieved and retrieved.id == "__test_task__":
                logger.info("Successfully connected to SQL persistence")
                return adapter
            else:
                logger.warning("SQL connection test failed")
                await adapter.shutdown()
                return None
                
        except Exception as e:
            logger.warning(f"Failed to create SQL adapter: {e}")
            return None
    
    @classmethod
    async def _create_redis(
        cls,
        redis_url: str,
        config: Dict[str, Any]
    ) -> UnifiedRedisAdapter:
        """Create Redis adapter or raise exception"""
        adapter = await cls._try_redis(redis_url, config)
        if adapter:
            return adapter
        raise RuntimeError("Failed to create Redis adapter")
    
    @classmethod
    async def _create_sql(
        cls,
        sql_connection: Optional[str],
        sql_db_path: str,
        config: Dict[str, Any]
    ) -> UnifiedSQLAlchemyAdapter:
        """Create SQL adapter or raise exception"""
        adapter = await cls._try_sql(sql_connection, sql_db_path, config)
        if adapter:
            return adapter
        raise RuntimeError("Failed to create SQL adapter")
    
    @classmethod
    async def _create_memory(
        cls,
        config: Dict[str, Any]
    ) -> UnifiedInMemoryAdapter:
        """Create in-memory adapter (always succeeds)"""
        logger.info("Using in-memory persistence")
        adapter = UnifiedInMemoryAdapter()
        await adapter.initialize()
        return adapter
    
    @classmethod
    async def create_for_testing(cls) -> UnifiedInMemoryAdapter:
        """
        Create an in-memory adapter for testing
        
        This is a convenience method that always returns an in-memory adapter,
        useful for unit tests and development.
        """
        return await cls._create_memory({})


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
            raise RuntimeError("PersistenceManager already initialized")
        
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
            raise RuntimeError("PersistenceManager not initialized. Call initialize() first.")
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
        persistence_type: Type string ("redis", "sql", "memory", "auto")
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


async def get_default_persistence() -> UnifiedPersistenceAdapter:
    """
    Get the default persistence adapter with automatic fallback
    
    Returns:
        Initialized persistence adapter (Redis -> SQL -> Memory)
    """
    return await PersistenceFactory.create()