#!/usr/bin/env python3
"""
Test signal workflow with optional protocol field.
Tests that protocol can be omitted and will be extracted from method.
"""

import asyncio
import json
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient


async def test_with_protocol():
    """Test with explicit protocol field (old way)."""
    print("=== Testing WITH explicit protocol field ===\n")

    client = GleitzeitClient(base_url="http://localhost:8003")
    await client.initialize()

    # Create workflow WITH protocol field
    workflow = {
        "name": "test_with_protocol",
        "tasks": [{
            "id": "wait_task",
            "protocol": "signal/v1",  # Explicit protocol
            "method": "signal/wait",
            "params": {
                "signal": "test_signal_1",
                "timeout": 30
            }
        }]
    }

    print("Workflow structure (WITH protocol):")
    print(json.dumps(workflow, indent=2))

    result = await client.submit_workflow(workflow)
    workflow_id = result.get("workflow_id")
    print(f"✅ Submitted workflow with explicit protocol: {workflow_id}")

    await asyncio.sleep(1)

    status = await client.get_workflow(workflow_id)
    print(f"Status: {status.status}")

    # Send signal to complete it
    send_workflow = {
        "tasks": [{
            "id": "send_task",
            "protocol": "signal/v1",
            "method": "signal/send",
            "params": {
                "signal": "test_signal_1",
                "target_workflow": workflow_id,
                "payload": {"test": "data"}
            }
        }]
    }

    await client.submit_workflow(send_workflow)
    await asyncio.sleep(2)

    final = await client.get_workflow(workflow_id)
    return final.status == "completed"


async def test_without_protocol():
    """Test without protocol field (new way - protocol extracted from method)."""
    print("\n=== Testing WITHOUT protocol field (extracted from method) ===\n")

    client = GleitzeitClient(base_url="http://localhost:8003")
    await client.initialize()

    # Create workflow WITHOUT protocol field
    workflow = {
        "name": "test_without_protocol",
        "tasks": [{
            "id": "wait_task",
            # NO protocol field - should be extracted from method
            "method": "signal/wait",
            "params": {
                "signal": "test_signal_2",
                "timeout": 30
            }
        }]
    }

    print("Workflow structure (WITHOUT protocol):")
    print(json.dumps(workflow, indent=2))

    result = await client.submit_workflow(workflow)
    workflow_id = result.get("workflow_id")
    print(f"✅ Submitted workflow without protocol field: {workflow_id}")

    await asyncio.sleep(1)

    status = await client.get_workflow(workflow_id)
    print(f"Status: {status.status}")

    # Send signal (also without protocol)
    send_workflow = {
        "tasks": [{
            "id": "send_task",
            # NO protocol field
            "method": "signal/send",
            "params": {
                "signal": "test_signal_2",
                "target_workflow": workflow_id,
                "payload": {"test": "data"}
            }
        }]
    }

    await client.submit_workflow(send_workflow)
    await asyncio.sleep(2)

    final = await client.get_workflow(workflow_id)
    return final.status == "completed"


async def test_easy_client_without_protocol():
    """Test easy client (which shouldn't specify protocol in the dict)."""
    print("\n=== Testing Easy Client (protocol in method) ===\n")

    client = GleitzeitClient(base_url="http://localhost:8003")
    await client.initialize()

    # Create workflow with easy client
    wait_task = (
        t("wait_approval", "signal/wait")  # Just method, no protocol
        .with_(signal="approval_signal", timeout=30)
    )

    workflow = w(wait_task).name("easy_test")

    workflow_dict = workflow.to_dict()
    print("Easy client generated structure:")
    print(json.dumps(workflow_dict, indent=2))

    result = await client.submit_workflow(workflow_dict)
    workflow_id = result.get("workflow_id")
    print(f"✅ Submitted easy client workflow: {workflow_id}")

    await asyncio.sleep(1)

    # Send signal
    send_task = (
        t("send_approval", "signal/send")
        .with_(
            signal="approval_signal",
            target_workflow=workflow_id,
            payload={"approved": True}
        )
    )

    send_workflow = w(send_task)
    await client.submit_workflow(send_workflow.to_dict())

    await asyncio.sleep(2)

    final = await client.get_workflow(workflow_id)
    return final.status == "completed"


async def main():
    """Test all formats."""
    print("=" * 60)
    print("TESTING OPTIONAL PROTOCOL FIELD")
    print("=" * 60)
    print()

    # Test with explicit protocol
    test1 = await test_with_protocol()

    # Test without protocol (extracted from method)
    test2 = await test_without_protocol()

    # Test easy client
    test3 = await test_easy_client_without_protocol()

    print("\n" + "=" * 60)
    print("TEST RESULTS:")
    print(f"  With explicit protocol: {'✅ PASSED' if test1 else '❌ FAILED'}")
    print(f"  Without protocol field: {'✅ PASSED' if test2 else '❌ FAILED'}")
    print(f"  Easy client:           {'✅ PASSED' if test3 else '❌ FAILED'}")

    if test1 and test2 and test3:
        print("\n✅ ALL TESTS PASSED - Protocol field is now optional!")
    else:
        print("\n❌ SOME TESTS FAILED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())