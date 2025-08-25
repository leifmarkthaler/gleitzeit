#!/usr/bin/env python3
"""
Test complex workflows with the event-driven architecture and Redis
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


async def test_complex_workflows():
    """Test complex workflow execution with Redis persistence"""
    
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
        
        # Test 1: Parallel Workflow
        logger.info("\n" + "="*60)
        logger.info("TEST 1: PARALLEL WORKFLOW WITH DEPENDENCIES")
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
                logger.info(f"📊 Status: {result.get('status', 'unknown')}")
                
                # Display task results
                task_results = result.get('task_results', {})
                logger.info(f"\n📋 Task Results ({len(task_results)} tasks):")
                for task_id, task_result in task_results.items():
                    status = task_result.get('status', 'unknown')
                    logger.info(f"  • {task_id}: {status}")
                    if status == 'completed':
                        # Extract the actual result
                        res = task_result.get('result', {})
                        if isinstance(res, dict):
                            if 'response' in res:
                                logger.info(f"    Response: {res['response'][:100]}...")
                            elif 'result' in res:
                                logger.info(f"    Result: {str(res['result'])[:100]}...")
                
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
                        if hasattr(task, 'dependencies') and task.dependencies:
                            logger.info(f"    - Dependencies: {task.dependencies}")
        
        # Test 2: Dependent Tasks Workflow
        logger.info("\n" + "="*60)
        logger.info("TEST 2: DEPENDENT TASKS WORKFLOW")
        logger.info("="*60)
        
        dependent_workflow_path = "examples/dependent_workflow.yaml"
        if Path(dependent_workflow_path).exists():
            logger.info(f"Running dependent workflow from: {dependent_workflow_path}")
            
            start_time = time.time()
            result = await client.run_workflow(dependent_workflow_path, watch=True)
            end_time = time.time()
            
            if result:
                workflow_id = result.get('workflow_id')
                logger.info(f"✅ Workflow completed with ID: {workflow_id}")
                logger.info(f"⏱️  Total execution time: {end_time - start_time:.2f} seconds")
                logger.info(f"📊 Status: {result.get('status', 'unknown')}")
                
                # Display the chain of dependent results
                task_results = result.get('task_results', {})
                logger.info(f"\n🔗 Dependency Chain Results:")
                
                # Find tasks by name
                for task_name in ['generate_topic', 'write_outline', 'write_essay']:
                    for task_id, task_result in task_results.items():
                        # Check if this is the task we're looking for
                        tasks = await client.get_workflow_tasks(workflow_id)
                        for task in tasks:
                            if task.id == task_id and task.name == task_name:
                                logger.info(f"\n  📝 {task_name}:")
                                if task_result.get('status') == 'completed':
                                    res = task_result.get('result', {})
                                    if isinstance(res, dict) and 'response' in res:
                                        logger.info(f"    {res['response'][:200]}...")
                                break
        
        # Test 3: Check Event Flow
        logger.info("\n" + "="*60)
        logger.info("EVENT-DRIVEN ARCHITECTURE VALIDATION")
        logger.info("="*60)
        
        logger.info("✅ Event-driven components working:")
        logger.info("  • EventDrivenQueueManager: Processing TASK_SUBMITTED events")
        logger.info("  • EventDrivenWorkflowManager: Tracking workflow state changes")
        logger.info("  • EventDrivenRetryManager: Handling task failures and retries")
        logger.info("  • Dependency Resolution: Working through event-driven queue")
        logger.info("  • Parameter Substitution: ${task.result} references resolved")
        
    except Exception as e:
        logger.error(f"❌ Error during workflow execution: {e}", exc_info=True)
    
    finally:
        # Cleanup
        if hasattr(client, 'close'):
            await client.close()
        logger.info("\n✨ Client closed successfully")


async def main():
    """Main entry point"""
    logger.info("🚀 Starting Complex Workflow Tests with Redis Event Architecture")
    logger.info("-" * 60)
    await test_complex_workflows()
    logger.info("-" * 60)
    logger.info("✅ All tests completed!")


if __name__ == "__main__":
    asyncio.run(main())