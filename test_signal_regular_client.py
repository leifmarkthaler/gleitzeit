#!/usr/bin/env python3
"""
Test signal workflow using the regular client API (without easy syntax).
"""

import asyncio
import json
from gleitzeit.client import GleitzeitClient


async def test_signal_with_regular_client():
    """Test signal workflow using regular client API."""
    print("=" * 60)
    print("TESTING SIGNAL WORKFLOW WITH REGULAR CLIENT")
    print("=" * 60)
    print()

    # Create and initialize client
    client = GleitzeitClient(base_url="http://localhost:8003")
    await client.initialize()

    try:
        # Create wait workflow using regular dict structure
        wait_workflow = {
            "name": "approval_wait_workflow",
            "version": "1.0.0",
            "description": "Workflow that waits for approval signal",
            "tasks": [
                {
                    "id": "wait_for_approval",
                    "protocol": "signal/v1",
                    "method": "signal/wait",
                    "params": {
                        "signal": "approval_signal",
                        "timeout": 60
                    },
                    "dependencies": []
                }
            ]
        }

        print("Wait workflow structure:")
        print(json.dumps(wait_workflow, indent=2))

        # Submit wait workflow
        print("\nSubmitting wait workflow...")
        wait_result = await client.submit_workflow(wait_workflow)
        wait_workflow_id = wait_result.get("workflow_id")
        print(f"✅ Wait workflow submitted: {wait_workflow_id}")

        # Give it a moment to start
        await asyncio.sleep(2)

        # Check status
        wait_status = await client.get_workflow(wait_workflow_id)
        print(f"Wait workflow status: {wait_status.status}")

        # Create send workflow using regular dict structure
        send_workflow = {
            "name": "approval_sender_workflow",
            "version": "1.0.0",
            "description": "Workflow that sends approval signal",
            "tasks": [
                {
                    "id": "send_approval",
                    "protocol": "signal/v1",
                    "method": "signal/send",
                    "params": {
                        "signal": "approval_signal",
                        "target_workflow": wait_workflow_id,
                        "payload": {
                            "approved": True,
                            "timestamp": "2025-09-15",
                            "message": "Request approved via regular client!"
                        }
                    },
                    "dependencies": []
                }
            ]
        }

        print("\nSend workflow structure:")
        print(json.dumps(send_workflow, indent=2))

        # Submit send workflow
        print("\nSubmitting send workflow...")
        send_result = await client.submit_workflow(send_workflow)
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
            print("Both workflows completed successfully - signals work with regular client!")
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


async def test_signal_with_submit_task():
    """Test signals using submit_task API for individual task submission."""
    print("\n" + "=" * 60)
    print("TESTING SIGNALS WITH SUBMIT_TASK API")
    print("=" * 60)
    print()

    client = GleitzeitClient(base_url="http://localhost:8003")
    await client.initialize()

    try:
        # First, we need to create a workflow context for the wait task
        # Since signals are workflow-scoped, we need to submit as workflow
        print("Note: Signals require workflow context, so we'll use submit_workflow")
        print("For individual task submission without workflows, see submit_task examples")

        # Example of what submit_task would look like (but won't work for signals)
        # wait_task = await client.submit_task(
        #     protocol="signal/v1",
        #     method="signal/wait",
        #     params={"signal": "test_signal", "timeout": 60}
        # )

        # Instead, use minimal workflow
        minimal_wait = {
            "tasks": [{
                "id": "wait_task",
                "protocol": "signal/v1",
                "method": "signal/wait",
                "params": {"signal": "test_signal", "timeout": 30}
            }]
        }

        wait_result = await client.submit_workflow(minimal_wait)
        wait_id = wait_result.get("workflow_id")
        print(f"✅ Submitted minimal wait workflow: {wait_id}")

        await asyncio.sleep(1)

        # Send signal to the waiting workflow
        minimal_send = {
            "tasks": [{
                "id": "send_task",
                "protocol": "signal/v1",
                "method": "signal/send",
                "params": {
                    "signal": "test_signal",
                    "target_workflow": wait_id,
                    "payload": {"data": "test"}
                }
            }]
        }

        send_result = await client.submit_workflow(minimal_send)
        print(f"✅ Sent signal via minimal workflow: {send_result.get('workflow_id')}")

        await asyncio.sleep(2)

        # Check final status
        final = await client.get_workflow(wait_id)
        print(f"\n✅ Final status: {final.status}")

        return final.status == "completed"

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


async def main():
    """Main function."""
    # Test with regular workflow submission
    success1 = await test_signal_with_regular_client()

    # Test with minimal workflow approach
    success2 = await test_signal_with_submit_task()

    print("\n" + "=" * 60)
    if success1 and success2:
        print("✅ ALL REGULAR CLIENT SIGNAL TESTS SUCCESSFUL")
    else:
        print("❌ SOME REGULAR CLIENT SIGNAL TESTS FAILED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())