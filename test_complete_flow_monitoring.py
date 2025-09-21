#!/usr/bin/env python3
"""
Monitor complete task execution flow with detailed logging.
"""

import asyncio
import logging
from datetime import datetime

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Silence noisy loggers
logging.getLogger('gleitzeit.events.stream_event_bus').setLevel(logging.INFO)
logging.getLogger('gleitzeit.persistence').setLevel(logging.INFO)

async def monitor_complete_flow():
    """Monitor the complete task execution flow."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
    from gleitzeit.core.events import EventType, GleitzeitEvent
    
    logger.info("=== Monitoring Complete Task Execution Flow ===")
    
    # Get SystemManager
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    
    await asyncio.sleep(2)
    logger.info(f"SystemManager initialized: {system_manager.instance_id}")
    
    # Track events
    events_captured = []
    
    # Register event monitors
    async def capture_event(event_type):
        async def handler(event):
            events_captured.append((event_type, event.data))
            logger.info(f"📡 Event: {event_type} - {event.data}")
        return handler
    
    event_bus = system_manager.event_bus
    event_bus.register(EventType.TASK_SUBMITTED, await capture_event("TASK_SUBMITTED"))
    event_bus.register(EventType.TASK_READY, await capture_event("TASK_READY"))
    event_bus.register(EventType.TASK_STARTED, await capture_event("TASK_STARTED"))
    event_bus.register(EventType.TASK_COMPLETED, await capture_event("TASK_COMPLETED"))
    event_bus.register(EventType.TASK_FAILED, await capture_event("TASK_FAILED"))
    
    # Create test task
    workflow_id = f"monitor_wf_{datetime.now().strftime('%H%M%S')}"
    task_id = f"monitor_task_{datetime.now().strftime('%H%M%S')}"
    
    task = Task(
        id=task_id,
        name="Monitor Test Task",
        workflow_id=workflow_id,
        protocol="python/v1",
        method="execute",
        params={"code": "print('Hello from monitoring'); result = 'SUCCESS'"},
        status=TaskStatus.PENDING
    )
    
    workflow = Workflow(
        id=workflow_id,
        name="Monitor Test Workflow",
        tasks=[task],
        status=WorkflowStatus.PENDING
    )
    
    # Save workflow and task
    await system_manager.persistence.save_workflow(workflow)
    await system_manager.persistence.save_task(task)
    logger.info(f"Created workflow {workflow_id} with task {task_id}")
    
    # Submit task via NativeAdapter (to test our fix)
    from gleitzeit.client import GleitzeitClient
    
    client = GleitzeitClient(mode="native", system_manager=system_manager)
    await client.initialize()
    
    logger.info("\n--- Submitting Task ---")
    result = await client.submit_task(task)
    logger.info(f"Submit result: {result}")
    
    # Monitor task progression
    logger.info("\n--- Monitoring Task Progress ---")
    
    for i in range(15):  # Monitor for 15 seconds
        await asyncio.sleep(1)
        
        # Check task status
        task_obj = await system_manager.persistence.get_task(task_id)
        if task_obj:
            current_status = task_obj.status
            logger.info(f"[{i+1}s] Task status: {current_status}")
            
            # Check if status changed
            if current_status == TaskStatus.COMPLETED:
                logger.info("✅ Task completed successfully!")
                
                # Get result
                result = await system_manager.persistence.get_task_result(task_id)
                if result:
                    logger.info(f"  Output: {result.output}")
                    logger.info(f"  Result: {result.result}")
                break
                
            elif current_status == TaskStatus.FAILED:
                logger.error("❌ Task failed!")
                
                # Get error details
                result = await system_manager.persistence.get_task_result(task_id)
                if result:
                    logger.error(f"  Error: {result.error}")
                    
                    # Get detailed error from Redis
                    import redis.asyncio as aioredis
                    redis = aioredis.from_url("redis://localhost:6379/0")
                    result_key = f"task:result:{task_id}"
                    result_data = await redis.hgetall(result_key)
                    
                    logger.error("\n--- Error Details ---")
                    for k, v in result_data.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        val = v.decode() if isinstance(v, bytes) else v
                        if key in ['error', 'traceback']:
                            logger.error(f"{key}:\n{val}")
                    
                    await redis.aclose()
                break
                
            elif current_status == TaskStatus.EXECUTING:
                logger.info("  ⚙️ Task is executing...")
            elif current_status == TaskStatus.QUEUED:
                logger.info("  📋 Task is queued...")
            elif current_status == TaskStatus.PENDING:
                logger.info("  ⏳ Task is still pending...")
    
    # Summary
    logger.info("\n--- Event Summary ---")
    logger.info(f"Total events captured: {len(events_captured)}")
    for event_type, data in events_captured:
        logger.info(f"  - {event_type}: {data}")
    
    # Final check
    task_obj = await system_manager.persistence.get_task(task_id)
    workflow_obj = await system_manager.persistence.get_workflow(workflow_id)
    
    logger.info("\n--- Final Status ---")
    logger.info(f"Task: {task_obj.status if task_obj else 'NOT FOUND'}")
    logger.info(f"Workflow: {workflow_obj.status if workflow_obj else 'NOT FOUND'}")
    
    await client.shutdown()
    logger.info("\n=== Monitoring Complete ===")

if __name__ == "__main__":
    asyncio.run(monitor_complete_flow())