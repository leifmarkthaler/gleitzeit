#!/usr/bin/env python3
"""
Debug test to see QueueManager processing of TASK_SUBMITTED events.
"""

import asyncio
import logging
from datetime import datetime

# Configure DETAILED logging
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG level to see everything
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Also enable DEBUG for gleitzeit components
logging.getLogger('gleitzeit.task_queue').setLevel(logging.DEBUG)
logging.getLogger('gleitzeit.events').setLevel(logging.DEBUG)

async def test_queue_manager_debug():
    """Test with detailed logging to debug QueueManager."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
    
    logger.info("=== DEBUG: QueueManager Event Processing ===")
    
    # Get or create SystemManager
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    logger.info(f"SystemManager initialized: {system_manager.instance_id}")
    
    # Create workflow and task
    workflow_id = f"debug_workflow_{datetime.now().strftime('%H%M%S')}"
    task_id = f"debug_task_{datetime.now().strftime('%H%M%S')}"
    
    test_task = Task(
        id=task_id,
        name="Debug Task",
        workflow_id=workflow_id,
        protocol="python/v1",
        method="execute",
        params={"code": "print('Debug')"},
        status=TaskStatus.PENDING,
        dependencies=[]  # No dependencies - should be ready immediately
    )
    
    workflow = Workflow(
        id=workflow_id,
        name="Debug Workflow",
        tasks=[test_task],
        status=WorkflowStatus.PENDING
    )
    
    # Save workflow and task
    await system_manager.persistence.save_workflow(workflow)
    await system_manager.persistence.save_task(test_task)
    logger.info(f"Saved workflow {workflow_id} and task {task_id}")
    
    # Emit TASK_SUBMITTED event directly
    from gleitzeit.core.events import EventType, GleitzeitEvent
    
    event = GleitzeitEvent(
        event_type=EventType.TASK_SUBMITTED,
        data={
            "task_id": task_id,
            "task_name": test_task.name,
            "workflow_id": workflow_id
        },
        source="debug_test"
    )
    
    logger.info(f"Emitting TASK_SUBMITTED event for {task_id}")
    await system_manager.event_bus.emit(event)
    
    # Wait for processing
    logger.info("Waiting for QueueManager to process event...")
    await asyncio.sleep(3)
    
    # Check task status
    task = await system_manager.persistence.get_task(task_id)
    logger.info(f"Task status after processing: {task.status if task else 'NOT FOUND'}")
    
    # Check for TASK_READY event
    redis = system_manager.persistence.redis
    messages = await redis.xrevrange("gleitzeit:events:stream:task:ready", count=5)
    
    found_ready = False
    for msg_id, data in messages:
        decoded = {k.decode() if isinstance(k, bytes) else k: 
                  v.decode() if isinstance(v, bytes) else v 
                  for k, v in data.items()}
        if 'data' in decoded:
            import json
            event_data = json.loads(decoded['data'])
            if event_data.get('task_id') == task_id:
                logger.info(f"✓ Found TASK_READY event for {task_id}")
                found_ready = True
                break
    
    if not found_ready:
        logger.warning(f"✗ No TASK_READY event found for {task_id}")
    
    logger.info("=== Debug Complete ===")

if __name__ == "__main__":
    asyncio.run(test_queue_manager_debug())