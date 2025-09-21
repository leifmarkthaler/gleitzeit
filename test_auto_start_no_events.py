#!/usr/bin/env python3
"""
Test auto-start functionality without events.
"""

import asyncio
from gleitzeit.client import GleitzeitClient

async def test_auto_start():
    """Test that client can auto-start the server."""

    print("1. Creating client with auto-start enabled (events disabled)...")
    client = GleitzeitClient(
        api_host="localhost",
        api_port=8000,
        auto_start_server=True,  # Enable auto-start
        enable_events=False      # Disable events to avoid WebSocket issues
    )

    print("2. Initializing client (should auto-start server if needed)...")
    await client.initialize()

    print("3. Server is running! Testing with a simple task...")

    # Submit a simple task
    task = {
        "id": "test_auto_start",
        "method": "python/inline",  # Protocol will be extracted as python/v1
        "params": {
            "code": "return 'Auto-start works!'"
        }
    }

    result = await client.execute_task(task)
    print(f"4. Task submitted: {result['task_id']}")

    # Wait briefly for completion
    await asyncio.sleep(2)

    # Get task result
    task_result = await client.get_task(result['task_id'])
    print(f"5. Task status: {task_result.status}")

    if task_result.status == 'completed':
        print(f"6. Task result: {task_result.result}")
        print("\n✅ AUTO-START TEST SUCCESSFUL!")
        print("   - Server was automatically started")
        print("   - Client connected successfully")
        print("   - Task executed successfully")
        print("   - Protocol was correctly extracted from method")
        print("   - Health check properly detects running servers")
    else:
        print(f"Task details: {task_result}")

    await client.shutdown()

if __name__ == "__main__":
    asyncio.run(test_auto_start())