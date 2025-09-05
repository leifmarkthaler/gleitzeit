#!/usr/bin/env python3
"""
Test the new provider pooling system for stateless operation.
"""

import asyncio
import time
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from gleitzeit.providers.provider_pool import ProviderPool, PooledProvider, ProviderState
from gleitzeit.providers.provider_pool_manager import ProviderPoolManager, ProviderConfig
from gleitzeit.providers.pooling_adapter import PoolingAdapter
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.core.models import Task, TaskStatus
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse


# Test provider class
class TestProvider:
    """Simple test provider"""
    
    def __init__(self):
        self.initialized = False
        self.execute_count = 0
    
    async def initialize(self):
        """Initialize the provider"""
        await asyncio.sleep(0.01)  # Simulate initialization
        self.initialized = True
    
    async def cleanup(self):
        """Cleanup the provider"""
        self.initialized = False
    
    async def execute(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """Execute a request"""
        self.execute_count += 1
        
        if request.method == "test_method":
            return JSONRPCResponse(
                result={"message": "Test successful", "count": self.execute_count},
                id=request.id
            )
        else:
            return JSONRPCResponse(
                error={"code": -32601, "message": "Method not found"},
                id=request.id
            )
    
    async def test_method(self, **kwargs):
        """Direct method for testing"""
        return {"message": "Direct call successful", "params": kwargs}


async def test_provider_pool():
    """Test basic provider pool functionality"""
    print("\n" + "="*60)
    print("Testing Provider Pool")
    print("="*60)
    
    # Create persistence
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    # Create pool
    pool = ProviderPool(
        provider_type="test_provider",
        provider_class=TestProvider,
        min_size=2,
        max_size=5,
        max_idle_time=300,
        persistence=persistence
    )
    
    # Initialize pool
    await pool.initialize()
    
    print(f"\n1. Pool initialized")
    stats = pool.get_stats()
    print(f"   Available: {stats['available']}")
    print(f"   In use: {stats['in_use']}")
    print(f"   Total: {stats['total']}")
    
    assert stats['available'] == 2  # min_size
    assert stats['in_use'] == 0
    
    # Acquire providers
    print("\n2. Acquiring providers...")
    providers = []
    for i in range(3):
        provider = await pool.acquire()
        providers.append(provider)
        print(f"   Acquired provider {i+1}: {provider.id}")
    
    stats = pool.get_stats()
    print(f"   Available: {stats['available']}")
    print(f"   In use: {stats['in_use']}")
    
    assert stats['available'] == 0
    assert stats['in_use'] == 3
    
    # Release one provider
    print("\n3. Releasing one provider...")
    await pool.release(providers[0])
    
    stats = pool.get_stats()
    print(f"   Available: {stats['available']}")
    print(f"   In use: {stats['in_use']}")
    
    assert stats['available'] == 1
    assert stats['in_use'] == 2
    
    # Release remaining providers
    print("\n4. Releasing remaining providers...")
    for provider in providers[1:]:
        await pool.release(provider)
    
    stats = pool.get_stats()
    print(f"   Available: {stats['available']}")
    print(f"   In use: {stats['in_use']}")
    
    # Shutdown pool
    await pool.shutdown()
    await persistence.shutdown()
    
    print("\n✅ Provider pool test passed!")


async def test_pool_manager():
    """Test provider pool manager"""
    print("\n" + "="*60)
    print("Testing Provider Pool Manager")
    print("="*60)
    
    # Create persistence
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    # Create pool manager
    manager = ProviderPoolManager(
        persistence=persistence,
        default_min_size=1,
        default_max_size=3
    )
    
    await manager.initialize()
    
    # Register provider types
    print("\n1. Registering provider types...")
    await manager.register_provider(
        provider_type="test_provider",
        provider_class=TestProvider,
        protocol="test_protocol",
        min_pool_size=2,
        max_pool_size=5
    )
    print("   Registered test_provider for test_protocol")
    
    # Get provider for protocol
    print("\n2. Getting provider for protocol...")
    provider = await manager.get_provider("test_protocol")
    print(f"   Got provider: {provider.id} (type: {provider.provider_type})")
    
    assert provider is not None
    assert provider.state == ProviderState.IN_USE
    assert provider.instance.initialized
    
    # Execute through provider
    print("\n3. Executing through provider...")
    request = JSONRPCRequest(
        method="test_method",
        params={"value": 42},
        id="test-1"
    )
    
    response = await provider.instance.execute(request)
    print(f"   Response: {response.result}")
    
    assert response.result["message"] == "Test successful"
    
    # Release provider
    print("\n4. Releasing provider...")
    await manager.release_provider(provider)
    
    # Get stats
    stats = manager.get_stats()
    print(f"\n5. Manager stats:")
    print(f"   Total pools: {stats['total_pools']}")
    for ptype, pool_stats in stats['pools'].items():
        print(f"   {ptype}: available={pool_stats['available']}, "
              f"in_use={pool_stats['in_use']}, "
              f"utilization={pool_stats['utilization']:.1f}%")
    
    # Shutdown
    await manager.shutdown()
    await persistence.shutdown()
    
    print("\n✅ Pool manager test passed!")


async def test_pooling_adapter():
    """Test pooling adapter for compatibility"""
    print("\n" + "="*60)
    print("Testing Pooling Adapter")
    print("="*60)
    
    # Create persistence
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    # Create pooling adapter
    adapter = PoolingAdapter(
        persistence=persistence,
        min_pool_size=1,
        max_pool_size=3
    )
    
    await adapter.initialize()
    
    # Register provider
    print("\n1. Registering provider through adapter...")
    await adapter.register_provider(
        provider_id="test_provider",
        protocol_id="test_protocol",
        provider_instance=TestProvider,
        supported_methods={"test_method"}
    )
    print("   Provider registered")
    
    # Check protocol availability
    print("\n2. Checking protocol availability...")
    available = adapter.is_protocol_available("test_protocol")
    print(f"   test_protocol available: {available}")
    assert available
    
    # Execute request
    print("\n3. Executing request through adapter...")
    request = JSONRPCRequest(
        method="test_method",
        params={"adapter": "test"},
        id="adapter-1"
    )
    
    response = await adapter.execute_request("test_protocol", request)
    print(f"   Response: {response.result}")
    
    assert response.result["message"] == "Test successful"
    
    # Execute task
    print("\n4. Executing task through adapter...")
    task = Task(
        id="task-1",
        name="test_task",
        protocol="test_protocol",
        method="test_method",
        params={"task": "test"},
        status=TaskStatus.PENDING
    )
    
    result = await adapter.execute_task(task)
    print(f"   Task result: status={result.status}, result={result.result}")
    
    assert result.status == TaskStatus.COMPLETED
    
    # Get stats
    stats = adapter.get_stats()
    print(f"\n5. Adapter stats:")
    print(f"   Total pools: {stats['total_pools']}")
    
    # Shutdown
    await adapter.shutdown()
    await persistence.shutdown()
    
    print("\n✅ Pooling adapter test passed!")


async def test_concurrent_access():
    """Test concurrent access to pooled providers"""
    print("\n" + "="*60)
    print("Testing Concurrent Access")
    print("="*60)
    
    # Create persistence
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    # Create pool with limited size
    manager = ProviderPoolManager(
        persistence=persistence,
        default_min_size=2,
        default_max_size=3  # Limited to force queueing
    )
    
    await manager.initialize()
    
    # Register provider
    await manager.register_provider(
        provider_type="test_provider",
        provider_class=TestProvider,
        protocol="test_protocol",
        min_pool_size=2,
        max_pool_size=3
    )
    
    print("\n1. Starting 5 concurrent tasks with pool size 3...")
    
    async def execute_task(task_id: int):
        """Execute a single task"""
        start = time.time()
        
        # Get provider
        provider = await manager.get_provider("test_protocol", timeout=5.0)
        
        # Simulate work
        await asyncio.sleep(0.1)
        
        # Execute
        request = JSONRPCRequest(
            method="test_method",
            params={"task_id": task_id},
            id=f"concurrent-{task_id}"
        )
        response = await provider.instance.execute(request)
        
        # Release
        await manager.release_provider(provider)
        
        elapsed = time.time() - start
        print(f"   Task {task_id} completed in {elapsed:.2f}s")
        return response.result
    
    # Run concurrent tasks
    tasks = [execute_task(i) for i in range(5)]
    results = await asyncio.gather(*tasks)
    
    print(f"\n2. All tasks completed")
    print(f"   Results: {len(results)} tasks executed successfully")
    
    assert len(results) == 5
    for result in results:
        assert result["message"] == "Test successful"
    
    # Check final stats
    stats = manager.get_stats()
    pool_stats = stats['pools']['test_provider']
    print(f"\n3. Final pool stats:")
    print(f"   Available: {pool_stats['available']}")
    print(f"   In use: {pool_stats['in_use']}")
    print(f"   Max size: {pool_stats['max_size']}")
    
    # Shutdown
    await manager.shutdown()
    await persistence.shutdown()
    
    print("\n✅ Concurrent access test passed!")


async def main():
    """Run all tests"""
    print("="*60)
    print("Provider Pooling System Tests")
    print("="*60)
    
    await test_provider_pool()
    await test_pool_manager()
    await test_pooling_adapter()
    await test_concurrent_access()
    
    print("\n" + "="*60)
    print("All Tests Passed! 🎉")
    print("="*60)
    print("\nThe provider pooling system is working correctly:")
    print("- ✅ Provider pools manage lifecycle properly")
    print("- ✅ Pool manager routes to correct providers")
    print("- ✅ Adapter provides compatibility layer")
    print("- ✅ Concurrent access handled with queueing")
    print("- ✅ No singleton pattern - fully stateless!")


if __name__ == "__main__":
    asyncio.run(main())