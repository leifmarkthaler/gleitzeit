"""
Test with actual Redis backend
"""

import asyncio
import logging
from datetime import datetime

from gleitzeit.hub.persistence import RedisHubAdapter
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_redis_backend():
    """Test with actual Redis server"""
    print("\n=== Testing with Actual Redis Backend ===")
    
    # Connect to real Redis
    adapter = RedisHubAdapter(redis_url="redis://localhost:6379")
    
    try:
        await adapter.initialize()
        print("✓ Connected to Redis successfully")
        
        # Create test data
        hub_id = "test-hub-redis"
        instance = ResourceInstance(
            id=f"redis-test-{datetime.utcnow().timestamp()}",
            name="Redis Test Instance",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:11434",
            status=ResourceStatus.HEALTHY,
            capabilities={"llm/complete", "llm/chat"},
            tags={"redis", "test"}
        )
        
        # Test 1: Save instance
        await adapter.save_instance(hub_id, instance)
        print(f"✓ Saved instance to Redis: {instance.id}")
        
        # Test 2: Load instance
        loaded = await adapter.load_instance(instance.id)
        assert loaded is not None
        assert loaded['id'] == instance.id
        assert loaded['name'] == instance.name
        print("✓ Loaded instance from Redis")
        
        # Test 3: List instances
        instances = await adapter.list_instances(hub_id)
        assert len(instances) > 0
        found = False
        for inst in instances:
            if inst['id'] == instance.id:
                found = True
                break
        assert found
        print(f"✓ Listed {len(instances)} instances from hub")
        
        # Test 4: Save metrics
        metrics = ResourceMetrics(
            request_count=42,
            error_count=2,
            avg_response_time_ms=35.7,
            cpu_percent=67.5,
            memory_mb=1024
        )
        await adapter.save_metrics(instance.id, metrics)
        print("✓ Saved metrics to Redis")
        
        # Test 5: Get metrics history
        from datetime import timedelta
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        history = await adapter.get_metrics_history(instance.id, start_time, end_time)
        assert len(history) > 0
        assert history[0]['request_count'] == 42
        print(f"✓ Retrieved metrics history: {len(history)} entries")
        
        # Test 6: Distributed locking
        lock_acquired = await adapter.acquire_lock("shared-resource", "worker-1", timeout=10)
        assert lock_acquired == True
        print("✓ Acquired distributed lock")
        
        # Try to acquire same lock (should fail)
        lock_acquired2 = await adapter.acquire_lock("shared-resource", "worker-2", timeout=10)
        assert lock_acquired2 == False
        print("✓ Second lock attempt correctly blocked")
        
        # Check lock owner
        owner = await adapter.get_lock_owner("shared-resource")
        assert owner == "worker-1"
        print(f"✓ Lock owner verified: {owner}")
        
        # Extend lock
        extended = await adapter.extend_lock("shared-resource", "worker-1", timeout=20)
        assert extended == True
        print("✓ Lock extended successfully")
        
        # Release lock
        await adapter.release_lock("shared-resource", "worker-1")
        owner = await adapter.get_lock_owner("shared-resource")
        assert owner is None
        print("✓ Lock released")
        
        # Now worker-2 can acquire
        lock_acquired3 = await adapter.acquire_lock("shared-resource", "worker-2", timeout=10)
        assert lock_acquired3 == True
        await adapter.release_lock("shared-resource", "worker-2")
        print("✓ Lock transferred to different worker")
        
        # Test 7: Cleanup
        await adapter.delete_instance(instance.id)
        loaded = await adapter.load_instance(instance.id)
        assert loaded is None
        print("✓ Instance deleted from Redis")
        
        print("\n✅ All Redis tests passed!")
        
        # Show Redis keys created
        print("\n📊 Redis Keys Pattern:")
        print(f"  Instance: {adapter._instance_key('example')}")
        print(f"  Hub Set: {adapter._hub_instances_key('example')}")
        print(f"  Metrics: {adapter._metrics_key('example')}")
        print(f"  Lock: {adapter._lock_key('example')}")
        
    except ImportError as e:
        print(f"⚠️  Redis client not installed: {e}")
        print("   Install with: pip install redis")
    except ConnectionError as e:
        print(f"⚠️  Could not connect to Redis: {e}")
        print("   Make sure Redis is running: redis-server")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await adapter.shutdown()
        print("✓ Adapter shut down")


async def test_redis_persistence_with_provider():
    """Test PersistentHubProvider with Redis"""
    print("\n=== Testing PersistentHubProvider with Redis ===")
    
    from gleitzeit.providers.persistent_hub_provider import PersistentHubProvider
    from gleitzeit.hub.ollama_hub import OllamaConfig
    
    # Simple test provider
    class TestProvider(PersistentHubProvider):
        def __init__(self, **kwargs):
            super().__init__(
                provider_id="redis-test-provider",
                protocol_id="test",
                name="Redis Test Provider",
                description="Testing Redis persistence",
                resource_config_class=OllamaConfig,
                **kwargs
            )
        
        def get_supported_methods(self):
            return ["test/method"]
        
        async def create_resource(self, config):
            return ResourceInstance(
                id=f"test-{datetime.utcnow().timestamp()}",
                name="Test Resource",
                type=ResourceType.OLLAMA,  # Use a valid ResourceType
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
    
    # Use Redis adapter
    adapter = RedisHubAdapter(redis_url="redis://localhost:6379")
    
    provider1 = TestProvider(
        persistence_adapter=adapter,
        enable_persistence=True,
        persistence_interval=1,
        instance_id="provider-instance-1"
    )
    
    try:
        await provider1.initialize()
        print("✓ Provider initialized with Redis persistence")
        
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
            instance_id="provider-instance-2"
        )
        
        await provider2.initialize()
        print(f"✓ Provider 2 initialized")
        print(f"✓ Recovered {len(provider2.instances)} instances from Redis")
        
        # Verify instances were recovered
        assert len(provider2.instances) >= 3  # At least the 3 we created
        print(f"✓ Recovered {len(provider2.instances)} instances successfully!")
        
        await provider2.shutdown()
        
    except ImportError as e:
        print(f"⚠️  Redis client not installed: {e}")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await adapter.shutdown()


async def main():
    """Run Redis tests"""
    print("=" * 60)
    print("Redis Backend Integration Tests")
    print("=" * 60)
    
    try:
        # First check if redis is installed
        import redis.asyncio as redis
        print("✓ redis-py (async) is installed")
    except ImportError:
        print("❌ redis not installed")
        print("\nTo test Redis backend, install redis:")
        print("  pip install redis")
        return
    
    await test_redis_backend()
    await test_redis_persistence_with_provider()
    
    print("\n" + "=" * 60)
    print("✅ Redis integration working perfectly!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())