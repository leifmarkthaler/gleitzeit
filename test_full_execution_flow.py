#!/usr/bin/env python3
"""
Test full task execution flow with detailed logging.
"""

import asyncio
import logging
from datetime import datetime

# Configure DETAILED logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Enable debug for key components
logging.getLogger('gleitzeit.task_queue').setLevel(logging.DEBUG)
logging.getLogger('gleitzeit.events').setLevel(logging.INFO)
logging.getLogger('gleitzeit.core.task_orchestrator').setLevel(logging.DEBUG)

async def test_full_flow():
    """Test complete task execution flow."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
    from gleitzeit.core.events import EventType, GleitzeitEvent
    
    logger.info("=== Testing Full Task Execution Flow ===")
    
    # Get or create SystemManager  
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    
    # Wait for system to stabilize
    await asyncio.sleep(2)
    logger.info(f"SystemManager ready: {system_manager.instance_id}")
    
    # Check if handlers are registered
    if hasattr(system_manager.event_bus, '_handlers'):
        handlers = system_manager.event_bus._handlers
        logger.info(f"Registered event handlers: {list(handlers.keys())}")
        logger.info(f"  task:submitted handlers: {len(handlers.get('task:submitted', []))}")
        logger.info(f"  task:ready handlers: {len(handlers.get('task:ready', []))}")
    
    # Create workflow and task
    workflow_id = f"flow_wf_{datetime.now().strftime('%H%M%S')}"
    task_id = f"flow_task_{datetime.now().strftime('%H%M%S')}"
    
    task = Task(
        id=task_id,
        name="Full Flow Test Task",
        workflow_id=workflow_id,
        protocol="python/v1",
        method="execute",
        params={"code": "result = 42; print(f'The answer is {result}')"},
        status=TaskStatus.PENDING,
        dependencies=[]
    )
    
    workflow = Workflow(
        id=workflow_id,
        name="Full Flow Test Workflow",
        tasks=[task],
        status=WorkflowStatus.PENDING
    )
    
    # Save workflow and task
    await system_manager.persistence.save_workflow(workflow)
    await system_manager.persistence.save_task(task)
    logger.info(f"Created workflow {workflow_id} with task {task_id}")
    
    # Method 1: Try direct event emission
    logger.info("\n--- Method 1: Direct Event Emission ---")
    event = GleitzeitEvent(
        event_type=EventType.TASK_SUBMITTED,
        data={
            "task_id": task_id,
            "task_name": task.name,
            "workflow_id": workflow_id
        },
        source="test"
    )
    
    await system_manager.event_bus.emit(event)
    logger.info(f"Emitted TASK_SUBMITTED event")
    
    # Wait and check
    await asyncio.sleep(3)
    
    task = await system_manager.persistence.get_task(task_id)
    logger.info(f"Task status after TASK_SUBMITTED: {task.status if task else 'NOT FOUND'}")
    
    # If task is QUEUED, manually emit TASK_READY
    if task and task.status == TaskStatus.QUEUED:
        logger.info("\n--- Manually emitting TASK_READY ---")
        ready_event = GleitzeitEvent(
            event_type=EventType.TASK_READY,
            data={
                'task_id': task_id,
                'workflow_id': workflow_id,
                'protocol': task.protocol,
                'method': task.method
            },
            source="test_manual"
        )
        await system_manager.event_bus.emit(ready_event)
        logger.info("Emitted TASK_READY event manually")
        
        await asyncio.sleep(3)
        task = await system_manager.persistence.get_task(task_id)
        logger.info(f"Task status after TASK_READY: {task.status if task else 'NOT FOUND'}")
    
    # Method 2: Try through execution engine
    logger.info("\n--- Method 2: Through Execution Engine ---")
    task2_id = f"engine_task_{datetime.now().strftime('%H%M%S')}"
    task2 = Task(
        id=task2_id,
        name="Engine Test Task",
        workflow_id=workflow_id,
        protocol="python/v1",
        method="execute",
        params={"code": "print('Via engine')"},
        status=TaskStatus.PENDING
    )
    
    if system_manager.execution_engine:
        await system_manager.execution_engine.submit_task(task2)
        logger.info(f"Submitted task {task2_id} via execution engine")
        
        await asyncio.sleep(3)
        task2_obj = await system_manager.persistence.get_task(task2_id)
        logger.info(f"Task2 status: {task2_obj.status if task2_obj else 'NOT FOUND'}")
    
    # Final check
    await asyncio.sleep(5)
    
    logger.info("\n--- Final Status ---")
    task = await system_manager.persistence.get_task(task_id)
    task2_obj = await system_manager.persistence.get_task(task2_id) if 'task2_id' in locals() else None
    
    logger.info(f"Task 1 ({task_id}): {task.status if task else 'NOT FOUND'}")
    if task2_obj:
        logger.info(f"Task 2 ({task2_id}): {task2_obj.status}")
    
    # Check for results
    if task and task.status == TaskStatus.COMPLETED:
        result = await system_manager.persistence.get_task_result(task_id)
        if result:
            logger.info(f"✓ Task 1 completed! Output: {result.output}")
    
    if task2_obj and task2_obj.status == TaskStatus.COMPLETED:
        result = await system_manager.persistence.get_task_result(task2_id)
        if result:
            logger.info(f"✓ Task 2 completed! Output: {result.output}")
    
    logger.info("=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(test_full_flow())