#!/usr/bin/env python3
"""
Simple integration test for pooled provider system.

Tests the pooled provider execution without the full execution engine.
"""

import asyncio
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from gleitzeit.core.models import Task, TaskStatus
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse
from gleitzeit.providers.pooling_adapter import PoolingAdapter
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter


class SimpleTestProvider:
    """Simple test provider"""
    
    def __init__(self):
        self.initialized = False
        self.execute_count = 0
    
    async def initialize(self):
        """Initialize the provider"""
        self.initialized = True
        print(f"      Provider initialized")
    
    async def cleanup(self):
        """Cleanup the provider"""
        self.initialized = False
    
    async def execute(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """Execute a request"""
        self.execute_count += 1
        print(f"      Provider executing request {request.id} (count: {self.execute_count})")
        
        # Simulate work
        await asyncio.sleep(0.01)
        
        return JSONRPCResponse(
            result={"message": "Success", "count": self.execute_count},
            id=request.id
        )


async def test_simple_pooled_execution():
    """Test basic pooled provider execution"""
    print("\n" + "="*60)
    print("Testing Simple Pooled Provider Execution")
    print("="*60)
    
    # Create persistence
    print("\n1. Setting up components...")
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    print("   Persistence initialized")
    
    # Create pooling adapter
    pooling_adapter = PoolingAdapter(
        persistence=persistence,
        min_pool_size=1,
        max_pool_size=3
    )
    await pooling_adapter.initialize()
    print("   Pooling adapter initialized")
    
    # Register test provider
    print("\n2. Registering provider...")
    await pooling_adapter.register_provider(
        provider_id="test_provider",
        protocol_id="test/v1",
        provider_instance=SimpleTestProvider,
        supported_methods={"test_method"}
    )
    print("   Provider registered")
    
    # Execute a simple task
    print("\n3. Executing task through pooling adapter...")
    task = Task(
        id="simple-task-1",
        name="Simple Test Task",
        protocol="test/v1",
        method="test_method",
        params={"value": 42},
        status=TaskStatus.PENDING
    )
    
    result = await pooling_adapter.execute_task(task)
    print(f"   Task result: status={result.status}, task_id={result.task_id}")
    
    assert result.status == TaskStatus.COMPLETED
    assert result.task_id == "simple-task-1"
    
    # Execute multiple tasks
    print("\n4. Executing multiple tasks concurrently...")
    tasks = []
    for i in range(5):
        task = Task(
            id=f"concurrent-task-{i}",
            name=f"Concurrent Task {i}",
            protocol="test/v1",
            method="test_method",
            params={"value": i},
            status=TaskStatus.PENDING
        )
        tasks.append(pooling_adapter.execute_task(task))
    
    results = await asyncio.gather(*tasks)
    print(f"   Executed {len(results)} tasks")
    
    for i, result in enumerate(results):
        print(f"   Task {i}: {result.status}")
        assert result.status == TaskStatus.COMPLETED
    
    # Get pool stats
    stats = pooling_adapter.get_stats()
    print(f"\n5. Pool statistics:")
    print(f"   Total pools: {stats['total_pools']}")
    for pool_name, pool_stats in stats['pools'].items():
        print(f"   {pool_name}: {pool_stats}")
    
    # Cleanup
    print("\n6. Cleaning up...")
    await pooling_adapter.shutdown()
    await persistence.shutdown()
    print("   Cleanup complete")
    
    print("\n✅ Simple pooled execution test passed!")


async def main():
    """Run simple pooled provider test"""
    print("="*60)
    print("Simple Pooled Provider Integration Test")
    print("="*60)
    
    await test_simple_pooled_execution()
    
    print("\n" + "="*60)
    print("Test Complete! 🎉")
    print("="*60)
    print("\nThe pooled provider system works correctly:")
    print("- ✅ Provider registration successful")
    print("- ✅ Task execution through pools works")
    print("- ✅ Concurrent task handling works")
    print("- ✅ Pool statistics available")


if __name__ == "__main__":
    asyncio.run(main())