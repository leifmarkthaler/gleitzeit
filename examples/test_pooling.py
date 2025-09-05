#!/usr/bin/env python3
"""
Test script to verify provider pooling is working.
"""

import asyncio
from gleitzeit.client import GleitzeitClient

async def main():
    """Test pooling integration."""
    
    print("Starting Gleitzeit with provider pooling...")
    
    # Create client with pooling configuration
    client = GleitzeitClient(
        mode="native",
        enable_pooling=True,  # Enable provider pooling
        min_pool_size=2,      # Minimum pool size
        max_pool_size=5,      # Maximum pool size
        max_concurrent_tasks=10
    )
    
    await client.initialize()
    
    print("Client initialized with pooling enabled!")
    
    # Check if pooling adapter was created
    if hasattr(client._adapter, 'execution_engine'):
        engine = client._adapter.execution_engine
        if hasattr(engine, 'task_executor') and engine.task_executor.pooling_adapter:
            print("✅ SUCCESS: PoolingAdapter is active!")
            adapter = engine.task_executor.pooling_adapter
            print(f"   Pool configuration: {adapter.min_pool_size}-{adapter.max_pool_size} providers")
        else:
            print("❌ FAILED: PoolingAdapter not found in task executor")
    else:
        print("❌ FAILED: Could not access execution engine")
    
    # Cleanup
    await client.shutdown()
    print("Test complete!")

if __name__ == "__main__":
    asyncio.run(main())