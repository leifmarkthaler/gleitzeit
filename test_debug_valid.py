#!/usr/bin/env python
"""Debug valid workflow submission error"""

import asyncio
import traceback
from gleitzeit.client import GleitzeitClient

async def test_valid():
    """Test valid workflow submission"""
    try:
        client = await GleitzeitClient.create(mode="api", api_url="http://localhost:8000")
        
        # Test valid workflow
        print("Submitting valid workflow...")
        result = await client.submit_workflow({
            "name": "Valid Python workflow",
            "tasks": [{
                "name": "python_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Hello from valid task')"
                }
            }]
        })
        print(f"✓ Valid workflow submitted: {result}")
        
    except Exception as e:
        print(f"Error: {e}")
        print(f"Error type: {type(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_valid())