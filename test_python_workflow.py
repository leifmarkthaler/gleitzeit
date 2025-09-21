#!/usr/bin/env python
"""
Test Python workflow execution with ModularStreamSystemManager.
"""

import asyncio
import logging
import os
from gleitzeit.system.modular_stream_system_manager import ModularStreamSystemManager
from gleitzeit.system.models import SystemConfig, DeploymentMode
from gleitzeit.core.models import Workflow, Task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_python_workflow():
    """Test executing a Python workflow through ModularStreamSystemManager."""

    # Create config
    config = SystemConfig(
        deployment_mode=DeploymentMode.DEVELOPMENT,
        environment="test",
        default_providers=["python"],
        provider_hub_port=9092
    )

    manager = None
    try:
        logger.info("=" * 60)
        logger.info("Creating ModularStreamSystemManager...")
        logger.info("=" * 60)

        # Create manager
        manager = await ModularStreamSystemManager.create(
            config=config,
            instance_id="test_python_exec",
            create_if_missing=True,
            start_system=True
        )

        if not manager:
            logger.error("Failed to create manager")
            return False

        logger.info(f"Manager created: {manager.instance_id}")

        # Create a simple workflow with a Python task
        task_file_path = os.path.abspath("test_task.py")
        logger.info(f"Using Python file: {task_file_path}")

        # Create workflow with proper Python task
        workflow = Workflow(
            id="test-python-workflow-001",
            name="Test Python Workflow",
            tasks=[
                Task(
                    id="python-task-1",
                    name="Execute Python Task",
                    protocol="python/v1",
                    operation="python/execute",
                    parameters={
                        "file": task_file_path,
                        "function": "main"
                    }
                )
            ]
        )

        logger.info("=" * 60)
        logger.info("Submitting workflow...")
        logger.info("=" * 60)

        # Submit workflow
        workflow_id = await manager.submit_workflow(workflow)
        logger.info(f"Workflow submitted: {workflow_id}")

        # Wait a bit for execution
        logger.info("Waiting for workflow execution...")
        await asyncio.sleep(5)

        # Check workflow status
        logger.info("=" * 60)
        logger.info("Checking workflow status...")
        logger.info("=" * 60)

        if manager.persistence:
            # Get workflow status
            workflow_data = await manager.persistence.get_workflow(workflow_id)
            if workflow_data:
                status = workflow_data.status if hasattr(workflow_data, 'status') else 'unknown'
                logger.info(f"Workflow status: {status}")

                # Check task results
                task_id = "python-task-1"
                task_result = await manager.persistence.get_task_result(task_id)
                if task_result:
                    logger.info(f"Task result: {task_result}")

                    # Check if task actually executed
                    if hasattr(task_result, 'status'):
                        logger.info(f"Task status: {task_result.status}")
                    if hasattr(task_result, 'result'):
                        logger.info(f"Task output: {task_result.result}")
                else:
                    logger.warning("No task result found yet")

                # Get all tasks for workflow
                tasks = await manager.persistence.get_tasks_by_workflow(workflow_id)
                if tasks:
                    logger.info(f"Found {len(tasks)} tasks in workflow")
                    for task in tasks:
                        task_status = task.status if hasattr(task, 'status') else 'unknown'
                        logger.info(f"  Task {task.id}: {task_status}")
            else:
                logger.warning("Could not retrieve workflow data")

        # Check if execution engine processed anything
        if manager.execution_engine:
            logger.info("Execution engine is active")

        # Check provider statistics
        if hasattr(manager, 'get_provider_statistics'):
            stats = manager.get_provider_statistics()
            logger.info(f"Provider stats: {stats}")

        return True

    except Exception as e:
        logger.error(f"Error during workflow execution: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

    finally:
        if manager:
            logger.info("Shutting down manager...")
            await manager.shutdown()


async def main():
    """Main test runner."""
    logger.info("Testing Python workflow execution with ModularStreamSystemManager")
    logger.info("=" * 60)

    success = await test_python_workflow()

    if success:
        print("\n" + "=" * 60)
        print("✅ Python workflow test completed")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ Python workflow test failed")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())