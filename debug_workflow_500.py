#!/usr/bin/env python3
"""Debug workflow submission 500 error."""

import asyncio
import yaml
import traceback
from gleitzeit.client import GleitzeitClient

async def main():
    # Simple workflow
    workflow_yaml = """
name: debug_test
version: "1.0"
description: Debug test

tasks:
  - id: task1
    name: Test Task
    protocol: python/v1
    method: python/execute
    params:
      code: |
        print("Testing")
        return {"result": "ok"}
"""
    
    workflow_def = yaml.safe_load(workflow_yaml)
    
    # Create client
    client = await GleitzeitClient.create(mode="api", base_url="http://localhost:8083", enable_events=False)
    
    try:
        print("Submitting workflow...")
        result = await client.submit_workflow(workflow_def)
        print(f"Success: {result}")
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())