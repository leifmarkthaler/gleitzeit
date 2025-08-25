#!/usr/bin/env python3
"""
Test the event-driven architecture with Redis adapter
"""

import asyncio
import logging
import yaml
from pathlib import Path

from gleitzeit.client import GleitzeitClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_redis_workflow():
    """Test workflow execution with Redis persistence"""
    
    # Initialize client with Redis persistence and retry configuration
    client = GleitzeitClient(
        mode='native',
        native_config={
            'persistence': {
                'type': 'redis',
                'redis_url': 'redis://localhost:6379/0'
            },
            'max_concurrent_tasks': 5,
            'enable_resource_management': True,
            'retry': {
                'enabled': True,
                'max_attempts': 3,
                'backoff_strategy': 'exponential',
                'base_delay': 2.0,
                'max_delay': 30.0,
                'jitter': True
            }
        }
    )
    
    try:
        # Initialize the client
        await client.initialize()
        logger.info("Client initialized with Redis persistence")
        
        # Run workflow from YAML file
        workflow_path = "examples/simple_python_workflow.yaml"
        
        logger.info(f"Running workflow from: {workflow_path}")
        
        # Submit and run the workflow
        logger.info("Submitting workflow...")
        result = await client.run_workflow(workflow_path, watch=True)
        
        if result:
            workflow_id = result.get('workflow_id')
            logger.info(f"Workflow submitted with ID: {workflow_id}")
        else:
            logger.error("Failed to submit workflow")
            return
        
        # The result from run_workflow with watch=True should include the final status
        if result:
            logger.info(f"Workflow completed!")
            logger.info(f"Status: {result.get('status', 'unknown')}")
            logger.info(f"Results: {result}")
            
            # Get detailed workflow info
            workflow = await client.get_workflow(workflow_id)
            if workflow:
                logger.info(f"Workflow details: status={workflow.status}, started_at={workflow.started_at}, completed_at={workflow.completed_at}")
        
        # Test retry functionality with a failing workflow
        logger.info("\n--- Testing Retry Functionality ---")
        
        # Run the retry test workflow
        retry_workflow_path = "examples/test_retry.yaml"
        if Path(retry_workflow_path).exists():
            logger.info(f"Running retry test workflow from: {retry_workflow_path}")
            
            # Submit the retry workflow
            retry_result = await client.run_workflow(retry_workflow_path, watch=True)
            
            if retry_result:
                retry_workflow_id = retry_result.get('workflow_id')
                logger.info(f"Retry workflow completed with ID: {retry_workflow_id}")
                logger.info(f"Retry workflow status: {retry_result.get('status', 'unknown')}")
                logger.info(f"Retry workflow results: {retry_result}")
                
                # Get detailed task info to see retry attempts
                tasks = await client.get_workflow_tasks(retry_workflow_id)
                for task in tasks:
                    logger.info(f"  Task {task.name}: status={task.status}")
                    if hasattr(task, 'metadata') and task.metadata:
                        if 'retry_count' in task.metadata:
                            logger.info(f"    Retry count: {task.metadata['retry_count']}")
                        if 'last_error' in task.metadata:
                            logger.info(f"    Last error: {task.metadata['last_error']}")
            else:
                logger.warning("Failed to run retry workflow")
        
    except Exception as e:
        logger.error(f"Error during workflow execution: {e}", exc_info=True)
    
    finally:
        # Cleanup
        if hasattr(client, 'close'):
            await client.close()
        logger.info("Client closed")


async def main():
    """Main entry point"""
    logger.info("Starting Redis event architecture test...")
    await test_redis_workflow()
    logger.info("Test completed!")


if __name__ == "__main__":
    asyncio.run(main())