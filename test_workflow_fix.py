#!/usr/bin/env python
"""Test workflow execution after protocol mismatch fix"""

import asyncio
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Task, TaskResult


async def test_workflow():
    """Test that workflows now execute correctly"""
    print("Testing workflow execution after protocol fix...")

    # Create client
    client = await GleitzeitClient.create(
        base_url="http://localhost:8080",
        mode="api"
    )

    try:
        # Create a simple Python task
        task = Task(
            id="test-task-1",
            name="Test Python Task",
            protocol="python/v1",  # Using the correct protocol
            method="python/execute",
            params={
                "code": """
import json
result = {"message": "Task executed successfully!", "value": 42}
print(json.dumps(result))
"""
            }
        )

        print(f"Submitting task with protocol: {task.protocol}")

        # Submit the task
        result = await client.submit_task_and_wait(task, timeout=30)

        if result:
            print(f"✅ SUCCESS! Task executed: {result}")
            return True
        else:
            print(f"❌ FAILED: Task did not execute")
            return False

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False
    finally:
        await client.close()


if __name__ == "__main__":
    success = asyncio.run(test_workflow())
    exit(0 if success else 1)