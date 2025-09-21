#!/usr/bin/env python3
"""
Test that tasks with invalid methods are rejected at validation time.
"""

import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_task_validation():
    """Test that invalid tasks are rejected early."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, TaskStatus
    from gleitzeit.client import GleitzeitClient
    
    logger.info("=== Testing Task Validation ===")
    
    # Get SystemManager
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    
    await asyncio.sleep(2)
    logger.info(f"SystemManager ready: {system_manager.instance_id}")
    
    # Initialize client
    client = GleitzeitClient(mode="native", system_manager=system_manager)
    await client.initialize()
    
    # Test 1: Invalid method (should be rejected)
    logger.info("\n--- Test 1: Invalid method 'execute' (should be 'python/execute') ---")
    
    invalid_task = Task(
        id=f"invalid_task_{datetime.now().strftime('%H%M%S')}",
        name="Invalid Method Task",
        workflow_id=f"test_wf_{datetime.now().strftime('%H%M%S')}",
        protocol="python/v1",
        method="execute",  # INVALID - should be "python/execute"
        params={"code": "print('test')"},
        status=TaskStatus.PENDING
    )
    
    result = await client.submit_task(invalid_task)
    
    if result.get("success"):
        logger.error("❌ FAILED: Invalid task was accepted!")
        logger.error(f"Result: {result}")
    else:
        logger.info("✅ PASSED: Invalid task was rejected!")
        logger.info(f"Error: {result.get('error')}")
        
        # Check that it mentions the method issue
        error_msg = str(result.get('error', ''))
        if 'method' in error_msg.lower() or 'execute' in error_msg:
            logger.info("✅ Error message correctly identifies the method issue")
        else:
            logger.warning("⚠️ Error message doesn't mention the method issue")
    
    # Test 2: Valid method (should be accepted)
    logger.info("\n--- Test 2: Valid method 'python/execute' ---")
    
    valid_task = Task(
        id=f"valid_task_{datetime.now().strftime('%H%M%S')}",
        name="Valid Method Task",
        workflow_id=f"test_wf2_{datetime.now().strftime('%H%M%S')}",
        protocol="python/v1",
        method="python/execute",  # VALID
        params={"code": "print('Valid task'); result = 'SUCCESS'"},
        status=TaskStatus.PENDING
    )
    
    result = await client.submit_task(valid_task)
    
    if result.get("success"):
        logger.info("✅ PASSED: Valid task was accepted!")
        logger.info(f"Task ID: {result.get('task_id')}")
        
        # Check if it actually executes
        task_id = result.get('task_id')
        await asyncio.sleep(3)
        
        task_obj = await system_manager.persistence.get_task(task_id)
        if task_obj:
            logger.info(f"Task status: {task_obj.status}")
            if task_obj.status == TaskStatus.COMPLETED:
                logger.info("✅ Task executed successfully!")
    else:
        logger.error("❌ FAILED: Valid task was rejected!")
        logger.error(f"Error: {result.get('error')}")
    
    # Test 3: Invalid protocol
    logger.info("\n--- Test 3: Invalid protocol ---")
    
    bad_protocol_task = Task(
        id=f"bad_proto_task_{datetime.now().strftime('%H%M%S')}",
        name="Bad Protocol Task",
        workflow_id=f"test_wf3_{datetime.now().strftime('%H%M%S')}",
        protocol="nonexistent/v1",  # INVALID protocol
        method="something",
        params={},
        status=TaskStatus.PENDING
    )
    
    result = await client.submit_task(bad_protocol_task)
    
    if result.get("success"):
        logger.error("❌ FAILED: Task with invalid protocol was accepted!")
    else:
        logger.info("✅ PASSED: Task with invalid protocol was rejected!")
        logger.info(f"Error: {result.get('error')}")
    
    await client.shutdown()
    logger.info("\n=== Validation Test Complete ===")

if __name__ == "__main__":
    asyncio.run(test_task_validation())