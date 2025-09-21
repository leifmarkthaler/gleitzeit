#!/usr/bin/env python3

import asyncio
import sys
import traceback
from gleitzeit.client import GleitzeitClient

async def test_signal_provider():
    """Test the signal provider directly to see the exact error"""
    try:
        # Create client
        print("Creating client...")
        client = GleitzeitClient(
            api_url="http://localhost:8000",
            auto_start=True
        )

        # Initialize the client
        print("Initializing client...")
        await client.initialize()

        # Test signal send directly via API
        print("Testing signal/send via API...")

        task_data = {
            "protocol": "signal/v1",
            "method": "signal/send",
            "params": {
                "signal": "test_debug_signal",
                "data": {"test": True}
            }
        }

        print(f"Submitting task: {task_data}")
        task = await client.execute_task(task_data)

        print(f"Task submitted: {task.id}")
        print(f"Task status: {task.status}")

        # Wait a bit for processing
        await asyncio.sleep(2)

        # Get updated task status
        updated_task = await client.get_task(task.id)
        print(f"Updated task status: {updated_task.status}")

        if updated_task.status == "failed":
            print(f"Task failed with error: {updated_task.error_message}")

        print("Test completed!")

    except Exception as e:
        print(f"Test failed with exception: {e}")
        print(f"Exception type: {type(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_signal_provider())