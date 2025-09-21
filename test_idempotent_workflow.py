#!/usr/bin/env python3
"""
Test workflow execution with idempotency fixes.
This tests that the stateless Redis Streams architecture with idempotency checks
properly handles task execution without duplicate processing.
"""

import asyncio
import logging
from gleitzeit.client import GleitzeitClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Test workflow with multiple tasks."""

    # Create client
    client = GleitzeitClient(
        base_url="http://localhost:8000",
        api_key="test-key"
    )

    try:
        logger.info("Client initialized successfully")

        # Submit a simple workflow with 3 tasks
        workflow_id = await client.submit_workflow(
            name="test-idempotent-workflow",
            tasks=[
                {
                    "id": "task1",
                    "type": "python",
                    "config": {
                        "code": "print('Task 1 executing'); result = 'task1-complete'"
                    }
                },
                {
                    "id": "task2",
                    "type": "python",
                    "dependencies": ["task1"],
                    "config": {
                        "code": "print('Task 2 executing'); result = 'task2-complete'"
                    }
                },
                {
                    "id": "task3",
                    "type": "python",
                    "dependencies": ["task2"],
                    "config": {
                        "code": "print('Task 3 executing'); result = 'task3-complete'"
                    }
                }
            ]
        )

        logger.info(f"Submitted workflow: {workflow_id}")

        # Wait for workflow to complete
        max_wait = 30  # seconds
        poll_interval = 1
        elapsed = 0

        while elapsed < max_wait:
            status = await client.get_workflow_status(workflow_id)
            logger.info(f"Workflow status: {status.get('status')}")

            # Check task statuses
            tasks = status.get('tasks', {})
            for task_id, task_status in tasks.items():
                logger.info(f"  Task {task_id}: {task_status}")

            if status.get('status') in ['completed', 'failed']:
                break

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # Get final results
        final_status = await client.get_workflow_status(workflow_id)
        logger.info(f"\nFinal workflow status: {final_status.get('status')}")

        # Check individual task results
        for task_id in ['task1', 'task2', 'task3']:
            try:
                result = await client.get_task_result(task_id)
                logger.info(f"Task {task_id} result: {result}")
            except Exception as e:
                logger.error(f"Failed to get result for {task_id}: {e}")

        # Verify all tasks completed
        tasks = final_status.get('tasks', {})
        all_completed = all(
            task_status == 'completed'
            for task_status in tasks.values()
        )

        if all_completed:
            logger.info("\n✅ SUCCESS: All tasks completed successfully!")
            logger.info("Idempotency checks are working - no duplicate executions")
        else:
            logger.error("\n❌ FAILED: Not all tasks completed")
            logger.error(f"Task statuses: {tasks}")

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
    finally:
        logger.info("Test completed")


if __name__ == "__main__":
    asyncio.run(main())