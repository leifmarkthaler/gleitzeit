#!/usr/bin/env python3
"""
Test signal workflow with the easy client.

This demonstrates using signals to coordinate workflow execution:
1. Start task begins processing
2. Wait for approval signal
3. Continue with approved processing
"""

import asyncio
import json
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient


async def create_signal_workflow():
    """Create a workflow that uses signals for coordination."""
    print("=== Creating Signal-Based Workflow ===\n")

    # Task 1: Initial processing
    start_task = (
        t("initialize", "python/v1:python/execute")
        .with_(file="print_start.py")  # Simple task that prints and returns data
        .with_timeout(30)
    )

    # Task 2: Wait for approval signal
    wait_for_approval = (
        t("wait_approval", "signal/v1:signal/wait")
        .needs("initialize")
        .with_(
            signal="approval_signal",  # Changed from signal_name to signal
            timeout=300  # Wait up to 5 minutes for signal
        )
        .with_timeout(310)  # Task timeout slightly longer than signal timeout
    )

    # Task 3: Process after approval
    process_approved = (
        t("process_approved", "python/v1:python/execute")
        .needs("wait_approval")
        .with_(file="process_ollama_response.py")  # Process after signal received
        .with_retry(max_attempts=3, delay=2.0)
        .with_timeout(60)
    )

    # Create workflow
    workflow = (
        w(start_task, wait_for_approval, process_approved)
        .name("signal_approval_workflow")
        .version("1.0.0")
        .description("Workflow that waits for external approval signal")
    )

    return workflow


async def create_multi_signal_workflow():
    """Create a workflow that waits for multiple signals."""
    print("\n=== Creating Multi-Signal Workflow ===\n")

    # Task 1: Start processing
    init = (
        t("init", "python/v1:python/execute")
        .with_(file="print_start.py")
    )

    # Task 2: Wait for ANY of multiple signals
    wait_any = (
        t("wait_any_signal", "signal/v1:signal/wait_any")
        .needs("init")
        .with_(
            signals=["cancel_signal", "proceed_signal", "retry_signal"],  # Changed from signal_names to signals
            timeout=120
        )
    )

    # Task 3: Process based on which signal was received
    process_signal = (
        t("process_signal", "python/v1:python/execute")
        .needs("wait_any_signal")
        .with_(file="log_error.py")  # Log which signal was received
    )

    # Create workflow
    workflow = (
        w(init, wait_any, process_signal)
        .name("multi_signal_workflow")
        .version("1.0.0")
        .description("Workflow that responds to different signals")
    )

    return workflow


async def submit_and_monitor_workflow(workflow, client):
    """Submit workflow and monitor its progress."""

    # Validate workflow
    errors = workflow.validate()
    if errors:
        print(f"❌ Validation errors: {errors}")
        return None

    print("✅ Workflow validated successfully\n")

    # Show workflow structure
    workflow_dict = workflow.to_dict()
    print("Workflow structure:")
    print(json.dumps(workflow_dict, indent=2))

    # Submit workflow
    try:
        print("\nSubmitting workflow...")
        result = await client.submit_workflow(workflow_dict)
        workflow_id = result.get("workflow_id")
        print(f"✅ Workflow submitted: {workflow_id}")

        return workflow_id

    except Exception as e:
        print(f"❌ Error submitting workflow: {e}")
        return None


async def send_signal(client, signal_name, workflow_id=None, data=None):
    """Send a signal to wake up waiting tasks."""
    print(f"\n📨 Sending signal: {signal_name} to workflow: {workflow_id}")

    # Create a signal sender task
    signal_task = (
        t(f"send_{signal_name}", "signal/v1:signal/send")
        .with_(
            signal=signal_name,  # The signal name
            target_workflow=workflow_id,  # CRITICAL: Specify target workflow!
            payload=data or {"approved": True, "timestamp": "2025-09-14T12:00:00Z"}
        )
    )

    # Create a simple workflow just to send the signal
    signal_workflow = (
        w(signal_task)
        .name(f"send_{signal_name}_workflow")
        .version("1.0.0")
    )

    # Submit the signal workflow
    try:
        workflow_dict = signal_workflow.to_dict()
        result = await client.submit_workflow(workflow_dict)
        signal_workflow_id = result.get("workflow_id")
        print(f"✅ Signal sent via workflow: {signal_workflow_id}")

        # Wait for signal to be sent
        await asyncio.sleep(2)

        # Check status
        workflow_obj = await client.get_workflow(signal_workflow_id)
        print(f"Signal workflow status: {workflow_obj.status}")

    except Exception as e:
        print(f"❌ Error sending signal: {e}")


async def monitor_workflow(client, workflow_id):
    """Monitor workflow progress."""
    print(f"\n📊 Monitoring workflow: {workflow_id}")

    max_attempts = 30
    for i in range(max_attempts):
        await asyncio.sleep(2)

        workflow_obj = await client.get_workflow(workflow_id)
        print(f"  [{i+1}/{max_attempts}] Status: {workflow_obj.status}")

        if workflow_obj.status in ["completed", "failed"]:
            return workflow_obj

    return workflow_obj


async def test_signal_workflow():
    """Test the signal workflow end-to-end."""
    print("=" * 60)
    print("TESTING SIGNAL WORKFLOW WITH EASY CLIENT")
    print("=" * 60)
    print()

    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Create and submit signal workflow
    workflow = await create_signal_workflow()
    workflow_id = await submit_and_monitor_workflow(workflow, client)

    if not workflow_id:
        return

    # Monitor for a bit to see it waiting
    print("\n⏳ Workflow should be waiting for signal...")
    await asyncio.sleep(5)

    workflow_obj = await client.get_workflow(workflow_id)
    print(f"Current status: {workflow_obj.status}")

    # Now send the approval signal
    await send_signal(client, "approval_signal", workflow_id)

    # Monitor workflow completion
    print("\n⏳ Monitoring workflow after signal...")
    final_workflow = await monitor_workflow(client, workflow_id)

    print(f"\n=== Final Result ===")
    print(f"Status: {final_workflow.status}")

    if final_workflow.status == "completed":
        print("✅ Signal workflow completed successfully!")
    else:
        print("❌ Signal workflow did not complete as expected")


async def test_multi_signal_workflow():
    """Test workflow with multiple signals."""
    print("\n" + "=" * 60)
    print("TESTING MULTI-SIGNAL WORKFLOW")
    print("=" * 60)
    print()

    client = GleitzeitClient(base_url="http://localhost:8000")
    await client.initialize()

    # Create and submit multi-signal workflow
    workflow = await create_multi_signal_workflow()
    workflow_id = await submit_and_monitor_workflow(workflow, client)

    if not workflow_id:
        return

    # Wait and then send one of the signals
    print("\n⏳ Workflow waiting for any of: cancel_signal, proceed_signal, retry_signal")
    await asyncio.sleep(3)

    # Send the proceed signal
    await send_signal(client, "proceed_signal", workflow_id, {"action": "proceed"})

    # Monitor completion
    final_workflow = await monitor_workflow(client, workflow_id)

    print(f"\n=== Final Result ===")
    print(f"Status: {final_workflow.status}")


async def main():
    """Main test function."""

    # Test basic signal workflow
    await test_signal_workflow()

    # Test multi-signal workflow
    # await test_multi_signal_workflow()

    print("\n" + "=" * 60)
    print("SIGNAL WORKFLOW TESTS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())