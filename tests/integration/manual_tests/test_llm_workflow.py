#!/usr/bin/env python3
"""Submit and test LLM workflow."""

import asyncio
import yaml
from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.workflow_loader import load_workflow_from_dict

async def test_llm_workflow():
    """Submit and test an LLM workflow."""
    
    print("Creating API client...")
    client = GleitzeitClient(
        mode=ClientMode.API,
        api_host="localhost",
        api_port=8001,
        auto_start_server=False
    )
    
    await client.initialize()
    print("Client initialized")
    
    # Load workflow
    print("\nLoading workflow from YAML...")
    with open("testworkflows/test_simple_llm.yaml", "r") as f:
        workflow_data = yaml.safe_load(f)
    print(f"Loaded workflow: {workflow_data['name']}")
    
    # Submit workflow
    print("\nSubmitting workflow...")
    try:
        # Load the workflow using the loader to get proper Task objects with UUIDs
        workflow = load_workflow_from_dict(workflow_data)
        workflow_id = await client.submit_workflow(workflow)
        print(f"✅ Workflow submitted successfully!")
        print(f"   Workflow ID: {workflow_id}")
    except Exception as e:
        print(f"❌ Failed to submit workflow: {e}")
        await client.shutdown()
        return
    
    # Wait a bit for execution
    print("\nWaiting for workflow to execute...")
    await asyncio.sleep(5)
    
    # List workflows to check status
    print("\nListing workflows to verify status...")
    workflows = await client.list_workflows(limit=10)
    print(f"Found {len(workflows)} workflow(s) in system")
    
    await client.shutdown()
    print("\nTest complete!")

if __name__ == "__main__":
    asyncio.run(test_llm_workflow())