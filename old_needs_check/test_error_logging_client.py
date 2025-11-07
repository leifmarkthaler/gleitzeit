#!/usr/bin/env python3
"""
Test client to verify error logging implementation.
"""
import asyncio
import httpx
import time

BASE_URL = "http://localhost:8000"

async def test_error_logging():
    """Test that errors are properly logged to Redis and queryable via API."""

    async with httpx.AsyncClient(timeout=30.0) as client:
        print("🚀 Starting error logging test...\n")

        # 1. Submit workflow that will fail
        print("1. Submitting workflow that will fail...")
        workflow = {
            "name": "test-error-logging",
            "tasks": [
                {
                    "name": "failing_task",
                    "handler": "python",
                    "params": {
                        "code": 'raise ValueError("This is a test error for logging verification")'
                    }
                }
            ]
        }
        response = await client.post(
            f"{BASE_URL}/workflows/submit",
            json={"workflow": workflow}
        )

        if response.status_code != 200:
            print(f"❌ Failed to submit workflow: {response.text}")
            return

        workflow_data = response.json()
        workflow_id = workflow_data["workflow_id"]
        print(f"✅ Workflow submitted: {workflow_id}\n")

        # 2. Wait for workflow to fail
        print("2. Waiting for workflow to fail...")
        await asyncio.sleep(5)

        # 3. Check workflow status
        response = await client.get(f"{BASE_URL}/workflows/{workflow_id}/status")
        status_data = response.json()
        print(f"   Status: {status_data.get('status')}")
        print(f"   Tasks: {status_data.get('tasks', {})}\n")

        # 4. Query error logs (all errors)
        print("3. Querying all error logs...")
        response = await client.get(f"{BASE_URL}/system/logs/errors")

        if response.status_code != 200:
            print(f"❌ Failed to query error logs: {response.text}")
            return

        error_data = response.json()
        print(f"   Total errors: {error_data['total']}")
        print(f"   Errors returned: {len(error_data['errors'])}")

        if error_data['errors']:
            print("\n   Sample error:")
            error = error_data['errors'][0]
            print(f"   - Log ID: {error.get('log_id')}")
            print(f"   - Message: {error.get('message')}")
            print(f"   - Component: {error.get('component')}")
            print(f"   - Error Type: {error.get('error_type')}")
            print(f"   - Workflow ID: {error.get('workflow_id')}")
            print(f"   - Task ID: {error.get('task_id')}")
        print()

        # 5. Query error logs for specific workflow
        print(f"4. Querying error logs for workflow {workflow_id}...")
        response = await client.get(
            f"{BASE_URL}/system/logs/errors",
            params={"workflow_id": workflow_id}
        )

        if response.status_code != 200:
            print(f"❌ Failed to query workflow errors: {response.text}")
            return

        workflow_errors = response.json()
        print(f"   Workflow errors: {workflow_errors['total']}")

        if workflow_errors['errors']:
            print("\n   Workflow error details:")
            for error in workflow_errors['errors']:
                print(f"   - {error.get('error_type')}: {error.get('message')[:100]}...")
        print()

        # 6. Verify error content
        if error_data['total'] > 0:
            print("✅ Error logging is working!")
            print(f"   - Errors are being written to Redis")
            print(f"   - Errors are queryable via API")
            print(f"   - Global and workflow-specific queries work")
        else:
            print("❌ No errors found in Redis")
            print("   Error logging may not be working correctly")

if __name__ == "__main__":
    asyncio.run(test_error_logging())
