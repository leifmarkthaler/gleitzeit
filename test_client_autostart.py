#!/usr/bin/env python
"""Test client auto-start functionality"""
import asyncio
from gleitzeit import GleitzeitClient

async def main():
    """Test the client auto-start"""
    print("Creating GleitzeitClient in auto mode...")
    
    async with GleitzeitClient(mode="auto") as client:
        print(f"Client active mode: {client._active_mode}")
        
        # Run a simple workflow
        result = await client.run_workflow("test_ui_message.yaml", watch=False)
        print(f"Workflow submitted: {result.get('workflow_id')}")
        print(f"Status: {result.get('status')}")
        
        # Wait a bit for execution
        await asyncio.sleep(5)
        
        # Check workflow status
        workflow = await client.get_workflow(result.get('workflow_id'))
        if workflow:
            # Handle both dict and object response
            if isinstance(workflow, dict):
                print(f"Workflow status: {workflow.get('status')}")
            else:
                print(f"Workflow status: {workflow.status}")

if __name__ == "__main__":
    asyncio.run(main())