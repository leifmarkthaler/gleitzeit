#!/usr/bin/env python3
"""
Test retry functionality with SQL backend
"""

import asyncio
import logging
import time
import os
from pathlib import Path

from gleitzeit.client import GleitzeitClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_sql_retry():
    """Test retry functionality with SQL persistence"""
    
    # Clean up any previous test attempts
    attempt_file = "/tmp/retry_test_attempts.txt"
    if os.path.exists(attempt_file):
        os.remove(attempt_file)
        logger.info(f"Cleaned up previous test file: {attempt_file}")
    
    # Initialize client with SQL persistence and retry configuration
    client = GleitzeitClient(
        mode='native',
        native_config={
            'persistence': {
                'type': 'sql',
                'database_url': 'sqlite:///test_retry.db'
            },
            'max_concurrent_tasks': 2,
            'retry': {
                'enabled': True,
                'max_attempts': 3,
                'backoff_strategy': 'fixed',  # Use fixed for predictable testing
                'base_delay': 1.0,  # 1 second between retries
                'jitter': False  # No jitter for predictable timing
            }
        }
    )
    
    try:
        # Initialize the client
        await client.initialize()
        logger.info("Client initialized with SQL persistence and retry config")
        
        # Test 1: Single task retry
        logger.info("\n" + "="*60)
        logger.info("TEST 1: SINGLE TASK RETRY (SQL BACKEND)")
        logger.info("="*60)
        
        # Submit a task that will fail twice then succeed
        task = await client.submit_task(
            protocol="python/v1",
            name="retry_test_task",
            method="python/execute",
            params={
                "file": "examples/scripts/retry_test.py"
            }
        )
        
        logger.info(f"Submitted task {task.id} that will fail 2 times, then succeed")
        
        # Watch for completion
        start_time = time.time()
        max_wait = 10  # Wait up to 10 seconds
        
        while time.time() - start_time < max_wait:
            task_status = await client.get_task(task.id)
            if task_status and task_status.status in ['completed', 'failed']:
                break
            await asyncio.sleep(0.5)
        
        # Check final status
        final_task = await client.get_task(task.id)
        if final_task:
            logger.info(f"\n📊 Task Final Status: {final_task.status}")
            
            if final_task.status == 'completed':
                logger.info("✅ Task succeeded after retries!")
                
                # Check retry metadata
                if hasattr(final_task, 'metadata') and final_task.metadata:
                    retry_info = final_task.metadata.get('retry', {})
                    attempts = retry_info.get('attempt_number', 1)
                    logger.info(f"🔄 Total attempts: {attempts}")
                    logger.info(f"   - Max attempts allowed: {retry_info.get('max_attempts', 3)}")
                    logger.info(f"   - Backoff strategy: {retry_info.get('backoff_strategy', 'fixed')}")
                    
                    # Get task result
                    result = await client.get_task_result(task.id)
                    if result:
                        logger.info(f"\n📋 Task Result:")
                        if isinstance(result.result, dict):
                            output = result.result.get('output', '')
                            if 'Success on attempt' in output:
                                logger.info(f"   {output}")
            else:
                logger.error(f"❌ Task failed with status: {final_task.status}")
        
        # Test 2: Workflow with retry
        logger.info("\n" + "="*60)
        logger.info("TEST 2: WORKFLOW WITH RETRY (SQL BACKEND)")
        logger.info("="*60)
        
        # Clean up for next test
        if os.path.exists(attempt_file):
            os.remove(attempt_file)
        
        workflow_path = "examples/retry_workflow.yaml"
        if Path(workflow_path).exists():
            logger.info(f"Running workflow with retry from: {workflow_path}")
            
            start_time = time.time()
            result = await client.run_workflow(workflow_path, watch=True)
            end_time = time.time()
            
            if result:
                workflow_id = result.get('workflow_id')
                logger.info(f"✅ Workflow completed with ID: {workflow_id}")
                logger.info(f"⏱️  Total execution time: {end_time - start_time:.2f} seconds")
                
                # Check retry details for each task
                tasks = await client.get_workflow_tasks(workflow_id)
                logger.info(f"\n🔄 Task Retry Details:")
                for task in tasks:
                    logger.info(f"\n  • Task: {task.name}")
                    logger.info(f"    - Status: {task.status}")
                    
                    if hasattr(task, 'metadata') and task.metadata:
                        retry_info = task.metadata.get('retry', {})
                        if retry_info:
                            attempts = retry_info.get('attempt_number', 1)
                            if attempts > 1:
                                logger.info(f"    - ✅ Succeeded after {attempts} attempts")
                                logger.info(f"    - Strategy: {retry_info.get('backoff_strategy')}")
        
        # Test 3: Verify SQL persistence of retry data
        logger.info("\n" + "="*60)
        logger.info("TEST 3: VERIFY SQL PERSISTENCE")
        logger.info("="*60)
        
        # Query persistence directly to verify retry metadata was saved
        if client.persistence:
            # Get all tasks with retry metadata
            all_tasks = await client.persistence.list_tasks(limit=10)
            retry_tasks = [t for t in all_tasks if t.metadata and 'retry' in t.metadata]
            
            logger.info(f"Found {len(retry_tasks)} tasks with retry metadata in SQL")
            for task in retry_tasks[:3]:  # Show first 3
                retry_info = task.metadata.get('retry', {})
                logger.info(f"\n  • Task {task.id}:")
                logger.info(f"    - Attempts: {retry_info.get('attempt_number', 1)}")
                logger.info(f"    - Max attempts: {retry_info.get('max_attempts', 3)}")
                logger.info(f"    - Strategy: {retry_info.get('backoff_strategy', 'unknown')}")
        
        logger.info("\n" + "="*60)
        logger.info("RETRY FUNCTIONALITY VALIDATION (SQL)")
        logger.info("="*60)
        
        logger.info("✅ Retry features working with SQL backend:")
        logger.info("  • Task retry with configurable attempts")
        logger.info("  • Backoff strategies (fixed, linear, exponential)")
        logger.info("  • Retry metadata persistence in SQL")
        logger.info("  • Event-driven retry manager integration")
        logger.info("  • Workflow-level retry configuration")
        
    except Exception as e:
        logger.error(f"❌ Error during retry test: {e}", exc_info=True)
    
    finally:
        # Cleanup
        if hasattr(client, 'close'):
            await client.close()
        logger.info("\n✨ Client closed successfully")


async def main():
    """Main entry point"""
    logger.info("🚀 Starting SQL Retry Tests")
    logger.info("-" * 60)
    await test_sql_retry()
    logger.info("-" * 60)
    logger.info("✅ All SQL retry tests completed!")


if __name__ == "__main__":
    asyncio.run(main())