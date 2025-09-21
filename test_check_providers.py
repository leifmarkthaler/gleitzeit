#!/usr/bin/env python3
"""
Check provider initialization and availability.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_providers():
    """Check if providers are properly set up."""
    
    from gleitzeit.system.system_manager import SystemManager
    
    logger.info("=== Checking Provider Setup ===")
    
    # Get SystemManager
    system_manager = await SystemManager.get_or_create(
        create_if_missing=True,
        start_system=True
    )
    
    await asyncio.sleep(2)
    
    # Check registry
    logger.info("\n--- Registry Status ---")
    if system_manager.registry:
        logger.info("✓ Registry exists")
        
        # Check for python provider
        try:
            python_provider = await system_manager.registry.get_provider("python/v1")
            if python_provider:
                logger.info("✓ Python provider registered")
                logger.info(f"  Provider: {python_provider}")
            else:
                logger.error("✗ Python provider not found")
        except Exception as e:
            logger.error(f"✗ Error getting python provider: {e}")
    else:
        logger.error("✗ No registry!")
    
    # Check pooling adapter
    logger.info("\n--- Pooling Adapter ---")
    if hasattr(system_manager, 'pooling_adapter'):
        adapter = system_manager.pooling_adapter
        if adapter:
            logger.info("✓ Pooling adapter exists")
            
            # Check registered protocols
            if hasattr(adapter, '_registered_protocols'):
                protocols = adapter._registered_protocols
                logger.info(f"  Registered protocols: {list(protocols)}")
            
            # Try to get a provider
            try:
                provider = await adapter.get_provider("python/v1")
                if provider:
                    logger.info("✓ Can get python provider from pooling adapter")
                    logger.info(f"  Provider ID: {provider.provider_id if hasattr(provider, 'provider_id') else 'N/A'}")
                else:
                    logger.error("✗ Could not get python provider")
            except Exception as e:
                logger.error(f"✗ Error getting provider: {e}")
    else:
        logger.error("✗ No pooling adapter!")
    
    # Check task executor
    logger.info("\n--- Task Executor ---")
    if system_manager.execution_engine:
        if hasattr(system_manager.execution_engine, 'task_executor'):
            executor = system_manager.execution_engine.task_executor
            logger.info("✓ Task executor exists")
            
            # Check if it has registry
            if hasattr(executor, 'registry'):
                logger.info(f"  Has registry: {executor.registry is not None}")
            else:
                logger.error("  No registry attribute!")
        else:
            logger.error("✗ No task executor!")
    
    # Now test actual execution
    logger.info("\n--- Testing Python Execution ---")
    
    from gleitzeit.core.models import Task, TaskStatus
    
    test_task = Task(
        id="provider_test_task",
        name="Provider Test",
        workflow_id="test_wf",
        protocol="python/v1",
        method="execute",
        params={"code": "result = 2 + 2; print(f'Result: {result}')"},
        status=TaskStatus.PENDING
    )
    
    # Try to execute directly with task executor
    if system_manager.execution_engine and hasattr(system_manager.execution_engine, 'task_executor'):
        executor = system_manager.execution_engine.task_executor
        
        try:
            logger.info("Attempting direct execution...")
            result = await executor.execute_task(test_task)
            logger.info(f"✓ Execution successful!")
            logger.info(f"  Output: {result.output if hasattr(result, 'output') else result}")
        except Exception as e:
            logger.error(f"✗ Execution failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    logger.info("\n=== Check Complete ===")

if __name__ == "__main__":
    asyncio.run(check_providers())