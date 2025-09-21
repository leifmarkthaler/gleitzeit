#!/usr/bin/env python3
"""
Test that task submission with workflow properly emits events and schedules tasks.
"""

import asyncio
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_workflow_task_submission():
    """Test task submission as part of a workflow."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
    
    logger.info("=== Testing Workflow-Based Task Submission ===")
    
    # Get or create SystemManager
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    logger.info(f"✓ SystemManager initialized: {system_manager.instance_id}")
    
    # Create a workflow with a task
    workflow_id = f"test_workflow_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    task_id = f"test_task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Create task with workflow_id
    test_task = Task(
        id=task_id,
        name="Test Task with Workflow",
        workflow_id=workflow_id,  # REQUIRED for save_task
        protocol="python/v1",
        method="execute",
        params={"code": "result = 2 + 2; print(f'Result: {result}')"},
        status=TaskStatus.PENDING
    )
    
    # Create workflow
    workflow = Workflow(
        id=workflow_id,
        name="Test Workflow for Event Flow",
        tasks=[test_task],
        status=WorkflowStatus.PENDING
    )
    
    logger.info(f"Created workflow {workflow_id} with task {task_id}")
    
    # Save workflow first
    await system_manager.persistence.save_workflow(workflow)
    logger.info("✓ Workflow saved to persistence")
    
    # Now submit the task through NativeAdapter to test our fix
    from gleitzeit.client import GleitzeitClient
    
    client = GleitzeitClient(mode="native", system_manager=system_manager)
    await client.initialize()
    
    logger.info(f"Submitting task {task_id} through NativeAdapter")
    result = await client.submit_task(test_task)
    
    if result.get("success"):
        logger.info(f"✓ Task submitted successfully: {result}")
    else:
        logger.error(f"✗ Task submission failed: {result}")
        return
    
    # Wait for event processing
    await asyncio.sleep(2)
    
    # Check Redis stream for TASK_SUBMITTED event
    redis = system_manager.persistence.redis
    stream_key = "gleitzeit:events:stream:task:submitted"
    
    try:
        messages = await redis.xrevrange(stream_key, count=10)
        found_event = False
        
        for msg_id, data in messages:
            # Decode the data
            decoded = {}
            for k, v in data.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                decoded[key] = val
            
            # Check if this is our task
            if 'data' in decoded:
                import json
                task_data = json.loads(decoded['data'])
                if task_data.get('task_id') == task_id:
                    logger.info(f"✓✓ Found TASK_SUBMITTED event in Redis stream!")
                    logger.info(f"  Event ID: {msg_id.decode() if isinstance(msg_id, bytes) else msg_id}")
                    logger.info(f"  Event data: {json.dumps(task_data, indent=2)}")
                    found_event = True
                    break
        
        if not found_event:
            logger.warning("⚠️ TASK_SUBMITTED event not found in last 10 messages")
            
    except Exception as e:
        logger.error(f"Error checking Redis stream: {e}")
    
    # Check if QueueManager received the event
    # The QueueManager should have processed the TASK_SUBMITTED event and enqueued the task
    await asyncio.sleep(2)
    
    # Check task status
    task = await system_manager.persistence.get_task(task_id)
    if task:
        logger.info(f"Task status after event processing: {task.status}")
        
        if task.status == TaskStatus.QUEUED:
            logger.info("✓✓✓ Task was queued! QueueManager received the event!")
        elif task.status in [TaskStatus.EXECUTING, TaskStatus.COMPLETED]:
            logger.info("✓✓✓✓ Task is being/has been executed! Full event flow working!")
        elif task.status == TaskStatus.PENDING:
            logger.warning("⚠️ Task still PENDING - event may not have been processed")
    
    # Wait for potential execution
    logger.info("Waiting for task execution...")
    await asyncio.sleep(5)
    
    # Final check
    task = await system_manager.persistence.get_task(task_id)
    workflow = await system_manager.persistence.get_workflow(workflow_id)
    
    logger.info(f"Final task status: {task.status if task else 'NOT FOUND'}")
    logger.info(f"Final workflow status: {workflow.status if workflow else 'NOT FOUND'}")
    
    if task and task.status == TaskStatus.COMPLETED:
        result = await system_manager.persistence.get_task_result(task_id)
        if result:
            logger.info(f"✓✓✓✓✓ SUCCESS! Task completed with output: {result.output}")
    
    # Cleanup
    await client.shutdown()
    
    logger.info("=== Test Complete ===")

if __name__ == "__main__":
    try:
        asyncio.run(test_workflow_task_submission())
    except KeyboardInterrupt:
        logger.info("Test interrupted")
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)