#!/usr/bin/env python3
"""
Test that task submission through ExecutionEngine properly emits events and schedules tasks.
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

async def test_task_with_execution_engine():
    """Test task submission through execution engine (which handles workflow creation)."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, TaskStatus
    
    logger.info("=== Testing Fixed Task Submission ===")
    
    # Get or create SystemManager
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    logger.info(f"✓ SystemManager initialized: {system_manager.instance_id}")
    
    # Use the execution engine which properly handles workflow creation
    execution_engine = system_manager.execution_engine
    if not execution_engine:
        logger.error("✗ No execution engine available")
        return
    
    logger.info("✓ ExecutionEngine available")
    
    # Create a test task
    test_task = Task(
        id=f"test_task_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        name="Test Task for Fixed Event Emission",
        protocol="python/v1",
        method="execute",
        params={"code": "result = 2 + 2; print(f'Result: {result}')"}
    )
    
    logger.info(f"Submitting task through ExecutionEngine: {test_task.id}")
    
    # Submit through execution engine (it will create a workflow automatically)
    task_id = await execution_engine.submit_task(test_task)
    logger.info(f"✓ Task submitted with ID: {task_id}")
    
    # Wait a moment for event processing
    await asyncio.sleep(2)
    
    # Check task status
    task = await system_manager.persistence.get_task(task_id)
    if task:
        logger.info(f"✓ Task found in persistence with status: {task.status}")
        
        # Check if task is being processed
        if task.status in [TaskStatus.EXECUTING, TaskStatus.COMPLETED]:
            logger.info("✓✓ Task is being/has been executed! Event flow is working!")
        elif task.status == TaskStatus.QUEUED:
            logger.info("✓ Task is queued for execution")
        elif task.status == TaskStatus.PENDING:
            logger.warning("⚠️ Task is still pending - may need to check queue processing")
    else:
        logger.error("✗ Task not found in persistence")
    
    # Check if task has a workflow
    if task and task.workflow_id:
        workflow = await system_manager.persistence.get_workflow(task.workflow_id)
        if workflow:
            logger.info(f"✓ Task belongs to workflow: {workflow.id} (status: {workflow.status})")
    
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
                    logger.info(f"✓ Found TASK_SUBMITTED event in Redis stream!")
                    logger.info(f"  Event data: {json.dumps(task_data, indent=2)}")
                    found_event = True
                    break
        
        if not found_event:
            logger.warning("⚠️ TASK_SUBMITTED event not found in stream (may have been consumed)")
            
    except Exception as e:
        logger.error(f"Error checking Redis stream: {e}")
    
    # Wait a bit more for execution
    logger.info("Waiting for task execution...")
    await asyncio.sleep(3)
    
    # Final status check
    task = await system_manager.persistence.get_task(task_id)
    if task:
        logger.info(f"Final task status: {task.status}")
        
        if task.status == TaskStatus.COMPLETED:
            # Get result
            result = await system_manager.persistence.get_task_result(task_id)
            if result:
                logger.info(f"✓✓✓ Task completed successfully! Result: {result.output}")
            else:
                logger.info("✓✓ Task completed (no result stored)")
        elif task.status == TaskStatus.FAILED:
            result = await system_manager.persistence.get_task_result(task_id)
            if result and result.error:
                logger.error(f"Task failed with error: {result.error}")
    
    logger.info("=== Test Complete ===")

if __name__ == "__main__":
    try:
        asyncio.run(test_task_with_execution_engine())
    except KeyboardInterrupt:
        logger.info("Test interrupted")
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)