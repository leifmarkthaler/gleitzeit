#!/usr/bin/env python3
"""
Debug Event-Driven Retry System

Simple test to verify retry events are properly handled.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from gleitzeit_v4.core.execution_engine import ExecutionEngine, ExecutionMode
from gleitzeit_v4.core.models import Task, TaskStatus, Priority, RetryConfig
from gleitzeit_v4.queue.task_queue import QueueManager
from gleitzeit_v4.queue.dependency_resolver import DependencyResolver
from gleitzeit_v4.registry import ProtocolProviderRegistry
from gleitzeit_v4.persistence.base import InMemoryBackend
import uuid
import logging

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def debug_event_driven_retry():
    """Debug event-driven retry system"""
    
    print("🔄 Debugging Event-Driven Retry System")
    print("=" * 50)
    
    try:
        # Setup basic components (no providers needed)
        registry = ProtocolProviderRegistry()
        queue_manager = QueueManager()
        await queue_manager.get_default_queue().initialize()
        dependency_resolver = DependencyResolver()
        persistence = InMemoryBackend()
        
        # Create execution engine
        execution_engine = ExecutionEngine(
            registry=registry,
            queue_manager=queue_manager,
            dependency_resolver=dependency_resolver,
            persistence=persistence
        )
        
        print("✓ ExecutionEngine created with event-driven retry")
        
        # Verify scheduler is connected to retry manager
        assert execution_engine.retry_manager.scheduler is not None
        print("✓ EventScheduler connected to RetryManager")
        
        # Create a simple task with retry config
        task = Task(
            id=f"debug-retry-{uuid.uuid4().hex[:8]}",
            name="Debug Retry Task",
            method="debug_method",
            protocol="debug/v1",
            params={"test": "data"},
            retry_config=RetryConfig(
                max_attempts=2,
                backoff_strategy="fixed",
                base_delay=2.0  # 2 second delay
            )
        )
        
        print(f"✓ Created task: {task.id}")
        
        # Start execution engine components without continuous processing
        await execution_engine.scheduler.start()
        print("✓ EventScheduler started")
        
        # Test retry scheduling
        print("\n🔄 Testing retry scheduling...")
        
        # Simulate a failed task that needs retry
        task.increment_attempt()  # Make it attempt 1
        retry_scheduled = await execution_engine.retry_manager.schedule_retry(
            task=task, 
            error_message="Debug test error"
        )
        
        print(f"✓ Retry scheduled: {retry_scheduled}")
        
        if retry_scheduled:
            print(f"✓ Task {task.id} scheduled for retry in 2 seconds")
            
            # Get retry stats
            stats = await execution_engine.get_retry_stats()
            print(f"✓ Retry stats: {stats}")
            
            # Wait for the retry event to be processed
            print("\n⏳ Waiting for retry event (5 seconds)...")
            
            for i in range(5):
                await asyncio.sleep(1)
                
                # Check if task was re-queued
                queue_size = queue_manager.get_default_queue().size()
                print(f"   Queue size: {queue_size} (waiting {i+1}/5)")
                
                if queue_size > 0:
                    print("✅ Task appeared in queue - retry event processed!")
                    break
            else:
                print("❌ Task never appeared in queue - retry event not processed")
        
        # Stop scheduler
        await execution_engine.scheduler.stop()
        print("✓ EventScheduler stopped")
        
        return True
        
    except Exception as e:
        print(f"💥 Debug failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        if 'execution_engine' in locals():
            try:
                await execution_engine.scheduler.stop()
            except:
                pass


if __name__ == "__main__":
    success = asyncio.run(debug_event_driven_retry())
    print(f"\n{'🎉 DEBUG SUCCESS' if success else '❌ DEBUG FAILED'}")
    exit(0 if success else 1)