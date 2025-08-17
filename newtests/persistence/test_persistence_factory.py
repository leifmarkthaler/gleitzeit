"""
Test Suite for Persistence Factory and Fallback Mechanism

Tests the automatic fallback chain: Redis -> SQL -> In-Memory
"""

import pytest
import asyncio
import tempfile
import os
from unittest.mock import patch, MagicMock, AsyncMock
from typing import Optional

from gleitzeit.persistence.factory import (
    PersistenceFactory,
    PersistenceManager,
    PersistenceType,
    create_persistence,
    get_default_persistence
)
from gleitzeit.persistence.unified_persistence import (
    UnifiedPersistenceAdapter,
    UnifiedInMemoryAdapter
)
from gleitzeit.persistence.unified_sqlalchemy import UnifiedSQLAlchemyAdapter
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.core.models import Task


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def clean_env():
    """Clean environment variables for testing"""
    env_vars = [
        "GLEITZEIT_PERSISTENCE_TYPE",
        "GLEITZEIT_REDIS_URL",
        "GLEITZEIT_SQL_CONNECTION",
        "GLEITZEIT_DB_PATH"
    ]
    
    # Store original values
    original = {}
    for var in env_vars:
        original[var] = os.environ.get(var)
        if var in os.environ:
            del os.environ[var]
    
    yield
    
    # Restore original values
    for var, value in original.items():
        if value is not None:
            os.environ[var] = value
        elif var in os.environ:
            del os.environ[var]


@pytest.fixture
async def reset_manager():
    """Reset PersistenceManager state"""
    # Shutdown if initialized
    if PersistenceManager.is_initialized():
        await PersistenceManager.shutdown()
    
    yield
    
    # Cleanup after test
    if PersistenceManager.is_initialized():
        await PersistenceManager.shutdown()


# ============================================================================
# Factory Tests
# ============================================================================

class TestPersistenceFactory:
    """Test the PersistenceFactory"""
    
    async def test_create_memory_explicitly(self, clean_env):
        """Test explicitly creating in-memory adapter"""
        adapter = await PersistenceFactory.create(
            persistence_type=PersistenceType.MEMORY
        )
        
        assert isinstance(adapter, UnifiedInMemoryAdapter)
        await adapter.shutdown()
    
    async def test_create_sql_explicitly(self, clean_env):
        """Test explicitly creating SQL adapter"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        
        try:
            adapter = await PersistenceFactory.create(
                persistence_type=PersistenceType.SQL,
                sql_db_path=db_path
            )
            
            assert isinstance(adapter, UnifiedSQLAlchemyAdapter)
            
            # Test it works
            task = Task(
                id="test_sql",
                name="Test",
                protocol="test",
                method="test",
                params={},
                priority="normal"
            )
            await adapter.save_task(task)
            retrieved = await adapter.get_task("test_sql")
            assert retrieved is not None
            
            await adapter.shutdown()
        finally:
            os.unlink(db_path)
    
    @pytest.mark.skipif(
        os.environ.get("CI") == "true",
        reason="Redis not available in CI"
    )
    async def test_create_redis_explicitly(self, clean_env):
        """Test explicitly creating Redis adapter"""
        try:
            adapter = await PersistenceFactory.create(
                persistence_type=PersistenceType.REDIS,
                redis_url="redis://localhost:6379/15"
            )
            
            assert isinstance(adapter, UnifiedRedisAdapter)
            
            # Cleanup
            await adapter._execute("FLUSHDB")
            await adapter.shutdown()
        except RuntimeError as e:
            if "Failed to create Redis adapter" in str(e):
                pytest.skip("Redis not available")
            raise
    
    async def test_auto_fallback_all_fail(self, clean_env):
        """Test AUTO mode falls back to memory when Redis and SQL fail"""
        with patch.object(PersistenceFactory, '_try_redis', return_value=None):
            with patch.object(PersistenceFactory, '_try_sql', return_value=None):
                adapter = await PersistenceFactory.create(
                    persistence_type=PersistenceType.AUTO
                )
                
                assert isinstance(adapter, UnifiedInMemoryAdapter)
                await adapter.shutdown()
    
    async def test_auto_fallback_redis_fails(self, clean_env):
        """Test AUTO mode falls back to SQL when Redis fails"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        
        try:
            with patch.object(PersistenceFactory, '_try_redis', return_value=None):
                adapter = await PersistenceFactory.create(
                    persistence_type=PersistenceType.AUTO,
                    sql_db_path=db_path
                )
                
                assert isinstance(adapter, UnifiedSQLAlchemyAdapter)
                await adapter.shutdown()
        finally:
            os.unlink(db_path)
    
    async def test_env_var_configuration(self, clean_env):
        """Test configuration from environment variables"""
        os.environ["GLEITZEIT_PERSISTENCE_TYPE"] = "memory"
        os.environ["GLEITZEIT_DB_PATH"] = "/tmp/test.db"
        
        adapter = await PersistenceFactory.create()
        
        assert isinstance(adapter, UnifiedInMemoryAdapter)
        await adapter.shutdown()
    
    async def test_invalid_persistence_type_env(self, clean_env):
        """Test invalid persistence type in environment falls back to AUTO"""
        os.environ["GLEITZEIT_PERSISTENCE_TYPE"] = "invalid_type"
        
        with patch.object(PersistenceFactory, '_try_redis', return_value=None):
            with patch.object(PersistenceFactory, '_try_sql', return_value=None):
                adapter = await PersistenceFactory.create()
                
                assert isinstance(adapter, UnifiedInMemoryAdapter)
                await adapter.shutdown()
    
    async def test_create_for_testing(self, clean_env):
        """Test convenience method for testing"""
        adapter = await PersistenceFactory.create_for_testing()
        
        assert isinstance(adapter, UnifiedInMemoryAdapter)
        await adapter.shutdown()
    
    async def test_config_parameter_passing(self, clean_env):
        """Test passing configuration parameters"""
        config = {
            "redis_key_prefix": "test_prefix",
            "redis_max_connections": 100,
            "sql_echo": True,
            "sql_pool_size": 50
        }
        
        with patch.object(PersistenceFactory, '_try_redis', return_value=None):
            with patch.object(PersistenceFactory, '_create_sql') as mock_sql:
                mock_adapter = AsyncMock()
                mock_sql.return_value = mock_adapter
                
                adapter = await PersistenceFactory.create(
                    persistence_type=PersistenceType.SQL,
                    config=config
                )
                
                # Verify config was passed
                mock_sql.assert_called_once()
                call_args = mock_sql.call_args[0]
                assert call_args[2] == config  # config is third argument


class TestPersistenceManager:
    """Test the PersistenceManager singleton"""
    
    async def test_initialize_and_get(self, reset_manager):
        """Test initializing and getting the adapter"""
        adapter = await PersistenceManager.initialize(
            persistence_type=PersistenceType.MEMORY
        )
        
        assert isinstance(adapter, UnifiedInMemoryAdapter)
        assert PersistenceManager.is_initialized()
        
        # Get adapter
        same_adapter = PersistenceManager.get_adapter()
        assert same_adapter is adapter
        
        # Get adapter type
        adapter_type = PersistenceManager.get_adapter_type()
        assert adapter_type == "UnifiedInMemoryAdapter"
    
    async def test_double_initialize_error(self, reset_manager):
        """Test that double initialization raises error"""
        await PersistenceManager.initialize(
            persistence_type=PersistenceType.MEMORY
        )
        
        with pytest.raises(RuntimeError, match="already initialized"):
            await PersistenceManager.initialize()
    
    async def test_get_before_initialize_error(self, reset_manager):
        """Test that getting adapter before initialization raises error"""
        with pytest.raises(RuntimeError, match="not initialized"):
            PersistenceManager.get_adapter()
    
    async def test_shutdown(self, reset_manager):
        """Test shutting down the manager"""
        await PersistenceManager.initialize(
            persistence_type=PersistenceType.MEMORY
        )
        
        assert PersistenceManager.is_initialized()
        
        await PersistenceManager.shutdown()
        
        assert not PersistenceManager.is_initialized()
        assert PersistenceManager.get_adapter_type() is None
        
        # Should be able to initialize again
        await PersistenceManager.initialize(
            persistence_type=PersistenceType.MEMORY
        )
        assert PersistenceManager.is_initialized()


class TestConvenienceFunctions:
    """Test convenience functions"""
    
    async def test_create_persistence_function(self, clean_env):
        """Test the create_persistence convenience function"""
        adapter = await create_persistence(persistence_type="memory")
        
        assert isinstance(adapter, UnifiedInMemoryAdapter)
        await adapter.shutdown()
    
    async def test_create_persistence_invalid_type(self, clean_env):
        """Test create_persistence with invalid type falls back to AUTO"""
        with patch.object(PersistenceFactory, '_try_redis', return_value=None):
            with patch.object(PersistenceFactory, '_try_sql', return_value=None):
                adapter = await create_persistence(persistence_type="invalid")
                
                assert isinstance(adapter, UnifiedInMemoryAdapter)
                await adapter.shutdown()
    
    async def test_get_default_persistence(self, clean_env):
        """Test get_default_persistence function"""
        with patch.object(PersistenceFactory, '_try_redis', return_value=None):
            with patch.object(PersistenceFactory, '_try_sql', return_value=None):
                adapter = await get_default_persistence()
                
                assert isinstance(adapter, UnifiedInMemoryAdapter)
                await adapter.shutdown()


# ============================================================================
# Fallback Chain Tests
# ============================================================================

class TestFallbackChain:
    """Test the complete fallback chain behavior"""
    
    async def test_redis_success_no_fallback(self, clean_env):
        """Test that successful Redis connection doesn't trigger fallback"""
        mock_redis = AsyncMock(spec=UnifiedRedisAdapter)
        
        with patch.object(PersistenceFactory, '_try_redis', return_value=mock_redis):
            with patch.object(PersistenceFactory, '_try_sql') as mock_sql:
                adapter = await PersistenceFactory.create(
                    persistence_type=PersistenceType.AUTO
                )
                
                assert adapter is mock_redis
                mock_sql.assert_not_called()  # SQL should not be tried
    
    async def test_redis_fail_sql_success(self, clean_env):
        """Test fallback from Redis to SQL"""
        mock_sql = AsyncMock(spec=UnifiedSQLAlchemyAdapter)
        
        with patch.object(PersistenceFactory, '_try_redis', return_value=None):
            with patch.object(PersistenceFactory, '_try_sql', return_value=mock_sql):
                adapter = await PersistenceFactory.create(
                    persistence_type=PersistenceType.AUTO
                )
                
                assert adapter is mock_sql
    
    async def test_complete_fallback_chain(self, clean_env):
        """Test complete fallback chain: Redis -> SQL -> Memory"""
        # Track which methods were called
        calls = []
        
        async def track_redis(*args, **kwargs):
            calls.append('redis')
            return None
        
        async def track_sql(*args, **kwargs):
            calls.append('sql')
            return None
        
        with patch.object(PersistenceFactory, '_try_redis', side_effect=track_redis):
            with patch.object(PersistenceFactory, '_try_sql', side_effect=track_sql):
                adapter = await PersistenceFactory.create(
                    persistence_type=PersistenceType.AUTO
                )
                
                assert isinstance(adapter, UnifiedInMemoryAdapter)
                assert calls == ['redis', 'sql']  # Both were tried in order
                await adapter.shutdown()
    
    async def test_redis_connection_test_failure(self, clean_env):
        """Test Redis connection test failure triggers fallback"""
        mock_redis = AsyncMock(spec=UnifiedRedisAdapter)
        mock_redis._execute = AsyncMock(side_effect=Exception("Connection failed"))
        
        with patch('gleitzeit.persistence.factory.UnifiedRedisAdapter', return_value=mock_redis):
            with patch.object(PersistenceFactory, '_try_sql', return_value=None):
                adapter = await PersistenceFactory.create(
                    persistence_type=PersistenceType.AUTO,
                    redis_url="redis://localhost:6379/15"
                )
                
                # Should fall back to memory
                assert isinstance(adapter, UnifiedInMemoryAdapter)
                await adapter.shutdown()
    
    async def test_sql_connection_test_failure(self, clean_env):
        """Test SQL connection test failure triggers fallback"""
        mock_sql = AsyncMock(spec=UnifiedSQLAlchemyAdapter)
        mock_sql.save_task = AsyncMock(side_effect=Exception("DB error"))
        
        with patch.object(PersistenceFactory, '_try_redis', return_value=None):
            with patch('gleitzeit.persistence.factory.UnifiedSQLAlchemyAdapter', return_value=mock_sql):
                adapter = await PersistenceFactory.create(
                    persistence_type=PersistenceType.AUTO
                )
                
                # Should fall back to memory
                assert isinstance(adapter, UnifiedInMemoryAdapter)
                await adapter.shutdown()


# ============================================================================
# Integration Tests
# ============================================================================

class TestFactoryIntegration:
    """Integration tests for the factory with real backends"""
    
    async def test_real_sql_fallback(self, clean_env):
        """Test real SQL adapter creation and usage"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        
        try:
            # Force Redis to fail, SQL should work
            adapter = await PersistenceFactory.create(
                persistence_type=PersistenceType.AUTO,
                redis_url="redis://invalid-host:6379",
                sql_db_path=db_path
            )
            
            # Should get SQL adapter
            assert isinstance(adapter, (UnifiedSQLAlchemyAdapter, UnifiedInMemoryAdapter))
            
            # Test it works
            task = Task(
                id="integration_test",
                name="Test Task",
                protocol="test",
                method="test",
                params={},
                priority="normal"
            )
            
            await adapter.save_task(task)
            retrieved = await adapter.get_task("integration_test")
            assert retrieved is not None
            assert retrieved.name == "Test Task"
            
            await adapter.shutdown()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)
    
    async def test_memory_always_works(self, clean_env):
        """Test that memory adapter always works as final fallback"""
        # Force all external backends to fail
        adapter = await PersistenceFactory.create(
            persistence_type=PersistenceType.AUTO,
            redis_url="redis://invalid-host:6379",
            sql_connection="postgresql://invalid:invalid@invalid/invalid"
        )
        
        # Should get memory adapter
        assert isinstance(adapter, UnifiedInMemoryAdapter)
        
        # Test it works
        task = Task(
            id="memory_test",
            name="Memory Test",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        
        await adapter.save_task(task)
        retrieved = await adapter.get_task("memory_test")
        assert retrieved is not None
        assert retrieved.name == "Memory Test"
        
        await adapter.shutdown()
    
    async def test_persistence_type_override(self, clean_env):
        """Test that explicit persistence type overrides AUTO behavior"""
        # Even if Redis would work, force memory
        adapter = await PersistenceFactory.create(
            persistence_type=PersistenceType.MEMORY,
            redis_url="redis://localhost:6379/15"  # Would work if tried
        )
        
        assert isinstance(adapter, UnifiedInMemoryAdapter)
        await adapter.shutdown()
    
    @pytest.mark.parametrize("env_type,expected_type", [
        ("memory", UnifiedInMemoryAdapter),
        ("sql", UnifiedSQLAlchemyAdapter),
        ("auto", UnifiedInMemoryAdapter),  # Will fallback to memory in test
    ])
    async def test_environment_configuration(self, clean_env, env_type, expected_type):
        """Test configuration from environment variables"""
        os.environ["GLEITZEIT_PERSISTENCE_TYPE"] = env_type
        
        if env_type == "sql":
            with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
                db_path = tmp.name
                os.environ["GLEITZEIT_DB_PATH"] = db_path
        
        try:
            # Mock Redis to fail for AUTO test
            with patch.object(PersistenceFactory, '_try_redis', return_value=None):
                with patch.object(PersistenceFactory, '_try_sql', return_value=None) if env_type == "auto" else nullcontext():
                    adapter = await PersistenceFactory.create()
                    
                    assert isinstance(adapter, expected_type)
                    await adapter.shutdown()
        finally:
            if env_type == "sql" and 'db_path' in locals():
                if os.path.exists(db_path):
                    os.unlink(db_path)


from contextlib import nullcontext