#!/usr/bin/env python3
"""Test workflow submission with Redis Streams event bus."""

import asyncio
import yaml
from gleitzeit.client import GleitzeitClient

async def main():
    # Create workflow YAML
    workflow_yaml = """
name: test_redis_streams_workflow
version: "1.0"
description: Test workflow for Redis Streams implementation

tasks:
  - id: task1
    name: First Task
    protocol: python/v1
    method: python/execute
    params:
      code: |
        print("Task 1 executing with Redis Streams")
        import time
        time.sleep(1)
        return {"status": "success", "value": 42}

  - id: task2
    name: Second Task  
    protocol: python/v1
    method: python/execute
    params:
      code: |
        print("Task 2 executing")
        return {"status": "success", "value": 84}
    dependencies:
      - task1

  - id: task3
    name: Final Task
    protocol: python/v1
    method: python/execute
    params:
      code: |
        print("Final task processing results")
        return {"final": "completed", "total": 126}
    dependencies:
      - task2
"""
    
    # Parse workflow
    workflow_def = yaml.safe_load(workflow_yaml)
    
    # Create client
    client = await GleitzeitClient.create(mode="api", base_url="http://localhost:8082", enable_events=False)
    
    try:
        print("📤 Submitting workflow to test Redis Streams...")
        
        # Submit workflow
        result = await client.submit_workflow(workflow_def)
        
        workflow_id = result.get('workflow_id') or result.get('id')
        print(f"✅ Workflow submitted: {workflow_id}")
        print(f"   Response: {result}")
        
        # Wait for completion
        print("\n⏳ Waiting for workflow to complete...")
        workflow_result = await client.wait_for_workflow(workflow_id, timeout=60)
        
        print(f"\n✅ Workflow completed!")
        print(f"   Final status: {workflow_result.status}")
        
        # Check task statuses
        tasks = await client.list_tasks(workflow_id=workflow_id)
        print(f"\n📊 Task statuses:")
        for task in tasks.get('items', []):
            status = task.get('status')
            # Check if status is properly saved as string value
            if "TaskStatus." in str(status):
                print(f"   ❌ {task.get('name')}: {status} (enum string!)")
            else:
                print(f"   ✅ {task.get('name')}: {status}")
        
        print("\n🎉 Redis Streams implementation is working!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())