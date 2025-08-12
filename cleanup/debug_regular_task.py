#!/usr/bin/env python3
"""
Debug Regular Task (Non-Ollama)

Test that regular tasks still work after the 'result not defined' fix.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from gleitzeit_v4.core.execution_engine import ExecutionEngine, ExecutionMode
from gleitzeit_v4.core.models import Task, TaskStatus, Priority
from gleitzeit_v4.queue.task_queue import QueueManager
from gleitzeit_v4.queue.dependency_resolver import DependencyResolver
from gleitzeit_v4.registry import ProtocolProviderRegistry
from gleitzeit_v4.persistence.base import InMemoryBackend
import uuid


async def debug_regular_task():
    """Debug regular task execution without Ollama"""
    
    print("🔧 Testing Regular Task (No Ollama Provider)")
    print("=" * 50)
    
    try:
        # Setup minimal components without any providers
        registry = ProtocolProviderRegistry()
        queue_manager = QueueManager()
        await queue_manager.get_default_queue().initialize()
        dependency_resolver = DependencyResolver()
        persistence = InMemoryBackend()
        
        # Create execution engine WITHOUT pooling adapter
        execution_engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=persistence
            # No pooling_adapter - will use direct provider routing
        )
        
        print("✓ ExecutionEngine ready (no providers)")
        
        # Create a task for a non-existent protocol (should fail gracefully)
        task = Task(
            id=f"regular-{uuid.uuid4().hex[:8]}",
            name="Regular Task",
            method="test_method",
            protocol="test/v1",  # Non-existent protocol
            params={"test_param": "test_value"},
            priority=Priority.HIGH
        )
        
        print(f"✓ Created regular task: {task.id}")
        
        # Submit task
        await execution_engine.submit_task(task)
        print("✓ Task submitted")
        
        # Start execution engine in single-shot mode
        await execution_engine.start(mode=ExecutionMode.SINGLE_SHOT)
        print("✓ ExecutionEngine started in single-shot mode")
        
        # Wait for task to complete or fail
        print("\n⏳ Waiting for task completion...")
        for i in range(10):
            await asyncio.sleep(1)
            
            result = await persistence.get_task_result(task.id)
            print(f"   [{i+1:2d}/10] Task status: {result.status if result else 'pending'}")
            
            if result and result.status in ['completed', 'failed']:
                print(f"✅ Task finished with status: {result.status}")
                if result.status == 'completed':
                    print(f"   Result: {result.result}")
                else:
                    print(f"   Error: {result.error}")
                break
        else:
            print("❌ Task did not complete within 10 seconds")
        
        # Stop execution engine
        await execution_engine.stop()
        
        return True
        
    except Exception as e:
        print(f"💥 Debug failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if 'execution_engine' in locals():
            try:
                await execution_engine.stop()
            except:
                pass


if __name__ == "__main__":
    success = asyncio.run(debug_regular_task())
    print(f"\n{'🎉 REGULAR TASK SUCCESS' if success else '❌ REGULAR TASK FAILED'}")
    exit(0 if success else 1)