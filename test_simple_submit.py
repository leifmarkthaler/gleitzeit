#!/usr/bin/env python
"""Simple test to debug client initialization"""

import asyncio
import traceback
from gleitzeit.client import GleitzeitClient

async def test_simple():
    """Test simple workflow submission"""
    try:
        print("Creating client...")
        client = await GleitzeitClient.create(mode="api", api_url="http://localhost:8000")
        print(f"Client created: {client}")
        print(f"Client adapter: {client._adapter}")
        
        # Try to submit a simple workflow
        print("\nSubmitting workflow...")
        result = await client.submit_workflow({
            "name": "Test workflow",
            "tasks": [{
                "name": "test_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Hello')"
                }
            }]
        })
        print(f"Result: {result}")
        
    except Exception as e:
        print(f"Error: {e}")
        print(f"Error type: {type(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_simple())