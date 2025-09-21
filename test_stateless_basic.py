#!/usr/bin/env python3
"""
Test basic workflow execution in the stateless system.
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.client import GleitzeitClient
from gleitzeit.core.workflow import Workflow
from gleitzeit.core.task import Task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def simple_task(x: int) -> int:
    """Simple task that doubles a number."""
    return x * 2


async def main():
    """Test basic workflow execution."""
    client = GleitzeitClient(mode="native")

    try:
        logger.info("Starting stateless system test...")

        # Create a simple workflow
        workflow = Workflow(
            workflow_id="test_stateless_workflow",
            name="Test Stateless Workflow"
        )

        # Add a simple task
        task = Task(
            task_id="double_number",
            name="Double Number",
            function=simple_task,
            params={"x": 5}
        )
        workflow.add_task(task)

        # Submit workflow
        logger.info("Submitting workflow...")
        result = await client.submit_workflow(workflow)
        logger.info(f"Workflow submitted: {result}")

        # Wait for completion
        logger.info("Waiting for workflow to complete...")
        await asyncio.sleep(2)

        # Check status
        status = await client.get_workflow_status(workflow.workflow_id)
        logger.info(f"Workflow status: {status}")

        # Get results
        if status.get("status") == "completed":
            results = await client.get_workflow_results(workflow.workflow_id)
            logger.info(f"Workflow results: {results}")

            if results and "double_number" in results:
                result_value = results["double_number"]
                expected = 10
                if result_value == expected:
                    logger.info(f"✅ Test passed! Got expected result: {result_value}")
                else:
                    logger.error(f"❌ Test failed! Expected {expected}, got {result_value}")
            else:
                logger.error("❌ Test failed! No results found")
        else:
            logger.error(f"❌ Workflow did not complete. Status: {status}")

    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())