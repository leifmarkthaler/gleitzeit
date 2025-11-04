"""
Example of using the Gleitzeit Python client SDK
"""

import asyncio
from gleitzeit.client.client import GleitzeitClient


async def main():
    """Example workflow submission using client sessions"""

    # Create client
    client = GleitzeitClient(api_url="http://localhost:8000")

    async with client:
        # Create a client session
        session_id = await client.create_session("test_user")
        print(f"Created session: {session_id}")

        # Define a simple workflow
        workflow = {
            "name": "example_workflow",
            "tasks": [
                {
                    "id": "task1",
                    "type": "python",
                    "params": {
                        "code": """
result = 2 + 2
print(f"The answer is {result}")
"""
                    }
                },
                {
                    "id": "task2",
                    "type": "python",
                    "depends_on": ["task1"],
                    "params": {
                        "code": """
import datetime
result = {
    "timestamp": datetime.datetime.utcnow().isoformat(),
    "message": "Task 2 completed successfully"
}
"""
                    }
                }
            ]
        }

        # Submit workflow
        response = await client.submit_workflow(workflow)
        print(f"Submitted workflow: {response.workflow_id}")
        print(f"Status: {response.status}")

        # Check workflow status
        status = await client.get_workflow(response.workflow_id)
        print(f"Workflow state: {status['state']}")

        # Get tasks
        tasks = await client.get_workflow_tasks(response.workflow_id)
        print(f"Tasks: {tasks}")

        # Clean up session
        await client.destroy_session()
        print("Session destroyed")


def sync_example():
    """Example using synchronous methods"""

    client = GleitzeitClient(api_url="http://localhost:8000")

    # Create session synchronously
    session_id = client.create_session_sync("sync_user")
    print(f"Created session: {session_id}")

    # Submit workflow synchronously
    workflow = {
        "name": "sync_workflow",
        "tasks": [
            {
                "id": "simple_task",
                "type": "python",
                "params": {
                    "code": "result = 'Hello from sync workflow!'"
                }
            }
        ]
    }

    response = client.submit_workflow_sync(workflow)
    print(f"Workflow {response.workflow_id} submitted")

    # Wait for completion
    try:
        final_status = client.wait_for_completion(
            response.workflow_id,
            timeout=30
        )
        print(f"Workflow completed: {final_status}")
    except TimeoutError as e:
        print(f"Workflow timed out: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("Async example:")
    print("=" * 60)
    asyncio.run(main())

    print("\n" + "=" * 60)
    print("Sync example:")
    print("=" * 60)
    sync_example()