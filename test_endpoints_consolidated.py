#!/usr/bin/env python3
"""
Test that all workflow endpoints work correctly with consolidated state.
"""

import asyncio
import httpx
import json
from datetime import datetime

# Configuration
API_BASE_URL = "http://localhost:8000"
SESSION_ID = "test-session"

async def test_endpoints():
    """Test all workflow endpoints with consolidated state"""

    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
        headers = {"X-Session-ID": SESSION_ID}

        print("🧪 Testing Workflow Endpoints with Consolidated State\n")

        # 1. Submit a workflow
        print("1️⃣ Testing POST /workflows/submit")
        workflow = {
            "name": "Endpoint Test Workflow",
            "description": "Testing consolidated state",
            "version": "1.0.0",
            "tasks": [
                {
                    "name": "task1",
                    "type": "python",
                    "params": {
                        "code": "return {'result': 'test1'}"
                    },
                    "dependencies": []
                },
                {
                    "name": "task2",
                    "type": "python",
                    "params": {
                        "code": "return {'result': 'test2'}"
                    },
                    "dependencies": ["task1"]
                }
            ]
        }

        response = await client.post(
            "/workflows/submit",
            json={"workflow": workflow},
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()
            workflow_id = data["workflow_id"]
            print(f"  ✅ Workflow submitted: {workflow_id}")
            print(f"     Status: {data['status']}")
        else:
            print(f"  ❌ Failed to submit workflow: {response.status_code}")
            return

        # Wait a bit for processing
        await asyncio.sleep(2)

        # 2. Get workflow details
        print("\n2️⃣ Testing GET /workflows/{workflow_id}")
        response = await client.get(f"/workflows/{workflow_id}", headers=headers)

        if response.status_code == 200:
            data = response.json()
            state = data.get("state", {})

            # Check consolidated state fields
            print("  ✅ Workflow details retrieved")
            print(f"     Status: {state.get('status', 'unknown')}")
            print(f"     Name: {state.get('name', 'N/A')}")
            print(f"     Description: {state.get('description', 'N/A')}")
            print(f"     Version: {state.get('version', 'N/A')}")
            print(f"     Total tasks: {state.get('total_tasks', 'N/A')}")
            print(f"     Completed tasks: {state.get('completed_tasks', 'N/A')}")
            print(f"     Running tasks: {state.get('running_tasks', 'N/A')}")

            # Verify status is not "unknown"
            if state.get('status') == 'unknown':
                print("  ⚠️  WARNING: Status is 'unknown' - consolidation may not be working!")
            else:
                print("  ✅ Status field properly populated")
        else:
            print(f"  ❌ Failed to get workflow: {response.status_code}")

        # 3. List workflows
        print("\n3️⃣ Testing GET /workflows/list")
        response = await client.get("/workflows/list?limit=10", headers=headers)

        if response.status_code == 200:
            data = response.json()
            workflows = data.get("workflows", [])
            print(f"  ✅ Listed {len(workflows)} workflows")

            # Check if our workflow is in the list
            our_workflow = next((w for w in workflows if w["workflow_id"] == workflow_id), None)
            if our_workflow:
                print(f"     Found our workflow:")
                print(f"     - Status: {our_workflow.get('status', 'unknown')}")
                print(f"     - Name: {our_workflow.get('name', 'N/A')}")
                print(f"     - Progress: {our_workflow.get('progress', {})}")

                # Verify fields from consolidated state
                if our_workflow.get('status') != 'unknown':
                    print("  ✅ Workflow status correctly read from consolidated state")
                else:
                    print("  ⚠️  WARNING: Workflow showing 'unknown' status")

                if our_workflow.get('name') == workflow['name']:
                    print("  ✅ Workflow name correctly read from consolidated state")
                else:
                    print("  ⚠️  WARNING: Workflow name not matching")
            else:
                print(f"  ⚠️  WARNING: Workflow {workflow_id} not found in list")
        else:
            print(f"  ❌ Failed to list workflows: {response.status_code}")

        # 4. Get multiple workflows
        print("\n4️⃣ Testing POST /workflows/")
        response = await client.post(
            "/workflows/",
            json={"workflow_ids": [workflow_id]},
            headers=headers
        )

        if response.status_code == 200:
            data = response.json()
            workflows = data.get("workflows", [])
            if workflows:
                wf = workflows[0]
                status_data = wf.get("status", {})
                print(f"  ✅ Retrieved workflow data")
                print(f"     Status: {status_data.get('status', 'unknown')}")
                print(f"     Name: {status_data.get('name', 'N/A')}")

                if status_data.get('status') != 'unknown':
                    print("  ✅ Status available in batch endpoint")
                else:
                    print("  ⚠️  WARNING: Status is 'unknown' in batch endpoint")
            else:
                print("  ⚠️  No workflows returned")
        else:
            print(f"  ❌ Failed to get workflows: {response.status_code}")

        # 5. Get workflow tasks
        print("\n5️⃣ Testing GET /workflows/{workflow_id}/tasks")
        response = await client.get(f"/workflows/{workflow_id}/tasks", headers=headers)

        if response.status_code == 200:
            data = response.json()
            tasks = data.get("tasks", [])
            print(f"  ✅ Retrieved {len(tasks)} tasks")
            for task in tasks:
                print(f"     - {task.get('task_id', 'N/A')}: {task.get('status', 'unknown')}")
        else:
            print(f"  ❌ Failed to get tasks: {response.status_code}")

        # 6. Cancel workflow (optional test)
        print("\n6️⃣ Testing POST /workflows/{workflow_id}/cancel")
        response = await client.post(f"/workflows/{workflow_id}/cancel", headers=headers)

        if response.status_code == 200:
            data = response.json()
            print(f"  ✅ Workflow cancelled")
            print(f"     Tasks cancelled: {data.get('tasks_cancelled', 0)}")

            # Verify status changed to cancelled
            response = await client.get(f"/workflows/{workflow_id}", headers=headers)
            if response.status_code == 200:
                data = response.json()
                state = data.get("state", {})
                if state.get('status') == 'cancelled':
                    print("  ✅ Status correctly updated to 'cancelled'")
                else:
                    print(f"  ⚠️  WARNING: Status is '{state.get('status')}' instead of 'cancelled'")
        else:
            print(f"  ⚠️  Could not cancel workflow: {response.status_code}")

        print("\n" + "="*60)
        print("📊 Summary:")
        print("All workflow endpoints have been tested.")
        print("The consolidated state structure is working if:")
        print("  - Workflow status is NOT 'unknown'")
        print("  - Workflow name, description, version are available")
        print("  - Task counts are properly tracked")
        print("  - Status updates correctly (submitted -> loaded -> running -> completed/cancelled)")

async def main():
    """Main test function"""
    print("="*60)
    print("Testing Workflow Endpoints with Consolidated State")
    print("="*60 + "\n")

    print("⚠️  Note: Make sure the API server is running on port 8000")
    print("     and Redis is available.\n")

    await test_endpoints()

if __name__ == "__main__":
    asyncio.run(main())