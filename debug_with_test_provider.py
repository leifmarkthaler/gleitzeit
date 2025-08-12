#!/usr/bin/env python3
"""
Debug Task with Test Provider

Test that tasks work correctly with a real provider after the 'result not defined' fix.
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
from gleitzeit_v4.providers.base import ProtocolProvider
import uuid
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)


class TestProvider(ProtocolProvider):
    """Simple test provider"""
    
    async def initialize(self) -> None:
        """Initialize the provider"""
        pass
    
    async def shutdown(self) -> None:
        """Shutdown the provider"""
        pass
    
    async def health_check(self) -> bool:
        """Check provider health"""
        return True
    
    async def handle_request(self, request):
        """Handle test requests"""
        if request.method == "test_method":
            # Return a successful result
            return {
                "message": "Test successful",
                "input_params": request.params,
                "provider_id": self.provider_id
            }
        else:
            raise ValueError(f"Unknown method: {request.method}")


async def debug_with_test_provider():
    """Debug task execution with test provider"""
    
    print("🧪 Testing Task with Test Provider")
    print("=" * 40)
    
    try:
        # Setup components
        registry = ProtocolProviderRegistry()
        queue_manager = QueueManager()
        await queue_manager.get_default_queue().initialize()
        dependency_resolver = DependencyResolver()
        persistence = InMemoryBackend()
        
        # Create and register protocol first
        from gleitzeit_v4.core.protocol import ProtocolSpec, MethodSpec
        protocol_spec = ProtocolSpec(
            protocol_id="test/v1",
            name="Test Protocol",
            description="Simple test protocol",
            version="1.0.0",
            methods=[
                MethodSpec(
                    name="test_method",
                    description="Test method",
                    params_schema={"type": "object"},
                    return_schema={"type": "object"}
                )
            ]
        )
        registry.register_protocol(protocol_spec)
        print("✓ Test protocol registered")
        
        # Create and register test provider
        test_provider = TestProvider(
            provider_id="test-provider",
            protocol_id="test/v1",
            name="Test Provider"
        )
        
        registry.register_provider(
            provider_id="test-provider",
            protocol_id="test/v1", 
            provider_instance=test_provider
        )
        print("✓ Test provider registered")
        
        # Create execution engine
        execution_engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=persistence
        )
        
        print("✓ ExecutionEngine ready with test provider")
        
        # Create a task that should succeed
        task = Task(
            id=f"test-{uuid.uuid4().hex[:8]}",
            name="Test Task",
            method="test_method",
            protocol="test/v1",
            params={"test_param": "test_value", "number": 42},
            priority=Priority.HIGH
        )
        
        print(f"✓ Created test task: {task.id}")
        
        # Submit task
        await execution_engine.submit_task(task)
        print("✓ Task submitted")
        
        # Start execution engine in single-shot mode
        await execution_engine.start(mode=ExecutionMode.SINGLE_SHOT)
        print("✓ ExecutionEngine started in single-shot mode")
        
        # Wait for task to complete
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
                    
                # Check if this is the success case we're testing
                if result.status == 'completed':
                    print("✅ SUCCESS PATH TESTED: Task completed without 'result not defined' error")
                    return True
                break
        else:
            print("❌ Task did not complete within 10 seconds")
        
        # Stop execution engine
        await execution_engine.stop()
        
        return False
        
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
    success = asyncio.run(debug_with_test_provider())
    print(f"\n{'🎉 TEST PROVIDER SUCCESS' if success else '❌ TEST PROVIDER FAILED'}")
    exit(0 if success else 1)