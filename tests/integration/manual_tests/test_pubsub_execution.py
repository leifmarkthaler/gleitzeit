#!/usr/bin/env python3
"""
Test task execution using Redis Pub/Sub.
"""

import asyncio
import logging
from datetime import datetime
from gleitzeit.core.models import Workflow, Task
from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.events.redis_pubsub_bus import RedisPubSubBus, PubSubWorker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_pubsub_execution():
    """Test workflow execution using Redis Pub/Sub."""
    
    logger.info("=== Setting up Pub/Sub System ===")
    persistence = await PersistenceFactory.create()
    
    # Get Redis client
    if not hasattr(persistence, 'redis'):
        logger.error("Redis not available - this test requires Redis")
        return False
    
    redis_client = persistence.redis
    
    # Create workers
    worker1 = PubSubWorker("worker-1", redis_client, persistence)
    await worker1.start()
    
    # Create event bus for submitting events
    bus = RedisPubSubBus(redis_client)
    await bus.start()
    
    # Create workflow
    workflow = Workflow(
        id=f'pubsub-test-{datetime.now().strftime("%H%M%S")}',
        name='PubSub Test',
        tasks=[
            Task(
                id='task1',
                name='First Task',
                protocol='python/v1',
                method='execute',
                parameters={'code': 'print("Task 1"); result = 1'}
            ),
            Task(
                id='task2',
                name='Second Task',
                protocol='python/v1',
                method='execute',
                parameters={'code': 'print("Task 2"); result = 2'},
                dependencies=['task1']
            ),
            Task(
                id='task3',
                name='Final Task',
                protocol='python/v1',
                method='execute',
                parameters={'code': 'print("Task 3"); result = 3'},
                dependencies=['task2']
            )
        ]
    )
    
    # Set workflow_id on tasks
    for task in workflow.tasks:
        task.workflow_id = workflow.id
    
    logger.info(f"=== Submitting Workflow {workflow.id} ===")
    
    # Save workflow
    await persistence.save_workflow(workflow)
    
    # Also save tasks individually (required for get_tasks_by_workflow)
    for task in workflow.tasks:
        await persistence.save_task(task)
    
    # Emit workflow submitted event
    await bus.emit(GleitzeitEvent(
        event_type=EventType.WORKFLOW_SUBMITTED,
        data={
            'workflow_id': workflow.id,
            'task_count': len(workflow.tasks)
        }
    ))
    
    logger.info("Workflow submitted event emitted")
    
    # Wait for execution
    logger.info("=== Waiting for Execution ===")
    max_wait = 10
    start_time = asyncio.get_event_loop().time()
    
    while asyncio.get_event_loop().time() - start_time < max_wait:
        # Check task status
        tasks = await persistence.get_tasks_by_workflow(workflow.id)
        
        statuses = []
        for task in tasks:
            status = task.status.value if hasattr(task.status, 'value') else task.status
            statuses.append(f"{task.id}:{status}")
        
        logger.info(f"Task statuses: {', '.join(statuses)}")
        
        # Check if all complete
        if all(
            task.status.value == 'completed' if hasattr(task.status, 'value') else task.status == 'completed'
            for task in tasks
        ):
            logger.info("✅ All tasks completed!")
            break
        
        await asyncio.sleep(1)
    
    # Check final status
    tasks = await persistence.get_tasks_by_workflow(workflow.id)
    completed = sum(1 for task in tasks if (
        task.status.value == 'completed' if hasattr(task.status, 'value') else task.status == 'completed'
    ))
    
    logger.info(f"Final: {completed}/{len(tasks)} tasks completed")
    
    # Cleanup
    await worker1.stop()
    await bus.stop()
    
    return completed == len(tasks)


if __name__ == "__main__":
    success = asyncio.run(test_pubsub_execution())
    if success:
        print("✅ ALL TASKS EXECUTED VIA PUB/SUB")
    else:
        print("❌ PUB/SUB EXECUTION FAILED")