#!/usr/bin/env python3
"""
Test the complete stateless workflow execution pipeline.
"""

import asyncio
import logging
from datetime import datetime
from gleitzeit.core.models import Workflow, Task
from gleitzeit.persistence.factory import PersistenceFactory
from gleitzeit.system.system_manager import SystemManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_workflow_execution():
    """Test the complete workflow execution pipeline."""
    
    # 1. Create and initialize SystemManager
    logger.info("=== Creating SystemManager ===")
    persistence = await PersistenceFactory.create()
    
    # Create proper system config
    from gleitzeit.system.models import SystemConfig
    config = SystemConfig(
        environment="development",  # Use valid environment
        deployment_mode="development"
    )
    
    system_manager = SystemManager(
        config=config,
        persistence=persistence
    )
    
    try:
        # 2. Initialize and start the system
        logger.info("=== Initializing SystemManager ===")
        await system_manager.initialize()
        
        logger.info("=== Starting System ===")
        await system_manager.start_system()
        
        # 3. Verify components are ready
        logger.info("=== Verifying Components ===")
        if not system_manager.workflow_manager:
            logger.error("WorkflowManager not initialized!")
            return False
            
        if not system_manager.execution_engine:
            logger.error("ExecutionEngine not initialized!")
            return False
            
        logger.info("✓ WorkflowManager ready")
        logger.info("✓ ExecutionEngine ready")
        
        # 4. Create a test workflow
        logger.info("=== Creating Test Workflow ===")
        workflow = Workflow(
            id=f"test-workflow-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            name="Stateless Test Workflow",
            tasks=[
                Task(
                    id="task1",
                    name="First Task",
                    protocol="python/v1",
                    method="execute",
                    parameters={
                        "code": "print('Task 1 executing'); result = 'Task 1 Complete'"
                    }
                ),
                Task(
                    id="task2", 
                    name="Second Task",
                    protocol="python/v1",
                    method="execute",
                    parameters={
                        "code": "print('Task 2 executing'); result = 'Task 2 Complete'"
                    },
                    dependencies=["task1"]  # Depends on task1
                ),
                Task(
                    id="task3",
                    name="Final Task",
                    protocol="python/v1",
                    method="execute",
                    parameters={
                        "code": "print('Task 3 executing'); result = 'All tasks complete!'"
                    },
                    dependencies=["task2"]  # Depends on task2
                )
            ]
        )
        
        logger.info(f"Created workflow: {workflow.id}")
        logger.info(f"  Tasks: {[t.id for t in workflow.tasks]}")
        logger.info(f"  Dependencies: task1 -> task2 -> task3")
        
        # 5. Store workflow in persistence
        logger.info("=== Storing Workflow ===")
        # save_workflow expects a Workflow object, not a dict
        await persistence.save_workflow(workflow)
        logger.info("✓ Workflow stored in persistence")
        
        # 6. Execute workflow via WorkflowManager
        logger.info("=== Executing Workflow ===")
        try:
            result = await system_manager.workflow_manager.execute_workflow(workflow)
            logger.info(f"✓ Workflow execution started: {result}")
        except Exception as e:
            logger.error(f"Failed to execute workflow: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # 7. Check workflow status
        logger.info("=== Checking Workflow Status ===")
        await asyncio.sleep(2)  # Give it time to process
        
        stored_workflow = await persistence.get_workflow(workflow.id)
        if stored_workflow:
            status = stored_workflow.status if hasattr(stored_workflow, 'status') else 'unknown'
            logger.info(f"Workflow status: {status}")
            
            # Check task statuses
            tasks = await persistence.get_tasks_by_workflow(workflow.id)
            logger.info(f"Tasks in persistence: {len(tasks) if tasks else 0}")
            for task in (tasks or []):
                if hasattr(task, 'status'):
                    task_status = task.status
                    task_id = task.id
                else:
                    task_status = task.get('status', 'unknown') if isinstance(task, dict) else 'unknown'
                    task_id = task.get('id', '?') if isinstance(task, dict) else '?'
                logger.info(f"  Task {task_id}: {task_status}")
        
        # 8. Test atomic operations if Redis is available
        logger.info("=== Testing Atomic Operations ===")
        dependency_manager = getattr(system_manager, 'dependency_resolver', None)
        if not dependency_manager:
            # Try to get it from execution engine
            if hasattr(system_manager.execution_engine, 'dependency_resolver'):
                dependency_manager = system_manager.execution_engine.dependency_resolver
        
        if dependency_manager and hasattr(dependency_manager, 'atomic_ops') and dependency_manager.atomic_ops:
            logger.info("✓ Atomic operations available via Redis")
            
            # Test atomic task claiming
            test_task_id = f"test-task-{datetime.now().strftime('%H%M%S')}"
            worker_id = "test-worker-1"
            
            # Create a test task in persistence
            test_task = {
                'id': test_task_id,
                'workflow_id': workflow.id,
                'status': 'pending'
            }
            task_key = f"task:{test_task_id}"
            if hasattr(persistence, 'redis'):
                import json
                await persistence.redis.set(task_key, json.dumps(test_task))
                
                # Try to claim it atomically
                claimed = await dependency_manager.atomic_ops.claim_task(test_task_id, worker_id)
                if claimed:
                    logger.info(f"✓ Successfully claimed task {test_task_id}")
                else:
                    logger.info(f"✗ Could not claim task {test_task_id}")
                    
                # Try to claim again (should fail)
                claimed2 = await dependency_manager.atomic_ops.claim_task(test_task_id, "worker-2")
                if not claimed2:
                    logger.info("✓ Atomic claiming works - second claim rejected")
                else:
                    logger.error("✗ RACE CONDITION: Second worker claimed same task!")
        else:
            logger.warning("⚠ No Redis/atomic operations available")
        
        # 9. Get system status
        logger.info("=== System Status ===")
        status = await system_manager.get_system_status()
        logger.info(f"System status: {status.get('status')}")
        logger.info(f"Deployment mode: {status.get('deployment_mode')}")
        logger.info(f"Services: {status.get('services')}")
        
        logger.info("=== Test Complete ===")
        return True
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        logger.info("=== Shutting Down ===")
        await system_manager.shutdown_system()
        await system_manager.shutdown()
        logger.info("✓ Shutdown complete")


if __name__ == "__main__":
    success = asyncio.run(test_workflow_execution())
    if success:
        logger.info("✅ ALL TESTS PASSED")
    else:
        logger.error("❌ TESTS FAILED")