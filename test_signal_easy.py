#!/usr/bin/env python3
"""
Test signal workflow using the easy client interface.
"""

import asyncio
from gleitzeit.easy import workflow, task

@task
async def wait_for_approval(signal_name: str = "approval", timeout: int = 60):
    """Wait for an approval signal."""
    print(f"Waiting for signal '{signal_name}'...")
    # This will use the signal/wait protocol
    return {
        "protocol": "signal/v1",
        "method": "signal/wait",
        "params": {
            "signal": signal_name,
            "timeout": timeout
        }
    }

@task
async def send_approval(target_workflow: str, signal_name: str = "approval"):
    """Send an approval signal to a workflow."""
    print(f"Sending signal '{signal_name}' to workflow {target_workflow}")
    return {
        "protocol": "signal/v1",
        "method": "signal/send",
        "params": {
            "signal": signal_name,
            "target_workflow": target_workflow,
            "payload": {"approved": True, "message": "Request approved!"}
        }
    }

@workflow
async def approval_workflow():
    """Workflow that waits for approval."""
    result = await wait_for_approval("approval", 60)
    print(f"Received signal with payload: {result}")
    return {"status": "approved", "signal_data": result}

@workflow
async def approver_workflow(target_workflow_id: str):
    """Workflow that sends approval."""
    result = await send_approval(target_workflow_id, "approval")
    return {"status": "signal_sent", "result": result}

async def main():
    """Test the signal workflow with easy client."""
    from gleitzeit.easy import Client

    # Create client
    client = Client(base_url="http://localhost:8003")

    print("Submitting approval workflow that waits for signal...")
    # Submit workflow that waits for approval
    wait_result = await client.submit(approval_workflow)
    wait_workflow_id = wait_result["workflow_id"]
    print(f"Waiting workflow ID: {wait_workflow_id}")

    # Give it a moment to start
    await asyncio.sleep(2)

    # Check status
    status = await client.get_workflow_status(wait_workflow_id)
    print(f"Waiting workflow status: {status['status']}")

    print(f"\nSending approval signal to workflow {wait_workflow_id}...")
    # Submit workflow that sends approval
    send_result = await client.submit(approver_workflow, target_workflow_id=wait_workflow_id)
    send_workflow_id = send_result["workflow_id"]
    print(f"Sender workflow ID: {send_workflow_id}")

    # Wait for signal to be processed
    await asyncio.sleep(3)

    # Check both workflow statuses
    wait_status = await client.get_workflow_status(wait_workflow_id)
    send_status = await client.get_workflow_status(send_workflow_id)

    print(f"\nFinal status of waiting workflow: {wait_status['status']}")
    print(f"Final status of sender workflow: {send_status['status']}")

    if wait_status['status'] == 'completed':
        # Get the result
        result = await client.get_workflow_result(wait_workflow_id)
        print(f"✅ Signal workflow completed successfully!")
        print(f"Result: {result}")
    else:
        print(f"❌ Workflow still in {wait_status['status']} state")
        # Get task details
        tasks = await client.get_workflow_tasks(wait_workflow_id)
        for task in tasks:
            print(f"  Task {task['id']}: {task['status']}")

if __name__ == "__main__":
    asyncio.run(main())