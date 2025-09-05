#!/usr/bin/env python3
"""
Test task execution through the complete pipeline.
"""

import asyncio
import logging
from datetime import datetime
from gleitzeit.core.models import Workflow, Task
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.system.system_manager import SystemManager
from gleitzeit.system.models import SystemConfig

# Enable DEBUG logging for event system
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Also set specific loggers to DEBUG
logging.getLogger('gleitzeit.events').setLevel(logging.DEBUG)
logging.getLogger('gleitzeit.task_queue').setLevel(logging.DEBUG)
logging.getLogger('gleitzeit.core.task_orchestrator').setLevel(logging.DEBUG)


async def test_task_execution():
    """Test that tasks actually execute."""
    
    logger.info("=== Setting up System ===")
    persistence = await PersistenceFactory.create()
    config = SystemConfig(environment='development', deployment_mode='development')
    system_manager = SystemManager(config=config, persistence=persistence)
    
    await system_manager.initialize()
    await system_manager.start_system()
    
    logger.info("=== System Ready ===")
    
    # Create a simple workflow with one task
    workflow = Workflow(
        id=f'exec-test-{datetime.now().strftime("%H%M%S")}',
        name='Execution Test',
        tasks=[
            Task(
                id='simple-task',
                name='Simple Task',
                protocol='python/v1',
                method='execute',
                parameters={'code': 'print("TASK EXECUTING!"); result = "SUCCESS"'}
            )
        ]
    )
    
    logger.info(f"=== Submitting Workflow {workflow.id} ===")
    
    # Store workflow
    await persistence.save_workflow(workflow)
    logger.info("Workflow saved to persistence")
    
    # Execute workflow
    result = await system_manager.workflow_manager.execute_workflow(workflow)
    logger.info(f"Workflow execution started: {result}")
    
    # Wait a bit for processing
    logger.info("=== Waiting for Task Execution ===")
    await asyncio.sleep(5)
    
    # Check task status
    tasks = await persistence.get_tasks_by_workflow(workflow.id)
    for task in tasks:
        logger.info(f"Task {task.id} status: {task.status}")
        if hasattr(task, 'result'):
            logger.info(f"  Result: {task.result}")
    
    # Check workflow status
    final_workflow = await persistence.get_workflow(workflow.id)
    logger.info(f"Final workflow status: {final_workflow.status}")
    
    logger.info("=== Shutting Down ===")
    await system_manager.shutdown()
    
    # Return success if task executed
    return any(task.status.value == 'completed' if hasattr(task.status, 'value') else task.status == 'completed' for task in tasks)


if __name__ == "__main__":
    success = asyncio.run(test_task_execution())
    if success:
        print("✅ TASKS EXECUTED SUCCESSFULLY")
    else:
        print("❌ TASKS DID NOT EXECUTE")