#!/usr/bin/env python
"""
Test complete event flow with all handlers registered
"""
import asyncio
import sys
from gleitzeit.client.client import GleitzeitClient

async def test_event_flow():
    """Test complete event flow after fixing handler registrations"""

    # Connect with native mode
    client = await GleitzeitClient.connect(
        mode='native',
        log_level='INFO'
    )

    print("✅ Connected to Gleitzeit")

    # Submit a simple workflow
    workflow_def = {
        "name": "Test Event Flow",
        "tasks": [
            {
                "name": "Task 1",
                "type": "python",
                "method": "python/execute",
                "params": {
                    "code": "result = 2 + 2"
                }
            }
        ]
    }

    print("📋 Submitting workflow...")
    workflow_id = await client.submit_workflow(workflow_def)
    print(f"✅ Workflow submitted: {workflow_id}")

    # Wait briefly for execution
    await asyncio.sleep(2)

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
        print(f"⚠️ Workflow not completed yet: {status}")
        return False

if __name__ == "__main__":
    try:
        success = asyncio.run(test_event_flow())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)