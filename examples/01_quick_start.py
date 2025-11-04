#!/usr/bin/env python3
"""
Quick Start Example - Simple Workflow Submission

This example demonstrates the basic workflow submission and monitoring.
"""

import asyncio
from gleitzeit.client import GleitzeitClient


async def main():
    """Quick start example"""

    # Create client with auto-login
    async with GleitzeitClient('http://localhost:8000') as client:
        print("✓ Connected to Gleitzeit API")

        # Define a simple workflow
        workflow = {
            'name': 'Hello World',
            'tasks': [{
                'id': 'greeting',
                'type': 'python',
                'params': {
                    'code': '''
result = {
    "message": "Hello, World!",
    "status": "success"
}
print(f"Generated greeting: {result['message']}")
'''
                }
            }]
        }

        # Submit workflow
        response = await client.submit_workflow(workflow)
        print(f"✓ Submitted workflow: {response.workflow_id}")

        # Wait for completion
        status = await client.wait_for_workflow(response.workflow_id, timeout=60)
        print(f"✓ Workflow completed with status: {status.status}")

        # Get task result
        tasks = await client.get_workflow_tasks(response.workflow_id)
        if tasks:
            task = tasks[0]
            task_id = task.get('task_id') if isinstance(task, dict) else task.task_id
            result = await client.get_task_result(task_id, response.workflow_id)
            print(f"✓ Result: {result}")


if __name__ == "__main__":
    print("=" * 60)
    print("Quick Start Example")
    print("=" * 60)
    asyncio.run(main())
