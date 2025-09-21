#!/usr/bin/env python3
"""
Debug retry limit issue
"""

import asyncio
import logging

logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(message)s')

async def main():
    from src.gleitzeit.persistence.factory import PersistenceFactory
    from src.gleitzeit.core.event_driven_retry_manager import EventDrivenRetryManager
    from src.gleitzeit.events.base import EventBus
    from src.gleitzeit.core.events import EventType, GleitzeitEvent
    from src.gleitzeit.core.models import Task, TaskStatus, TaskResult, RetryConfig
    from datetime import datetime
    
    print("=== Testing Stateless Retry Limit ===\n")
    
    # Create persistence and event bus
    persistence = await PersistenceFactory.create()
    event_bus = EventBus()
    
    # Create a task with retry config
    task = Task(
        id="test-task-003",
        workflow_id="test-workflow",
        name="test-task",
        protocol="llm/v1",
        method="generate",
        params={"model": "llama3.2"},
        retry_config=RetryConfig(max_attempts=3),
        metadata={}
    )
    
    # Save task to persistence
    await persistence.save_task(task)
    print(f"Created task with max_attempts=3, initial status={task.status}")
    
    # Also save a task result with the error
    result = TaskResult(
        task_id=task.id,
        status=TaskStatus.FAILED,
        error='[RESOURCE_EXHAUSTED] Failed to allocate Ollama resource',
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow()
    )
    await persistence.save_task_result(result)
    print(f"Saved task result with RESOURCE_EXHAUSTED error")
    
    # Create retry manager
    retry_manager = EventDrivenRetryManager(
        persistence=persistence,
        scheduler=None,
        event_bus=event_bus,
        max_retries=3
    )
    
    # Manually call the handler to see what happens
    print(f"\n--- Processing failure ---")
    event = GleitzeitEvent(
        event_type=EventType.TASK_FAILED,
        data={'task_id': task.id},
        source="test"
    )
    
    await retry_manager._on_task_failed(event)
    
    # Check task status
    updated_task = await persistence.get_task(task.id)
    if updated_task:
        print(f"After processing:")
        print(f"  Status: {updated_task.status}")
        print(f"  Metadata: {updated_task.metadata}")

if __name__ == "__main__":
    asyncio.run(main())