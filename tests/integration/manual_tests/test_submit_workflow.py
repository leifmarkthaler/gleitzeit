#!/usr/bin/env python3
"""Submit and monitor a workflow to test persistence."""

import asyncio
import yaml
from gleitzeit.client import GleitzeitClient, ClientMode

async def test_workflow_persistence():
    """Submit a workflow and verify it persists."""
    
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
    with open("test_workflow.yaml", "r") as f:
        workflow_data = yaml.safe_load(f)
    print(f"Loaded workflow: {workflow_data['name']}")
    
    # Submit workflow
    print("\nSubmitting workflow...")
    try:
        # Load the workflow using the loader to get proper Task objects with UUIDs
        from gleitzeit.core.workflow_loader import load_workflow_from_dict
        workflow = load_workflow_from_dict(workflow_data)
        workflow_id = await client.submit_workflow(workflow)
        print(f"✅ Workflow submitted successfully!")
        print(f"   Workflow ID: {workflow_id}")
    except Exception as e:
        print(f"❌ Failed to submit workflow: {e}")
        await client.shutdown()
        return
    
    # List workflows to verify persistence
    print("\nListing workflows to verify persistence...")
    workflows = await client.list_workflows(limit=10)
    print(f"Found {len(workflows)} workflow(s) in system")
    
    # Find our workflow
    our_workflow = None
    for wf in workflows:
        if hasattr(wf, 'id') and wf.id == workflow_id:
            our_workflow = wf
            break
        elif hasattr(wf, 'workflow_id') and wf.workflow_id == workflow_id:
            our_workflow = wf
            break
    
    if our_workflow:
        print(f"\n✅ Workflow found in persistence!")
        print(f"   Status: {getattr(our_workflow, 'status', 'unknown')}")
    else:
        print(f"\n⚠️ Workflow {workflow_id} not found in list")
    
    # Get workflow status
    print("\nGetting workflow status...")
    try:
        status = await client.get_workflow_status(workflow_id)
        print(f"Workflow status: {status}")
    except Exception as e:
        print(f"Error getting status: {e}")
    
    # Wait a bit for execution
    print("\nWaiting for workflow to execute...")
    await asyncio.sleep(3)
    
    # Check status again
    print("\nChecking final status...")
    try:
        final_status = await client.get_workflow_status(workflow_id)
        print(f"Final status: {final_status}")
        
        # Get results if available
        if final_status.get('status') == 'completed':
            print("\n✅ Workflow completed successfully!")
            if 'results' in final_status:
                print("Results:", final_status['results'])
    except Exception as e:
        print(f"Error getting final status: {e}")
    
    # List workflows again to confirm persistence
    print("\nFinal check - listing workflows again...")
    final_workflows = await client.list_workflows(limit=10)
    print(f"Total workflows in system: {len(final_workflows)}")
    
    await client.shutdown()
    print("\nTest complete!")

if __name__ == "__main__":
    asyncio.run(test_workflow_persistence())