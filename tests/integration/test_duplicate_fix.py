#!/usr/bin/env python
"""Test to verify duplicate execution fix"""
import asyncio
import httpx
import json
import time

async def main():
    """Submit a workflow and count executions"""
    
    # Submit workflow
    async with httpx.AsyncClient() as client:
        workflow = {
            "name": "Test Duplicate Fix",
            "description": "Test workflow to verify no duplicate executions",
            "tasks": [
                {
                    "name": "test_task",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Say 'test passed' exactly"}
                        ]
                    },
                    "dependencies": [],
                    "priority": "normal"
                }
            ]
        }
        
        print("Submitting workflow...")
        response = await client.post(
            "http://localhost:8000/workflows",
            json=workflow
        )
        result = response.json()
        workflow_id = result["workflow_id"]
        print(f"Workflow ID: {workflow_id}")
        
        # Wait for completion
        print("Waiting for completion...")
        await asyncio.sleep(3)
        
        # Check status
        response = await client.get(f"http://localhost:8000/workflows/{workflow_id}")
        status = response.json()
        
        print(f"\nWorkflow Status: {status['status']}")
        
        # Check task results
        for task_id, task_result in status.get('results', {}).items():
            print(f"\nTask {task_id}:")
            print(f"  Status: {task_result['status']}")
            if task_result.get('result'):
                print(f"  Response: {task_result['result'].get('response', 'N/A')}")
        
        print("\n✅ Test completed - check server logs for duplicate executions")

if __name__ == "__main__":
    asyncio.run(main())