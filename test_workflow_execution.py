#!/usr/bin/env python
"""
Test workflow execution with fixed event system
"""
import asyncio
from gleitzeit.client.client import GleitzeitClient

async def main():
    print("🚀 Testing workflow execution...")

    # Create native client
    client = GleitzeitClient(mode='native')

    # Simple workflow
    workflow = {
        "name": "Test Workflow",
        "tasks": [
            {
                "id": "task1",
                "name": "Add Numbers",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = 2 + 3\nprint(f'Result: {result}')"
                }
            }
        ]
    }

    print("📋 Submitting workflow...")
    workflow_id = await client.submit_workflow(workflow)
    print(f"✅ Workflow submitted: {workflow_id}")

    # Wait for execution
    await asyncio.sleep(3)

    # Check status
    status = await client.get_workflow_status(workflow_id)
    print(f"📊 Status: {status.get('status', 'unknown')}")

    if status.get('status') == 'completed':
        print("✅ Workflow executed successfully!")
        tasks = status.get('tasks', [])
        for task in tasks:
            print(f"  - Task {task['id']}: {task['status']}")
    else:
        print(f"⚠️ Workflow not completed: {status}")

if __name__ == "__main__":
    asyncio.run(main())