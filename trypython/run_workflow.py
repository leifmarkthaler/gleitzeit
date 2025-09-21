#!/usr/bin/env python3
"""
Simple example of running a Gleitzeit workflow from Python.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import gleitzeit
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import WorkflowStatus


async def run_workflow(workflow_path: str):
    """Run a workflow and monitor its execution."""
    
    # Initialize client
    client = await GleitzeitClient.create(mode="api")
    
    try:
        # Submit the workflow
        print(f"Submitting workflow: {workflow_path}")
        result = await client.run_workflow(workflow_path, watch=False)
        workflow_id = result.get('workflow_id')
        print(f"Workflow submitted with ID: {workflow_id}")
        
        # Monitor workflow status
        print("\nMonitoring workflow execution...")
        while True:
            status = await client.get_workflow_status(workflow_id)
            print(f"Status: {status.status}")
            
            if status.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                break
                
            await asyncio.sleep(1)
        
        # Get final results
        if status.status == WorkflowStatus.COMPLETED:
            print("\n✓ Workflow completed successfully!")
            
            # Get results for each task
            workflow = await client.get_workflow(workflow_id)
            for task_name, task_id in workflow.task_ids.items():
                result = await client.get_task_result(task_id)
                print(f"\nTask '{task_name}' result:")
                print(f"  Output: {result.output}")
                if result.error:
                    print(f"  Error: {result.error}")
        else:
            print(f"\n✗ Workflow failed: {status.error}")
    finally:
        if hasattr(client, 'disconnect'):
            await client.disconnect()


async def run_workflow_with_streaming(workflow_path: str):
    """Run a workflow with real-time output streaming."""
    
    client = await GleitzeitClient.create(mode="api")
    
    try:
        print(f"Submitting workflow with streaming: {workflow_path}")
        
        # Submit workflow with streaming enabled
        result = await client.run_workflow(workflow_path, watch=False)
        workflow_id = result.get('workflow_id')
        print(f"Workflow ID: {workflow_id}")
        
        # Stream output in real-time
        async for event in client.stream_workflow_events(workflow_id):
            if event.event_type == "task_output":
                print(f"[{event.task_id[:8]}] {event.data.get('output', '')}", end="")
            elif event.event_type == "task_completed":
                print(f"\n✓ Task {event.task_id[:8]} completed")
            elif event.event_type == "workflow_completed":
                print("\n✓ Workflow completed!")
                break
            elif event.event_type == "workflow_failed":
                print(f"\n✗ Workflow failed: {event.data.get('error')}")
                break
    finally:
        if hasattr(client, 'disconnect'):
            await client.disconnect()


async def main():
    """Main entry point."""
    
    # Check if workflow file is provided
    if len(sys.argv) < 2:
        print("Usage: python run_workflow.py <workflow_file> [--stream]")
        print("\nExample:")
        print("  python run_workflow.py example_workflow.yaml")
        print("  python run_workflow.py example_workflow.yaml --stream")
        sys.exit(1)
    
    workflow_file = sys.argv[1]
    stream_mode = "--stream" in sys.argv
    
    # Check if file exists
    if not Path(workflow_file).exists():
        print(f"Error: Workflow file '{workflow_file}' not found")
        sys.exit(1)
    
    # Run workflow
    if stream_mode:
        await run_workflow_with_streaming(workflow_file)
    else:
        await run_workflow(workflow_file)


if __name__ == "__main__":
    asyncio.run(main())