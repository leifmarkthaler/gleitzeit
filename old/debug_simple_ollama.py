#!/usr/bin/env python3
"""
Debug Simple Ollama Task

Minimal test to identify the 'result not defined' issue.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from gleitzeit_v4.pooling.adapter import PoolingAdapter
from gleitzeit_v4.core.execution_engine import ExecutionEngine, ExecutionMode
from gleitzeit_v4.core.models import Task, TaskStatus, Priority
from gleitzeit_v4.queue.task_queue import QueueManager
from gleitzeit_v4.queue.dependency_resolver import DependencyResolver
from gleitzeit_v4.registry import ProtocolProviderRegistry
from gleitzeit_v4.persistence.base import InMemoryBackend
from gleitzeit_v4.providers.ollama_provider import OllamaProvider
import uuid
import logging

# Enable detailed logging
logging.basicConfig(level=logging.DEBUG)


async def debug_simple_ollama():
    """Debug simple Ollama task execution"""
    
    print("🔍 Debugging Simple Ollama Task")
    print("=" * 40)
    
    try:
        # Setup minimal components
        registry = ProtocolProviderRegistry()
        queue_manager = QueueManager()
        await queue_manager.get_default_queue().initialize()
        dependency_resolver = DependencyResolver()
        persistence = InMemoryBackend()
        
        # Create pooling adapter
        pooling_adapter = PoolingAdapter(registry=registry)
        await pooling_adapter.start()
        
        # Register Ollama provider
        ollama_config = {
            "provider_id": "debug-ollama",
            "ollama_url": "http://localhost:11434",
            "timeout": 10
        }
        
        await pooling_adapter.register_provider(
            protocol_id="llm/v1",
            provider_class=OllamaProvider,
            provider_config=ollama_config,
            min_workers=1,
            max_workers=1
        )
        
        await asyncio.sleep(1)
        
        # Create execution engine
        execution_engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=persistence,
            pooling_adapter=pooling_adapter
        )
        
        print("✓ ExecutionEngine ready")
        
        # Create a simple task
        task = Task(
            id=f"debug-{uuid.uuid4().hex[:8]}",
            name="Debug Task",
            method="generate",
            protocol="llm/v1", 
            params={
                "prompt": "Say hello",
                "model": "phi3:mini",
                "max_tokens": 10
            },
            priority=Priority.HIGH
        )
        
        print(f"✓ Created task: {task.id}")
        
        # Submit task
        await execution_engine.submit_task(task)
        print("✓ Task submitted")
        
        # Start execution engine in single-shot mode to process one task
        await execution_engine.start(mode=ExecutionMode.SINGLE_SHOT)
        print("✓ ExecutionEngine started in single-shot mode")
        
        # Wait for task to complete or fail
        print("\n⏳ Waiting for task completion...")
        for i in range(15):
            await asyncio.sleep(1)
            
            result = await persistence.get_task_result(task.id)
            print(f"   [{i+1:2d}/15] Task status: {result.status if result else 'pending'}")
            
            if result and result.status in ['completed', 'failed']:
                print(f"✅ Task finished with status: {result.status}")
                if result.status == 'completed':
                    print(f"   Result: {result.result}")
                else:
                    print(f"   Error: {result.error}")
                break
        else:
            print("❌ Task did not complete within 15 seconds")
        
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
        if 'pooling_adapter' in locals():
            try:
                await pooling_adapter.stop()
            except:
                pass


if __name__ == "__main__":
    success = asyncio.run(debug_simple_ollama())
    print(f"\n{'🎉 DEBUG SUCCESS' if success else '❌ DEBUG FAILED'}")
    exit(0 if success else 1)