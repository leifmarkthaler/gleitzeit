#!/usr/bin/env python3
"""
Test signal workflow using the easy client syntax with t() and w().
"""

import asyncio
import json
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient


def create_wait_workflow():
    """Create a workflow that waits for a signal."""
    print("=== Creating Wait Workflow with Easy Syntax ===\n")

    # Create a task that waits for a signal
    wait_task = (
        t("wait_for_approval", "signal/v1:signal/wait")
        .with_(
            signal="approval_signal",
            timeout=60
        )
    )

    # Create the workflow
    workflow = (
        w(wait_task)
        .name("approval_wait_workflow")
        .version("1.0.0")
        .description("Workflow that waits for approval signal")
    )

    # Validate
    errors = workflow.validate()
    if errors:
        print(f"❌ Validation errors: {errors}")
        return None

    print("✅ Wait workflow validation passed!")
    return workflow


def create_send_workflow(target_workflow_id):
    """Create a workflow that sends a signal."""
    print(f"\n=== Creating Send Workflow for {target_workflow_id} ===\n")

    # Create a task that sends a signal
    send_task = (
        t("send_approval", "signal/v1:signal/send")
        .with_(
            signal="approval_signal",
            target_workflow=target_workflow_id,
            payload={"approved": True, "timestamp": "2025-09-14", "message": "Request approved!"}
        )
    )

    # Create the workflow
    workflow = (
        w(send_task)
        .name("approval_sender_workflow")
        .version("1.0.0")
        .description("Workflow that sends approval signal")
    )

    # Validate
    errors = workflow.validate()
    if errors:
        print(f"❌ Validation errors: {errors}")
        return None

    print("✅ Send workflow validation passed!")
    return workflow


async def test_signal_workflow():
    """Test the signal workflow with easy client."""
    print("=" * 60)
    print("TESTING SIGNAL WORKFLOW WITH EASY CLIENT")
    print("=" * 60)
    print()

    # Create and initialize client
    client = GleitzeitClient(base_url="http://localhost:8003")
    await client.initialize()

    try:
        # Create and submit wait workflow
        wait_workflow = create_wait_workflow()
        if not wait_workflow:
            print("Failed to create wait workflow")
            return

        wait_dict = wait_workflow.to_dict()
        print("\nWait workflow structure:")
        print(json.dumps(wait_dict, indent=2))

        print("\nSubmitting wait workflow...")
        wait_result = await client.submit_workflow(wait_dict)
        wait_workflow_id = wait_result.get("workflow_id")
        print(f"✅ Wait workflow submitted: {wait_workflow_id}")

        # Give it a moment to start
        await asyncio.sleep(2)

        # Check status
        wait_status = await client.get_workflow(wait_workflow_id)
        print(f"Wait workflow status: {wait_status.status}")

        # Create and submit send workflow
        send_workflow = create_send_workflow(wait_workflow_id)
        if not send_workflow:
            print("Failed to create send workflow")
            return

        send_dict = send_workflow.to_dict()
        print("\nSend workflow structure:")
        print(json.dumps(send_dict, indent=2))

        print("\nSubmitting send workflow...")
        send_result = await client.submit_workflow(send_dict)
        send_workflow_id = send_result.get("workflow_id")
        print(f"✅ Send workflow submitted: {send_workflow_id}")

        # Wait for signal processing
        print("\nWaiting for signal to be processed...")
        await asyncio.sleep(3)

        # Check both workflow statuses
        wait_final = await client.get_workflow(wait_workflow_id)
        send_final = await client.get_workflow(send_workflow_id)

        print(f"\n=== Final Results ===")
        print(f"Wait workflow status: {wait_final.status}")
        print(f"Send workflow status: {send_final.status}")

        if wait_final.status == "completed" and send_final.status == "completed":
            print(f"\n✅ Signal workflow test SUCCESSFUL!")
            print("Both workflows completed successfully - signals are working with easy client!")
        else:
            print(f"\n❌ Signal workflow test FAILED")
            if wait_final.status != "completed":
                print(f"  Wait workflow still in {wait_final.status} state")
            if send_final.status != "completed":
                print(f"  Send workflow still in {send_final.status} state")

        return wait_final.status == "completed" and send_final.status == "completed"

    except Exception as e:
        print(f"❌ Error testing signal workflow: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        pass  # Client doesn't have close method


async def main():
    """Main function."""
    success = await test_signal_workflow()

    print("\n" + "=" * 60)
    if success:
        print("✅ EASY CLIENT SIGNAL TEST SUCCESSFUL")
    else:
        print("❌ EASY CLIENT SIGNAL TEST FAILED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())