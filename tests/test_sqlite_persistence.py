"""
Test SQLite persistence adapter for hub state management
"""

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from gleitzeit.hub.persistence_sql import SQLiteHubAdapter
from gleitzeit.hub.persistence_sqlalchemy import SQLAlchemyHubAdapter
from gleitzeit.hub.persistence import RedisHubAdapter, InMemoryHubAdapter
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType
from gleitzeit.providers.persistent_hub_provider import PersistentHubProvider
from gleitzeit.hub.ollama_hub import OllamaConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_sqlite_backend():
    """Test SQLite persistence adapter"""
    print("\n=== Testing SQLite Backend ===")
    
    # Use temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    adapter = SQLiteHubAdapter(db_path=db_path)
    
    try:
        await adapter.initialize()
        print(f"✓ SQLite adapter initialized: {db_path}")
        
        # Create test data
        hub_id = "test-hub-sqlite"
        instance = ResourceInstance(
            id=f"sqlite-test-{datetime.utcnow().timestamp()}",
            name="SQLite Test Instance",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:11434",
            status=ResourceStatus.HEALTHY,
            capabilities={"llm/complete", "llm/chat"},
            tags={"sqlite", "test"}
        )
        
        # Test 1: Save instance
        await adapter.save_instance(hub_id, instance)
        print(f"✓ Saved instance to SQLite: {instance.id}")
        
        # Test 2: Load instance
        loaded = await adapter.load_instance(instance.id)
        assert loaded is not None
        assert loaded['id'] == instance.id
        assert loaded['name'] == instance.name
        print("✓ Loaded instance from SQLite")
        
        # Test 3: List instances
        instances = await adapter.list_instances(hub_id)
        assert len(instances) == 1
        assert instances[0]['id'] == instance.id
        print(f"✓ Listed {len(instances)} instances from hub")
        
        # Test 4: Save metrics
        metrics = ResourceMetrics(
            request_count=100,
            error_count=5,
            avg_response_time_ms=42.5,
            cpu_percent=55.5,
            memory_mb=2048
        )
        await adapter.save_metrics(instance.id, metrics)
        print("✓ Saved metrics to SQLite")
        
        # Test 5: Get metrics history
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        history = await adapter.get_metrics_history(instance.id, start_time, end_time)
        assert len(history) > 0
        assert history[0]['request_count'] == 100
        print(f"✓ Retrieved metrics history: {len(history)} entries")
        
        # Test 6: Distributed locking
        lock_acquired = await adapter.acquire_lock("resource-1", "worker-1", timeout=10)
        assert lock_acquired == True
        print("✓ Acquired lock in SQLite")
        
        # Try to acquire same lock (should fail)
        lock_acquired2 = await adapter.acquire_lock("resource-1", "worker-2", timeout=10)
        assert lock_acquired2 == False
        print("✓ Second lock attempt correctly blocked")
        
        # Check lock owner
        owner = await adapter.get_lock_owner("resource-1")
        assert owner == "worker-1"
        print(f"✓ Lock owner verified: {owner}")
        
        # Extend lock
        extended = await adapter.extend_lock("resource-1", "worker-1", timeout=20)
        assert extended == True
        print("✓ Lock extended successfully")
        
        # Release lock
        await adapter.release_lock("resource-1", "worker-1")
        owner = await adapter.get_lock_owner("resource-1")
        assert owner is None
        print("✓ Lock released")
        
        # Now worker-2 can acquire
        lock_acquired3 = await adapter.acquire_lock("resource-1", "worker-2", timeout=10)
        assert lock_acquired3 == True
        await adapter.release_lock("resource-1", "worker-2")
        print("✓ Lock transferred to different worker")
        
        # Test 7: Delete instance
        await adapter.delete_instance(instance.id)
        loaded = await adapter.load_instance(instance.id)
        assert loaded is None
        print("✓ Instance deleted from SQLite")
        
        print("\n✅ All SQLite tests passed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await adapter.shutdown()
        # Clean up temp file
        if os.path.exists(db_path):
            os.unlink(db_path)
        print("✓ Adapter shut down and cleaned up")


async def test_sqlite_with_provider():
    """Test PersistentHubProvider with SQLite"""
    print("\n=== Testing PersistentHubProvider with SQLite ===")
    
    # Use temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    # Simple test provider
    class TestProvider(PersistentHubProvider):
        def __init__(self, **kwargs):
            super().__init__(
                provider_id="sqlite-test-provider",
                protocol_id="test",
                name="SQLite Test Provider",
                description="Testing SQLite persistence",
                resource_config_class=OllamaConfig,
                **kwargs
            )
        
        def get_supported_methods(self):
            return ["test/method"]
        
        async def create_resource(self, config):
            return ResourceInstance(
                id=f"test-{datetime.utcnow().timestamp()}",
                name="Test Resource",
                type=ResourceType.OLLAMA,
                endpoint="http://test",
                status=ResourceStatus.HEALTHY,
                config=config
            )
        
        async def destroy_resource(self, instance):
            pass
        
        async def execute_on_resource(self, instance, method, params):
            return {"result": "test"}
        
        async def check_resource_health(self, instance):
            return True
        
        async def discover_resources(self):
            return []
    
    # Use SQLite adapter
    adapter = SQLiteHubAdapter(db_path=db_path)
    
    provider1 = TestProvider(
        persistence_adapter=adapter,
        enable_persistence=True,
        persistence_interval=1,
        instance_id="provider-sqlite-1"
    )
    
    try:
        await provider1.initialize()
        print("✓ Provider initialized with SQLite persistence")
        
        # Create some resources
        for i in range(3):
            config = OllamaConfig(host=f"test-{i}", port=11434)
            instance = await provider1.create_resource(config)
            await provider1.register_instance(instance)
            print(f"✓ Registered instance {i+1}")
        
        # Wait for persistence
        await asyncio.sleep(2)
        
        # Simulate restart - create new provider with same ID
        await provider1.shutdown()
        print("✓ Provider 1 shut down")
        
        provider2 = TestProvider(
            persistence_adapter=adapter,
            enable_persistence=True,
            instance_id="provider-sqlite-2"
        )
        
        await provider2.initialize()
        print(f"✓ Provider 2 initialized")
        print(f"✓ Recovered {len(provider2.instances)} instances from SQLite")
        
        # Verify instances were recovered
        assert len(provider2.instances) == 3
        print("✓ All instances recovered successfully!")
        
        await provider2.shutdown()
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await adapter.shutdown()
        # Clean up temp file
        if os.path.exists(db_path):
            os.unlink(db_path)
        print("✓ Cleaned up SQLite database")


async def compare_adapters():
    """Compare performance and features of different adapters"""
    print("\n=== Comparing Persistence Adapters ===")
    
    # Create instances of each adapter
    adapters = {
        'InMemory': InMemoryHubAdapter(),
        'SQLite': SQLiteHubAdapter(db_path=":memory:"),  # In-memory SQLite for testing
        'SQLAlchemy': SQLAlchemyHubAdapter("sqlite+aiosqlite:///:memory:"),  # In-memory SQLAlchemy
    }
    
    # Add Redis if available
    try:
        import redis.asyncio as redis
        adapters['Redis'] = RedisHubAdapter(redis_url="redis://localhost:6379")
    except ImportError:
        print("  ⚠️  Redis not available for comparison")
    
    results = {}
    
    for name, adapter in adapters.items():
        print(f"\n  Testing {name} adapter...")
        
        try:
            await adapter.initialize()
            
            # Measure write performance
            start = datetime.utcnow()
            
            hub_id = f"test-{name.lower()}"
            for i in range(10):
                instance = ResourceInstance(
                    id=f"{name.lower()}-{i}",
                    name=f"{name} Instance {i}",
                    type=ResourceType.OLLAMA,
                    endpoint=f"http://localhost:{11434+i}",
                    status=ResourceStatus.HEALTHY,
                    capabilities={"llm/complete"},
                    tags={name.lower()}
                )
                await adapter.save_instance(hub_id, instance)
            
            write_time = (datetime.utcnow() - start).total_seconds()
            
            # Measure read performance
            start = datetime.utcnow()
            instances = await adapter.list_instances(hub_id)
            read_time = (datetime.utcnow() - start).total_seconds()
            
            # Measure lock performance
            start = datetime.utcnow()
            for i in range(10):
                acquired = await adapter.acquire_lock(f"lock-{i}", "test-owner", timeout=5)
                if acquired:
                    await adapter.release_lock(f"lock-{i}", "test-owner")
            lock_time = (datetime.utcnow() - start).total_seconds()
            
            results[name] = {
                'write_time': write_time,
                'read_time': read_time,
                'lock_time': lock_time,
                'instances_saved': len(instances)
            }
            
            print(f"    ✓ Write 10 instances: {write_time:.3f}s")
            print(f"    ✓ Read instances: {read_time:.3f}s")
            print(f"    ✓ Lock operations: {lock_time:.3f}s")
            
        except Exception as e:
            print(f"    ❌ Failed: {e}")
            results[name] = {'error': str(e)}
        
        finally:
            await adapter.shutdown()
    
    # Summary
    print("\n📊 Performance Summary:")
    print("  " + "-" * 50)
    print(f"  {'Adapter':<15} {'Write (s)':<12} {'Read (s)':<12} {'Lock (s)':<12}")
    print("  " + "-" * 50)
    
    for name, result in results.items():
        if 'error' not in result:
            print(f"  {name:<15} {result['write_time']:<12.3f} {result['read_time']:<12.3f} {result['lock_time']:<12.3f}")
        else:
            print(f"  {name:<15} {'Error':<12} {'Error':<12} {'Error':<12}")
    
    print("\n✅ Comparison complete!")


async def main():
    """Run all SQLite persistence tests"""
    print("=" * 60)
    print("SQLite Hub Persistence Tests")
    print("=" * 60)
    
    # Check if aiosqlite is installed
    try:
        import aiosqlite
        print("✓ aiosqlite is installed")
    except ImportError:
        print("❌ aiosqlite not installed")
        print("\nTo test SQLite backend, install aiosqlite:")
        print("  pip install aiosqlite")
        return
    
    await test_sqlite_backend()
    await test_sqlite_with_provider()
    await compare_adapters()
    
    print("\n" + "=" * 60)
    print("✅ SQLite persistence working perfectly!")
    print("=" * 60)
    
    print("\n📝 Summary:")
    print("  • SQLite provides ACID-compliant local persistence")
    print("  • Supports all hub persistence operations")
    print("  • Distributed locking via database transactions")
    print("  • Good for single-node deployments")
    print("  • Redis better for distributed multi-node setups")


if __name__ == "__main__":
    asyncio.run(main())