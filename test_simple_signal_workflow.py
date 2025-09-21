#!/usr/bin/env python3
"""
Test simple signal workflow with auto-start.
This should automatically start the server if it's not running.
"""

import asyncio
from gleitzeit.client import GleitzeitClient

async def test_signal_workflow():
    """Test signal workflow with auto-start."""

    print("Creating client (should auto-start server if not running)...")

    # Create client - should auto-start server
    client = GleitzeitClient(
        api_host="localhost",
        api_port=8000,
        auto_start_server=True  # This is the default
    )

    print("Initializing client...")
    await client.initialize()

    print("Server is running! Testing signal workflow...")

    # Create a simple signal workflow
    workflow = {
        "name": "test_signal_auto_start",
        "tasks": [
            {
                "id": "signal_sender",
                "method": "signal/send",  # No protocol field - should extract to signal/v1
                "params": {
                    "signal": "test_auto_start",
                    "data": {"message": "Auto-start works!"}
                }
            }
        ]
    }

    # Submit the workflow
    print("Submitting signal workflow...")
    result = await client.submit_workflow(workflow)
    print(f"Workflow submitted: {result['workflow_id']}")

    # Wait a moment for completion
    await asyncio.sleep(2)

    # Check status using get_workflow
    workflow_data = await client.get_workflow(result['workflow_id'])
    # workflow_data is a Workflow object, not a dict
    status = workflow_data.status if hasattr(workflow_data, 'status') else 'unknown'
    print(f"Workflow status: {status}")

    if status == 'completed':
        print("✅ Signal workflow completed successfully!")
        print("✅ Auto-start worked - server was started automatically!")
    else:
        print(f"Workflow data: {workflow_data}")

    await client.shutdown()
    print("\nTest complete!")

if __name__ == "__main__":
    asyncio.run(test_signal_workflow())