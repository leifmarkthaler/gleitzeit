#!/usr/bin/env python
"""
Test workflow execution with fixed event system
"""
import asyncio
import time
from gleitzeit.client.client import GleitzeitClient

async def test_workflow():
    """Test complete event flow after fixing handler registrations"""

    # Connect with API mode to running server
    client = GleitzeitClient(
        mode='api',
        api_url='http://localhost:8020'
    )

    # Initialize the client
    await client.initialize()

    print("✅ Connected to Gleitzeit")

    # Submit a simple workflow
    workflow_def = {
        "name": "Test Event Flow",
        "tasks": [
            {
                "id": "task1",
                "name": "Add Numbers",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = 20 + 22\nprint(f'🎉 WORKFLOW EXECUTION WORKING! Result: {result}')"
                }
            }
        ]
    }

    print("📋 Submitting workflow...")
    workflow_id = await client.submit_workflow(workflow_def)
    print(f"✅ Workflow submitted: {workflow_id}")

    # Wait briefly for execution
    await asyncio.sleep(3)

    # Check status
    status = await client.get_workflow_status(workflow_id)
    print(f"📊 Workflow status: {status.get('status')}")

    # Check for task completion
    if status.get('status') == 'completed':
        print("✅ Event flow working correctly!")
        result = await client.get_workflow_result(workflow_id)
        print(f"📦 Result: {result}")
        return True
    else:
        print(f"⚠️ Workflow status: {status}")
        # Check task details
        tasks = status.get('tasks', [])
        for task in tasks:
            print(f"  Task {task.get('id', 'unknown')}: {task.get('status', 'unknown')}")
        return False

if __name__ == "__main__":
    try:
        success = asyncio.run(test_workflow())
        exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)