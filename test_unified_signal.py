#!/usr/bin/env python3
"""
Test signal workflow with the unified StreamSystemManager
"""

import asyncio
from gleitzeit.client import GleitzeitClient


async def test_signal_workflow():
    """Test signal workflow with unified architecture"""
    print("Testing signal workflow with unified StreamSystemManager...")

    # Connect to server
    client = GleitzeitClient(base_url="http://localhost:8000")

    # Submit a simple signal workflow
    workflow_data = {
        "name": "test_unified_signal",
        "tasks": [
            {
                "id": "wait_task",
                "name": "Wait for Signal",
                "protocol": "signal/v1",
                "method": "wait",
                "params": {
                    "signal_name": "test_signal",
                    "timeout": 30
                }
            }
        ]
    }

    print("Submitting signal workflow...")
    result = await client.submit_workflow(workflow_data)
    workflow_id = result.get("workflow_id")
    print(f"Workflow submitted: {workflow_id}")

    # Wait a moment for workflow to initialize
    await asyncio.sleep(1)

    # Send the signal
    print("Sending signal...")
    signal_result = await client.send_signal("test_signal", {"message": "Hello from unified architecture!"})
    print(f"Signal sent: {signal_result}")

    # Wait for workflow completion
    print("Waiting for workflow completion...")
    for i in range(30):  # 30 second timeout
        status = await client.get_workflow_status(workflow_id)
        print(f"Workflow status: {status}")

        if status.get("status") in ["completed", "failed"]:
            break

        await asyncio.sleep(1)

    # Get final results
    final_status = await client.get_workflow_status(workflow_id)
    print(f"Final workflow status: {final_status}")

    if final_status.get("status") == "completed":
        print("✅ Signal workflow completed successfully with unified StreamSystemManager!")
        return True
    else:
        print("❌ Signal workflow failed")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_signal_workflow())
    exit(0 if success else 1)