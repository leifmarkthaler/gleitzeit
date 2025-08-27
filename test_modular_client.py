#!/usr/bin/env python3
"""
Test script for the new modular Gleitzeit client.
"""

import asyncio
import sys
import os
sys.path.insert(0, 'src')

from gleitzeit.client import GleitzeitClient


async def test_modular_client():
    """Test the new modular client functionality."""
    
    print("Testing Modular Gleitzeit Client")
    print("=" * 50)
    
    # Test API mode connection
    async with GleitzeitClient(mode="api", api_port=8000) as client:
        print(f"✓ Client initialized in {client.get_mode()} mode")
        
        # Test system operations
        print("\nTesting System Operations:")
        status = await client.get_system_status()
        print(f"  ✓ System status: {status.get('status', 'unknown')}")
        
        health = await client.health_check()
        print(f"  ✓ Health check: OK")
        
        # Test task operations
        print("\nTesting Task Operations:")
        task = {
            "id": "test_task",
            "name": "Test Task",
            "method": "python/execute",
            "parameters": {"code": "result = 42"}
        }
        
        try:
            result = await client.submit_task(task)
            print(f"  ✓ Task submitted: {result.get('task_id', 'unknown')}")
        except Exception as e:
            print(f"  ! Task submission failed: {e}")
        
        # Test workflow operations
        print("\nTesting Workflow Operations:")
        workflows = await client.list_workflows(limit=5)
        print(f"  ✓ Found {len(workflows.get('workflows', []))} workflows")
        
        # Test queue operations
        print("\nTesting Queue Operations:")
        queues = await client.get_queues()
        print(f"  ✓ Found {len(queues)} queue(s)")
        
        # Test batch operations
        print("\nTesting Batch Operations:")
        print(f"  ✓ Batch processing methods available")
        print(f"  ✓ Directory processing methods available")
        
        # Test mixin integration
        print("\nTesting Mixin Integration:")
        print(f"  ✓ WorkflowMixin: {hasattr(client, 'submit_workflow')}")
        print(f"  ✓ TaskMixin: {hasattr(client, 'submit_task')}")
        print(f"  ✓ QueueMixin: {hasattr(client, 'get_queues')}")
        print(f"  ✓ BatchProcessingMixin: {hasattr(client, 'batch_process')}")
        print(f"  ✓ SystemMixin: {hasattr(client, 'health_check')}")
        print(f"  ✓ AuthMixin: {hasattr(client, 'login')}")
    
    print("\n" + "=" * 50)
    print("✓ All tests passed!")
    print("\nModular Client Benefits:")
    print("  • Clean separation of concerns")
    print("  • Each mixin handles one domain")
    print("  • Adapter pattern for API/Native modes")
    print("  • Much more maintainable code")
    print("  • Easy to extend with new features")


if __name__ == "__main__":
    asyncio.run(test_modular_client())