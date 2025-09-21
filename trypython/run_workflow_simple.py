#!/usr/bin/env python3
"""
Simplified workflow runner using direct API calls.
"""

import asyncio
import yaml
import json
from pathlib import Path
import httpx


async def submit_workflow(workflow_file: str):
    """Submit a workflow via direct API call."""
    
    # Load workflow
    file_path = Path(workflow_file)
    with open(file_path, 'r') as f:
        if file_path.suffix in ['.yaml', '.yml']:
            workflow_dict = yaml.safe_load(f)
        else:
            workflow_dict = json.load(f)
    
    # Submit via API
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/workflows/",
            json={"workflow": workflow_dict}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✓ Workflow submitted successfully!")
            print(f"  Workflow ID: {result.get('workflow_id')}")
            return result.get('workflow_id')
        else:
            print(f"✗ Failed to submit workflow")
            print(f"  Status: {response.status_code}")
            print(f"  Error: {response.text}")
            return None


async def get_workflow_status(workflow_id: str):
    """Get workflow status."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://localhost:8000/workflows/{workflow_id}")
        if response.status_code == 200:
            return response.json()
        return None


async def main():
    """Main entry point."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python run_workflow_simple.py <workflow_file>")
        sys.exit(1)
    
    workflow_file = sys.argv[1]
    
    # Submit workflow
    workflow_id = await submit_workflow(workflow_file)
    
    if workflow_id:
        print("\nMonitoring workflow...")
        
        # Poll for status
        while True:
            await asyncio.sleep(2)
            status = await get_workflow_status(workflow_id)
            if status:
                workflow_status = status.get('status')
                print(f"  Status: {workflow_status}")
                
                if workflow_status in ['completed', 'failed']:
                    if workflow_status == 'completed':
                        print("\n✓ Workflow completed successfully!")
                    else:
                        print(f"\n✗ Workflow failed: {status.get('error')}")
                    break


if __name__ == "__main__":
    asyncio.run(main())