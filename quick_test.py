#!/usr/bin/env python3
"""Quick test to verify workflow processing is working"""

import asyncio
from gleitzeit.client.client import GleitzeitClient

async def test_workflow():
    """Test a single workflow submission and completion"""
    client = GleitzeitClient()

    print("🚀 Submitting test workflow...")
    workflow = {
        "name": "test_workflow",
        "tasks": [
            {
                "id": "test_task",
                "type": "python",
                "code": "result = 42"
            }
        ]
    }

    try:
        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id if hasattr(response, 'workflow_id') else response
        print(f"✅ Workflow submitted: {workflow_id}")

        # Wait for completion
        print("⏳ Waiting for completion...")
        for i in range(30):  # 30 second timeout
            await asyncio.sleep(1)
            status = await client.get_workflow_status(workflow_id)
            if status and status.status in ['completed', 'failed']:
                print(f"✅ Workflow {status.status} in {i+1} seconds!")
                if status.status == 'completed':
                    print("🎉 System is working correctly!")
                else:
                    print(f"❌ Workflow failed: {status}")
                return

        print("⚠️  Workflow did not complete within 30 seconds")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_workflow())
