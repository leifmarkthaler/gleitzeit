#!/usr/bin/env python3
"""
Test task execution with correct method name.
"""

import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_working_execution():
    """Test task execution with correct method."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
    
    logger.info("=== Testing Working Task Execution ===")
    
    # Get SystemManager
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    
    await asyncio.sleep(2)
    logger.info(f"SystemManager ready: {system_manager.instance_id}")
    
    # Create test task with CORRECT method name
    workflow_id = f"working_wf_{datetime.now().strftime('%H%M%S')}"
    task_id = f"working_task_{datetime.now().strftime('%H%M%S')}"
    
    task = Task(
        id=task_id,
        name="Working Test Task",
        workflow_id=workflow_id,
        protocol="python/v1",
        method="python/execute",  # CORRECT method name for Python provider
        params={"code": "print('Task executed successfully!'); result = 42"},
        status=TaskStatus.PENDING
    )
    
    workflow = Workflow(
        id=workflow_id,
        name="Working Test Workflow",
        tasks=[task],
        status=WorkflowStatus.PENDING
    )
    
    # Save workflow and task
    await system_manager.persistence.save_workflow(workflow)
    await system_manager.persistence.save_task(task)
    logger.info(f"Created task {task_id} with correct method 'python/execute'")
    
    # Submit task
    from gleitzeit.client import GleitzeitClient
    
    client = GleitzeitClient(mode="native", system_manager=system_manager)
    await client.initialize()
    
    result = await client.submit_task(task)
    logger.info(f"Task submitted: {result}")
    
    # Monitor execution
    logger.info("\n--- Monitoring Execution ---")
    
    for i in range(10):
        await asyncio.sleep(1)
        
        task_obj = await system_manager.persistence.get_task(task_id)
        if task_obj:
            logger.info(f"[{i+1}s] Task status: {task_obj.status}")
            
            if task_obj.status == TaskStatus.COMPLETED:
                logger.info("✅✅✅ TASK COMPLETED SUCCESSFULLY! ✅✅✅")
                
                # Get result
                result = await system_manager.persistence.get_task_result(task_id)
                if result:
                    logger.info(f"Output: {result.output}")
                    logger.info(f"Result: {result.result}")
                break
                
            elif task_obj.status == TaskStatus.FAILED:
                logger.error("❌ Task failed")
                result = await system_manager.persistence.get_task_result(task_id)
                if result:
                    logger.error(f"Error: {result.error}")
                break
    
    # Final status
    task_obj = await system_manager.persistence.get_task(task_id)
    workflow_obj = await system_manager.persistence.get_workflow(workflow_id)
    
    logger.info("\n--- Final Status ---")
    logger.info(f"Task: {task_obj.status if task_obj else 'NOT FOUND'}")
    logger.info(f"Workflow: {workflow_obj.status if workflow_obj else 'NOT FOUND'}")
    
    if task_obj and task_obj.status == TaskStatus.COMPLETED:
        logger.info("\n🎉🎉🎉 SUCCESS! The complete event flow is working! 🎉🎉🎉")
        logger.info("Tasks are now:")
        logger.info("  1. Submitted via API/Client")
        logger.info("  2. Event emitted (TASK_SUBMITTED)")
        logger.info("  3. Queued by QueueManager")
        logger.info("  4. Scheduled by TaskOrchestrator")
        logger.info("  5. Executed by TaskExecutor with providers")
        logger.info("  6. Completed successfully!")
    
    await client.shutdown()
    logger.info("\n=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(test_working_execution())