#!/usr/bin/env python3
"""
Test task execution using Redis queue (no events needed).
"""

import asyncio
import logging
from datetime import datetime
from gleitzeit.core.models import Workflow, Task
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.core.redis_task_queue import RedisTaskQueue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def worker_process(queue: RedisTaskQueue, worker_id: str):
    """
    Worker process that polls queue and executes tasks.
    
    Args:
        queue: Redis task queue
        worker_id: Worker identifier
    """
    logger.info(f"Worker {worker_id} started")
    
    while True:
        # Get next task (blocks for 1 second)
        task_entry = await queue.dequeue_task(worker_id, timeout=1)
        
        if not task_entry:
            # No task available
            await asyncio.sleep(0.1)
            continue
        
        task_id = task_entry['task_id']
        workflow_id = task_entry['workflow_id']
        
        logger.info(f"Worker {worker_id} processing task {task_id}")
        
        try:
            # Get task details
            task = await queue.persistence.get_task(task_id)
            
            if task:
                # Simulate execution
                logger.info(f"Executing: {task.name}")
                await asyncio.sleep(1)  # Simulate work
                
                # Mark as complete
                await queue.complete_task(task_id, workflow_id)
                logger.info(f"Task {task_id} completed successfully")
            else:
                logger.error(f"Task {task_id} not found")
                
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            await queue.fail_task(task_id, str(e))


async def test_redis_queue():
    """Test workflow execution using Redis queue."""
    
    # Setup
    logger.info("=== Setting up Redis Queue System ===")
    persistence = await PersistenceFactory.create()
    
    # Get Redis client
    if not hasattr(persistence, 'redis'):
        logger.error("Redis not available - this test requires Redis")
        return False
    
    redis_client = persistence.redis
    
    # Create queue
    queue = RedisTaskQueue(redis_client, persistence)
    
    # Create workflow
    workflow = Workflow(
        id=f'queue-test-{datetime.now().strftime("%H%M%S")}',
        name='Queue Test',
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
    
    logger.info(f"=== Submitting Workflow {workflow.id} ===")
    
    # Save workflow
    await persistence.save_workflow(workflow)
    
    # Start worker in background
    worker_task = asyncio.create_task(worker_process(queue, 'worker-1'))
    
    # Submit workflow to queue
    ready_count = await queue.submit_workflow(workflow.id)
    logger.info(f"Submitted {ready_count} initial tasks to queue")
    
    # Check queue stats
    stats = await queue.get_queue_stats()
    logger.info(f"Queue stats: {stats}")
    
    # Wait for completion
    logger.info("=== Waiting for Execution ===")
    max_wait = 10
    start_time = asyncio.get_event_loop().time()
    
    while asyncio.get_event_loop().time() - start_time < max_wait:
        # Check workflow status
        final_workflow = await persistence.get_workflow(workflow.id)
        if final_workflow.status.value == 'completed':
            logger.info("✅ Workflow completed!")
            break
        
        # Check progress
        stats = await queue.get_queue_stats()
        logger.info(f"Progress - Ready: {stats['ready']}, Processing: {stats['processing']}, Completed: {stats['completed']}")
        
        await asyncio.sleep(1)
    
    # Check final status
    tasks = await persistence.get_tasks_by_workflow(workflow.id)
    for task in tasks:
        status = task.status.value if hasattr(task.status, 'value') else task.status
        logger.info(f"Task {task.id}: {status}")
    
    # Cancel worker
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    
    # Return success
    return all(
        task.status.value == 'completed' if hasattr(task.status, 'value') else task.status == 'completed'
        for task in tasks
    )


if __name__ == "__main__":
    success = asyncio.run(test_redis_queue())
    if success:
        print("✅ ALL TASKS EXECUTED SUCCESSFULLY")
    else:
        print("❌ TASKS DID NOT EXECUTE")