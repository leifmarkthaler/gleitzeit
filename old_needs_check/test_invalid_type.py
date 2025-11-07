"""Test workflow with invalid task type"""
import asyncio
import sys
sys.path.insert(0, '/Users/leifmarkthaler/github/gleitzeit 0.0.7/src')

from gleitzeit.client.client import GleitzeitClient

async def test_invalid_type():
    """Submit a workflow with invalid task type 'pythono' instead of 'python'"""
    client = GleitzeitClient()

    # Submit workflow with INVALID task type
    response = await client.submit_workflow(
        workflow={
            "name": "test_invalid_type",
            "description": "Test validation error for invalid task type",
            "tasks": [
                {
                    "id": "task1",
                    "type": "pythono",  # INVALID - should be "python"
                    "name": "Invalid task",
                    "params": {
                        "code": "print('hello')",
                        "method": "inline"
                    }
                }
            ]
        }
    )

    workflow_id = response.workflow_id
    print(f"✅ Submitted workflow: {workflow_id}")

    # Wait a bit for processing
    await asyncio.sleep(3)

    # Get workflow status
    status = await client.get_workflow_status(workflow_id)
    print(f"\n📊 Workflow Status:")
    print(f"   Status: {status.status}")
    print(f"   Error: {getattr(status, 'error', 'N/A')}")
    print(f"   Total Tasks: {status.total_tasks}")
    print(f"   Completed Tasks: {status.completed_tasks}")

    # Get timeline
    timeline = await client.get_workflow_timeline(workflow_id)
    print(f"\n📅 Timeline Events:")
    if hasattr(timeline, 'events'):
        for event in timeline.events:
            print(f"   - {event.event_type}: {getattr(event, 'message', '')}")
    else:
        print(f"   Timeline: {timeline}")

    await client.close()

if __name__ == "__main__":
    asyncio.run(test_invalid_type())
