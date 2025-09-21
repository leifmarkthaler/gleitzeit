#!/usr/bin/env python3
"""
Fix to ensure consumer groups process existing messages on startup.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_with_pending_processing():
    """Test with processing of pending messages."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
    import redis.asyncio as redis
    
    logger.info("=== Testing with Pending Message Processing ===")
    
    # First, clean up and add a test task
    r = redis.from_url("redis://localhost:6379/0")
    
    # Create test data
    workflow_id = "test_wf_pending"
    task_id = "test_task_pending"
    
    # Save task to Redis
    task_data = {
        "id": task_id,
        "name": "Pending Test Task",
        "workflow_id": workflow_id,
        "protocol": "python/v1",
        "method": "execute",
        "params": '{"code": "print(\'Hello\')"}',
        "status": "pending",
        "dependencies": "[]"
    }
    
    workflow_data = {
        "id": workflow_id,
        "name": "Pending Test Workflow",
        "status": "pending",
        "tasks": f'["{task_id}"]'
    }
    
    await r.hset(f"workflow:{workflow_id}", mapping=workflow_data)
    await r.hset(f"task:{task_id}", mapping=task_data)
    logger.info(f"Created test task {task_id}")
    
    # Add TASK_SUBMITTED event to stream
    event_data = {
        "event_type": "task:submitted",
        "data": f'{{"task_id": "{task_id}", "workflow_id": "{workflow_id}"}}',
        "source": "test_setup",
        "timestamp": "2025-09-10T00:00:00"
    }
    
    stream_key = "gleitzeit:events:stream:task:submitted"
    msg_id = await r.xadd(stream_key, event_data)
    logger.info(f"Added TASK_SUBMITTED event to stream: {msg_id}")
    
    # Now start the system - it should process the existing message
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    
    logger.info("System started - should process pending messages")
    
    # The key fix: Force processing of pending messages on startup
    # This would need to be added to the StreamEventBus initialization
    
    # For now, manually trigger pending message processing
    consumer_group = "gleitzeit-workers"
    
    # Read pending messages (messages that were added but not ACKed)
    pending = await r.xpending_range(stream_key, consumer_group, "-", "+", count=10)
    
    if pending:
        logger.info(f"Found {len(pending)} pending messages")
        for entry in pending:
            logger.info(f"  Pending: {entry['message_id']} (consumer: {entry['consumer']})")
    
    # Read undelivered messages (from last confirmed ID)
    info = await r.xinfo_groups(stream_key)
    for group in info:
        if group['name'] == consumer_group:
            last_delivered = group['last-delivered-id']
            logger.info(f"Consumer group last delivered: {last_delivered}")
            
            # Read messages after last delivered
            unread = await r.xrange(stream_key, last_delivered, "+", count=10)
            if unread:
                logger.info(f"Found {len(unread)} unread messages after {last_delivered}")
    
    # Wait for processing
    await asyncio.sleep(3)
    
    # Check task status
    task = await system_manager.persistence.get_task(task_id)
    if task:
        logger.info(f"Task status: {task.status}")
        if task.status == TaskStatus.QUEUED:
            logger.info("✓ Task was processed and queued!")
        elif task.status == TaskStatus.PENDING:
            logger.warning("✗ Task is still pending - not processed")
    
    await r.close()
    logger.info("=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(test_with_pending_processing())