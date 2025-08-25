#!/usr/bin/env python
"""Test script for the new centralized event architecture with SQL backend"""

import asyncio
import logging
from gleitzeit.client import GleitzeitClient, ClientMode

logging.basicConfig(level=logging.INFO)

async def main():
    # Use API mode to test the running server
    client = GleitzeitClient(
        mode=ClientMode.API,
        api_host="localhost",
        api_port=8049
    )
    
    await client.initialize()
    
    # Test with dependent workflow to verify event-driven queue handles dependencies
    workflows = [
        "examples/dependent_workflow.yaml"
    ]
    
    for workflow_path in workflows:
        print(f"\n{'='*50}")
        print(f"Running workflow: {workflow_path}")
        
        try:
            result = await client.run_workflow(workflow_path, watch=True)
            
            print(f"Workflow completed!")
            print(f"Workflow ID: {result.get('workflow_id')}")
            print(f"Status: {result.get('status')}")
            
            # Show task results summary
            results = result.get('results', {})
            for task_id, task_result in results.items():
                status = task_result.get('status', 'unknown')
                print(f"  Task {task_id}: {status}")
                
        except Exception as e:
            print(f"Error running workflow: {e}")
    
    await client.shutdown()

if __name__ == "__main__":
    asyncio.run(main())