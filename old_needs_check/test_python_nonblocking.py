#!/usr/bin/env python3
"""Test non-blocking workflow with simple Python tasks."""

import asyncio
import yaml
from gleitzeit.client import GleitzeitClient

async def main():
    with open("test_python_workflow.yaml", "r") as f:
        workflow = yaml.safe_load(f)

    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        print("=== Non-Blocking Python Workflow Test ===\n")

        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id
        print(f"✓ Workflow submitted: {workflow_id}\n")

        workflow_done = asyncio.Event()

        def on_task_complete(event):
            print(f"  🎯 Task completed: {event.get('task_id', 'unknown')[:8]}")

        def on_complete(event):
            print(f"\n  ✅ Workflow completed!")
            workflow_done.set()

        def on_failure(event):
            print(f"\n  ❌ Workflow failed: {event.get('error', 'unknown')}")
            workflow_done.set()

        print("Setting up WebSocket monitoring...")
        try:
            monitor_task = await client.wait_for_workflow_async(
                workflow_id,
                on_task_complete=on_task_complete,
                on_complete=on_complete,
                on_failure=on_failure,
                timeout=30
            )
            print("  ✓ Monitoring started\n")

            await asyncio.wait_for(workflow_done.wait(), timeout=35)
            
            monitor_task.cancel()
            
            tasks = await client.get_workflow_tasks(workflow_id)
            print(f"\nResults ({len(tasks)} tasks):")
            for task in tasks:
                if task.get('result'):
                    print(f"  - {task.get('result')}")

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
