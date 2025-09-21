#!/usr/bin/env python3
"""
Simplified test to understand the correct workflow format.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gleitzeit.client import GleitzeitClient


async def main():
    # Create client
    client = await GleitzeitClient.create(mode="api")
    
    # Simple workflow dict
    workflow = {
        "name": "test_workflow",
        "description": "Simple test",
        "tasks": [
            {
                "name": "hello",
                "protocol": "shell/v1",
                "method": "execute",
                "params": {
                    "command": "echo 'Hello from Gleitzeit!'"
                }
            }
        ]
    }
    
    try:
        # Submit workflow directly
        print("Submitting workflow...")
        from gleitzeit.core.models import Workflow
        workflow_obj = Workflow(**workflow)
        result = await client.submit_workflow(workflow_obj)
        print(f"Result: {result}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if hasattr(client, 'disconnect'):
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())