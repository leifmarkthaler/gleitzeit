#!/usr/bin/env python3
"""
Debug why tasks are failing during execution.
"""

import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enable debug for execution components
logging.getLogger('gleitzeit.core.task_orchestrator').setLevel(logging.DEBUG)
logging.getLogger('gleitzeit.core.task_executor').setLevel(logging.DEBUG)
logging.getLogger('gleitzeit.providers').setLevel(logging.DEBUG)

async def debug_task_execution():
    """Debug task execution issues."""
    
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
    
    logger.info("=== Debugging Task Execution ===")
    
    # Get SystemManager
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    
    await asyncio.sleep(2)
    logger.info(f"SystemManager ready: {system_manager.instance_id}")
    
    # Check components
    logger.info("\n--- Component Status ---")
    
    # Check execution engine
    if system_manager.execution_engine:
        logger.info("✓ ExecutionEngine is available")
        logger.info(f"  Running: {system_manager.execution_engine._running}")
    else:
        logger.error("✗ No ExecutionEngine!")
    
    # Check task orchestrator
    if hasattr(system_manager.execution_engine, 'task_orchestrator'):
        orchestrator = system_manager.execution_engine.task_orchestrator
        logger.info(f"✓ TaskOrchestrator available")
        logger.info(f"  Running: {orchestrator._running if hasattr(orchestrator, '_running') else 'N/A'}")
    else:
        logger.error("✗ No TaskOrchestrator!")
    
    # Check providers
    if system_manager.registry:
        providers = system_manager.registry.get_all_providers()
        logger.info(f"✓ Registry has {len(providers)} provider(s):")
        for protocol, provider_info in providers.items():
            logger.info(f"  - {protocol}: {provider_info}")
    else:
        logger.error("✗ No Registry!")
    
    # Create a simple test task
    workflow_id = f"exec_test_wf_{datetime.now().strftime('%H%M%S')}"
    task_id = f"exec_test_task_{datetime.now().strftime('%H%M%S')}"
    
    task = Task(
        id=task_id,
        name="Execution Test Task",
        workflow_id=workflow_id,
        protocol="python/v1",
        method="execute",
        params={"code": "print('Test execution'); result = 42"},
        status=TaskStatus.PENDING
    )
    
    workflow = Workflow(
        id=workflow_id,
        name="Execution Test Workflow",
        tasks=[task],
        status=WorkflowStatus.PENDING
    )
    
    # Save workflow and task
    await system_manager.persistence.save_workflow(workflow)
    await system_manager.persistence.save_task(task)
    logger.info(f"\nCreated test task {task_id}")
    
    # Submit through execution engine
    await system_manager.execution_engine.submit_task(task)
    logger.info("Submitted task to execution engine")
    
    # Monitor task progress
    for i in range(10):
        await asyncio.sleep(1)
        
        task = await system_manager.persistence.get_task(task_id)
        if task:
            logger.info(f"[{i+1}s] Task status: {task.status}")
            
            if task.status == TaskStatus.COMPLETED:
                logger.info("✓✓ Task completed successfully!")
                result = await system_manager.persistence.get_task_result(task_id)
                if result:
                    logger.info(f"  Output: {result.output}")
                    logger.info(f"  Result: {result.result}")
                break
            elif task.status == TaskStatus.FAILED:
                logger.error("✗ Task failed!")
                result = await system_manager.persistence.get_task_result(task_id)
                if result:
                    logger.error(f"  Error: {result.error}")
                    if hasattr(result, 'traceback'):
                        logger.error(f"  Traceback: {result.traceback}")
                break
            elif task.status == TaskStatus.EXECUTING:
                logger.info("  Task is executing...")
    
    # Check for any error logs
    if task and task.status == TaskStatus.FAILED:
        logger.info("\n--- Checking Redis for error details ---")
        import redis.asyncio as aioredis
        redis = aioredis.from_url("redis://localhost:6379/0")
        
        # Check task result
        result_key = f"task:result:{task_id}"
        result_data = await redis.hgetall(result_key)
        if result_data:
            for k, v in result_data.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                logger.info(f"  {key}: {val[:500]}")
        
        await redis.aclose()
    
    logger.info("\n=== Debug Complete ===")

if __name__ == "__main__":
    asyncio.run(debug_task_execution())