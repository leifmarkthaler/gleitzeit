#!/usr/bin/env python3
"""
Test the complete system with Pub/Sub event bus.
"""

import asyncio
import logging
from datetime import datetime
from gleitzeit.core.models import Workflow, Task
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.system.system_manager import SystemManager
from gleitzeit.system.models import SystemConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_complete_pubsub_system():
    """Test complete workflow execution with Pub/Sub event bus."""
    
    logger.info("=== Initializing System with Pub/Sub ===")
    
    # Create system
    persistence = await PersistenceFactory.create()
    
    # Verify we have Redis
    if not hasattr(persistence, 'redis'):
        logger.error("Redis not available - Pub/Sub requires Redis")
        return False
    
    config = SystemConfig(
        environment='development',
        deployment_mode='development'
    )
    
    system_manager = SystemManager(
        config=config,
        persistence=persistence
    )
    
    # Initialize and start
    await system_manager.initialize()
    
    # Check that we're using PubSubEventBus
    if system_manager.event_bus.__class__.__name__ != 'PubSubEventBus':
        logger.error(f"Not using PubSubEventBus! Got: {system_manager.event_bus.__class__.__name__}")
        return False
    
    logger.info("✓ System using PubSubEventBus")
    
    await system_manager.start_system()
    
    logger.info("✓ System started successfully")
    
    # Create a test workflow
    workflow = Workflow(
        id=f'pubsub-system-test-{datetime.now().strftime("%H%M%S")}',
        name='Complete Pub/Sub Test',
        tasks=[
            Task(
                id='task1',
                name='First Task',
                protocol='python/v1',
                method='execute',
                parameters={'code': 'print("TASK 1 EXECUTING"); result = {"status": "ok", "value": 1}'}
            ),
            Task(
                id='task2',
                name='Second Task',
                protocol='python/v1',
                method='execute',
                parameters={'code': 'print("TASK 2 EXECUTING"); result = {"status": "ok", "value": 2}'},
                dependencies=['task1']
            ),
            Task(
                id='task3',
                name='Final Task',
                protocol='python/v1',
                method='execute',
                parameters={'code': 'print("TASK 3 EXECUTING"); result = {"status": "ok", "value": 3}'},
                dependencies=['task2']
            )
        ]
    )
    
    logger.info(f"=== Executing Workflow {workflow.id} ===")
    
    # Save workflow
    await persistence.save_workflow(workflow)
    
    # Save tasks individually
    for task in workflow.tasks:
        task.workflow_id = workflow.id
        await persistence.save_task(task)
    
    # Execute via workflow manager
    result = await system_manager.workflow_manager.execute_workflow(workflow)
    logger.info(f"Workflow execution initiated: {result}")
    
    # Monitor execution
    logger.info("=== Monitoring Execution ===")
    max_wait = 15
    check_interval = 1
    start_time = asyncio.get_event_loop().time()
    
    while asyncio.get_event_loop().time() - start_time < max_wait:
        # Get task statuses
        tasks = await persistence.get_tasks_by_workflow(workflow.id)
        
        # Check statuses
        statuses = {}
        for task in tasks:
            status = task.status.value if hasattr(task.status, 'value') else task.status
            statuses[task.id] = status
        
        logger.info(f"Task statuses: {statuses}")
        
        # Check if all completed
        if all(status == 'completed' for status in statuses.values()):
            logger.info("✅ All tasks completed!")
            break
        
        # Check if any failed
        if any(status == 'failed' for status in statuses.values()):
            logger.error("❌ Task execution failed")
            break
        
        await asyncio.sleep(check_interval)
    
    # Get final workflow status
    final_workflow = await persistence.get_workflow(workflow.id)
    workflow_status = final_workflow.status.value if hasattr(final_workflow.status, 'value') else final_workflow.status
    
    logger.info(f"Final workflow status: {workflow_status}")
    
    # Check results
    success = workflow_status == 'completed'
    
    if success:
        logger.info("=== Workflow Completed Successfully ===")
        
        # Verify all tasks completed in order
        tasks = await persistence.get_tasks_by_workflow(workflow.id)
        for task in sorted(tasks, key=lambda t: t.id):
            status = task.status.value if hasattr(task.status, 'value') else task.status
            logger.info(f"  {task.id}: {status}")
    
    # Shutdown
    logger.info("=== Shutting Down System ===")
    await system_manager.shutdown_system()
    await system_manager.shutdown()
    
    return success


if __name__ == "__main__":
    success = asyncio.run(test_complete_pubsub_system())
    if success:
        print("\n✅ COMPLETE SYSTEM WORKS WITH PUB/SUB EVENT BUS")
    else:
        print("\n❌ SYSTEM TEST FAILED")