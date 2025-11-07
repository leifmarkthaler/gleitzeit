#!/usr/bin/env python3
"""
Test script showing non-blocking Ollama workflow with callbacks.

This demonstrates the new wait_for_workflow_async() method with:
1. Event-driven workflow monitoring with callbacks
2. Doing other work while workflow runs
3. on_complete / on_failure / on_task_complete callbacks
"""

import asyncio
import yaml
from gleitzeit.client import GleitzeitClient

async def do_other_work(n: int):
    """Simulate doing other work while workflow runs."""
    print(f"  [Other work #{n}] Starting some background task...")
    await asyncio.sleep(2)
    print(f"  [Other work #{n}] Completed!")

async def main():
    # Load workflow from YAML file
    with open("test_ollama_workflow.yaml", "r") as f:
        workflow = yaml.safe_load(f)

    async with GleitzeitClient(api_url="http://localhost:8000") as client:
        print("=== EVENT-DRIVEN / CALLBACK Pattern ===\n")

        # Submit workflow
        print("1. Submitting workflow...")
        response = await client.submit_workflow(workflow)
        workflow_id = response.workflow_id
        print(f"   ✓ Workflow {workflow_id} submitted!\n")

        # Set up event-driven monitoring with callbacks
        print("2. Setting up event callbacks (non-blocking)...")

        # Track completion
        workflow_done = asyncio.Event()

        def on_task_complete(event):
            print(f"   🎯 [Callback] Task completed: {event.get('task_id', 'unknown')}")

        def on_complete(event):
            print(f"   ✅ [Callback] Workflow completed successfully!")
            workflow_done.set()

        def on_failure(event):
            print(f"   ❌ [Callback] Workflow failed: {event.get('error', 'unknown')}")
            workflow_done.set()

        # Start monitoring in background (non-blocking)
        monitor_task = await client.wait_for_workflow_async(
            workflow_id,
            on_task_complete=on_task_complete,
            on_complete=on_complete,
            on_failure=on_failure,
            timeout=120
        )

        print("   ✓ Event monitoring started in background\n")

        # Do other work while workflow runs - callbacks will fire as events arrive
        print("3. Doing other work (callbacks fire in background)...")
        await do_other_work(1)
        await do_other_work(2)
        await do_other_work(3)
        print()

        # Wait for workflow to complete (via callback setting the event)
        print("4. Waiting for workflow completion event...")
        await workflow_done.wait()

        # Clean up monitoring task
        monitor_task.cancel()

        # Get final results
        print("\n5. Getting final results...")
        tasks = await client.get_workflow_tasks(workflow_id)
        print(f"   Task Results ({len(tasks)} tasks):")
        for task in tasks:
            result = task.get('result', {})
            if result:
                response_text = result.get('response', 'No response')
                print(f"   - {response_text}")

        print("\n=== COMPARISON ===")
        print("Blocking:     wait_for_workflow() - your code pauses")
        print("Polling:      loop + get_status() - you check periodically")
        print("Event-Driven: wait_for_workflow_async() - callbacks fire automatically")
        print("              ↑ Best for real-time updates!")

if __name__ == "__main__":
    asyncio.run(main())
