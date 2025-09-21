#!/usr/bin/env python3
"""
Test that retry limits work in a stateless system
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(message)s')

async def main():
    from src.gleitzeit.persistence.factory import PersistenceFactory
    from src.gleitzeit.core.event_driven_retry_manager import EventDrivenRetryManager
    from src.gleitzeit.events.base import EventBus
    from src.gleitzeit.core.events import EventType, GleitzeitEvent
    from src.gleitzeit.core.models import Task, TaskStatus, RetryConfig
    
    print("=== Testing Stateless Retry Limit ===\n")
    
    # Create persistence and event bus
    persistence = await PersistenceFactory.create()
    event_bus = EventBus()
    
    # Create a task with retry config
    task = Task(
        id="test-task-001",
        workflow_id="test-workflow",
        name="test-task",
        protocol="llm/v1",
        method="generate",
        params={"model": "llama3.2"},
        retry_config=RetryConfig(max_attempts=3),
        metadata={}  # Start with no retry attempts
    )
    
    # Save task to persistence
    await persistence.save_task(task)
    print(f"Created task with max_attempts=3")
    
    # Create retry manager
    retry_manager = EventDrivenRetryManager(
        persistence=persistence,
        scheduler=None,
        event_bus=event_bus,
        max_retries=3
    )
    
    # Simulate multiple failures in a stateless manner
    for i in range(5):  # Try 5 times to test the limit
        print(f"\n--- Simulating failure #{i+1} ---")
        
        # Save a task result with the error (stateless system reads from persistence)
        from src.gleitzeit.core.models import TaskResult
        from datetime import datetime
        
        result = TaskResult(
            task_id=task.id,
            status=TaskStatus.FAILED,
            error='[RESOURCE_EXHAUSTED] Ollama not available',
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        await persistence.save_task_result(result)
        
        # Create a new retry manager instance each time (simulating stateless)
        new_retry_manager = EventDrivenRetryManager(
            persistence=persistence,
            scheduler=None,
            event_bus=event_bus,
            max_retries=3
        )
        
        # Emit a task failed event (minimal, stateless)
        event = GleitzeitEvent(
            event_type=EventType.TASK_FAILED,
            data={'task_id': task.id},
            source="test"
        )
        
        # Process the failure
        await new_retry_manager._on_task_failed(event)
        
        # Check task status in persistence
        updated_task = await persistence.get_task(task.id)
        if updated_task:
            retry_attempt = updated_task.metadata.get('retry_attempt', 0) if updated_task.metadata else 0
            max_reached = updated_task.metadata.get('max_retries_reached', False) if updated_task.metadata else False
            
            print(f"  Task status: {updated_task.status}")
            print(f"  Retry attempt: {retry_attempt}")
            print(f"  Max retries reached: {max_reached}")
            
            if max_reached:
                print("\n✓ SUCCESS: Task correctly stopped retrying after max attempts!")
                break
        else:
            print("  ERROR: Task not found in persistence!")
    
    # Final check
    final_task = await persistence.get_task(task.id)
    if final_task and final_task.metadata:
        if final_task.metadata.get('max_retries_reached'):
            print("\n=== TEST PASSED ===")
            print(f"Task stopped after {final_task.metadata.get('retry_attempt', 0)} attempts")
        else:
            print("\n=== TEST FAILED ===")
            print("Task did not stop after max attempts")
    else:
        print("\n=== TEST ERROR ===")
        print("Could not verify final task state")

if __name__ == "__main__":
    asyncio.run(main())