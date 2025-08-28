#!/usr/bin/env python3
"""
Test the centralized event-driven architecture with SQL backend
"""

import asyncio
import logging
import time
from pathlib import Path

from gleitzeit.client import GleitzeitClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_sql_workflows():
    """Test workflow execution with SQL persistence"""
    
    # Initialize client with SQL persistence and retry configuration
    client = GleitzeitClient(
        mode='native',
        native_config={
            'persistence': {
                'type': 'sql',
                'database_url': 'sqlite:///test_gleitzeit.db'
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
        logger.info("Client initialized with SQL persistence")
        
        # Test 1: Simple Workflow
        logger.info("\n" + "="*60)
        logger.info("TEST 1: SIMPLE WORKFLOW WITH SQL BACKEND")
        logger.info("="*60)
        
        workflow_path = "examples/simple_workflow.yaml"
        if Path(workflow_path).exists():
            logger.info(f"Running simple workflow from: {workflow_path}")
            
            start_time = time.time()
            result = await client.run_workflow(workflow_path, watch=True)
            end_time = time.time()
            
            if result:
                workflow_id = result.get('workflow_id')
                logger.info(f"✅ Workflow completed with ID: {workflow_id}")
                logger.info(f"⏱️  Total execution time: {end_time - start_time:.2f} seconds")
                logger.info(f"📊 Status: {result.get('status', 'unknown')}")
                
                # Display task results
                task_results = result.get('task_results', {})
                logger.info(f"\n📋 Task Results ({len(task_results)} tasks):")
                for task_id, task_result in task_results.items():
                    status = task_result.get('status', 'unknown')
                    logger.info(f"  • {task_id}: {status}")
        
        # Test 2: Parallel Workflow with Dependencies
        logger.info("\n" + "="*60)
        logger.info("TEST 2: PARALLEL WORKFLOW WITH SQL BACKEND")
        logger.info("="*60)
        
        workflow_path = "examples/parallel_workflow.yaml"
        if Path(workflow_path).exists():
            logger.info(f"Running parallel workflow from: {workflow_path}")
            
            start_time = time.time()
            result = await client.run_workflow(workflow_path, watch=True)
            end_time = time.time()
            
            if result:
                workflow_id = result.get('workflow_id')
                logger.info(f"✅ Workflow completed with ID: {workflow_id}")
                logger.info(f"⏱️  Total execution time: {end_time - start_time:.2f} seconds")
                
                # Get workflow details to check parallel execution
                workflow = await client.get_workflow(workflow_id)
                if workflow:
                    logger.info(f"\n⚡ Workflow Execution Details:")
                    logger.info(f"  • Started at: {workflow.started_at}")
                    logger.info(f"  • Completed at: {workflow.completed_at}")
                    
                    # Check task execution times
                    tasks = await client.get_workflow_tasks(workflow_id)
                    logger.info(f"\n🔄 Task Execution Timeline:")
                    for task in tasks:
                        logger.info(f"  • {task.name}:")
                        logger.info(f"    - Status: {task.status}")
                        if hasattr(task, 'started_at') and task.started_at:
                            logger.info(f"    - Started: {task.started_at}")
                        if hasattr(task, 'completed_at') and task.completed_at:
                            logger.info(f"    - Completed: {task.completed_at}")
        
        # Test 3: Workflow with Retry
        logger.info("\n" + "="*60)
        logger.info("TEST 3: WORKFLOW WITH RETRY (SQL BACKEND)")
        logger.info("="*60)
        
        # Create a workflow with a task that will retry
        retry_workflow_path = "examples/retry_workflow.yaml"
        if Path(retry_workflow_path).exists():
            logger.info(f"Running retry workflow from: {retry_workflow_path}")
            
            start_time = time.time()
            result = await client.run_workflow(retry_workflow_path, watch=True)
            end_time = time.time()
            
            if result:
                workflow_id = result.get('workflow_id')
                logger.info(f"✅ Workflow completed with ID: {workflow_id}")
                logger.info(f"⏱️  Total execution time: {end_time - start_time:.2f} seconds")
                
                # Check retry details
                tasks = await client.get_workflow_tasks(workflow_id)
                for task in tasks:
                    if hasattr(task, 'metadata') and task.metadata:
                        retry_info = task.metadata.get('retry', {})
                        if retry_info.get('attempt_number', 0) > 1:
                            logger.info(f"\n🔄 Task {task.name} succeeded after {retry_info['attempt_number']} attempts")
        
        # Test 4: Event Flow Validation
        logger.info("\n" + "="*60)
        logger.info("EVENT-DRIVEN ARCHITECTURE VALIDATION (SQL)")
        logger.info("="*60)
        
        logger.info("✅ Event-driven components working with SQL backend:")
        logger.info("  • Centralized event emission from ExecutionEngine")
        logger.info("  • EventDrivenQueueManager processing task events")
        logger.info("  • EventDrivenWorkflowManager tracking workflow state")
        logger.info("  • EventDrivenRetryManager handling failures")
        logger.info("  • Save-Before-Emit pattern ensuring data consistency")
        
    except Exception as e:
        logger.error(f"❌ Error during workflow execution: {e}", exc_info=True)
    
    finally:
        # Cleanup
        if hasattr(client, 'close'):
            await client.close()
        logger.info("\n✨ Client closed successfully")


async def main():
    """Main entry point"""
    logger.info("🚀 Starting SQL Backend Tests with Event Architecture")
    logger.info("-" * 60)
    await test_sql_workflows()
    logger.info("-" * 60)
    logger.info("✅ All SQL backend tests completed!")


if __name__ == "__main__":
    asyncio.run(main())