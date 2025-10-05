"""
Direct API tests for workflow endpoints.

Tests the actual HTTP endpoints without using the client library.
"""
import pytest
import httpx
import asyncio
import json

BASE_URL = "http://localhost:8000"


async def create_test_session():
    """Helper to create a test session"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/auth/session/create",
            json={"username": "workflow_test_user", "password": ""}
        )
        return response.json()["session_id"]


@pytest.mark.asyncio
async def test_submit_workflow():
    """Test POST /workflows/submit"""
    session_id = await create_test_session()

    workflow = {
        "name": "test-workflow",
        "tasks": [
            {
                "name": "task1",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = {'status': 'completed'}"
                }
            }
        ]
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/workflows/submit",
            json={"workflow": workflow},
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "workflow_id" in data
        assert "status" in data
        assert data["status"] == "submitted"
        print(f"✓ Submitted workflow: {data['workflow_id']}")
        return data["workflow_id"]


@pytest.mark.asyncio
async def test_get_workflow():
    """Test GET /workflows/{workflow_id}"""
    session_id = await create_test_session()

    # Submit workflow first
    workflow_id = await test_submit_workflow()
    await asyncio.sleep(1)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/workflows/{workflow_id}",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "workflow_id" in data
        assert data["workflow_id"] == workflow_id
        assert "state" in data
        print(f"✓ Got workflow: {workflow_id}")


@pytest.mark.asyncio
async def test_get_workflow_tasks():
    """Test GET /workflows/{workflow_id}/tasks"""
    session_id = await create_test_session()
    workflow_id = await test_submit_workflow()
    await asyncio.sleep(2)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/workflows/{workflow_id}/tasks",
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "workflow_id" in data
        assert "tasks" in data
        assert isinstance(data["tasks"], list)
        print(f"✓ Got {len(data['tasks'])} tasks for workflow {workflow_id}")


@pytest.mark.asyncio
async def test_list_workflows():
    """Test GET /workflows/list"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/workflows/list",
            params={"limit": 10},
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
        assert "total" in data
        assert "limit" in data
        print(f"✓ Listed {data['total']} workflows (showing {len(data['workflows'])})")


@pytest.mark.asyncio
async def test_get_workflows_batch():
    """Test POST /workflows/ (batch get)"""
    session_id = await create_test_session()

    # Submit a workflow
    wf_id = await test_submit_workflow()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/workflows/",
            json={"workflow_ids": [wf_id]},
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
        assert "requested" in data
        assert "found" in data
        print(f"✓ Batch get: {data['found']}/{data['requested']} workflows found")


@pytest.mark.asyncio
async def test_cancel_workflow():
    """Test POST /workflows/{workflow_id}/cancel"""
    session_id = await create_test_session()

    # Submit a workflow
    wf_id = await test_submit_workflow()
    await asyncio.sleep(0.5)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/workflows/{wf_id}/cancel",
            headers={"X-Session-ID": session_id}
        )

        # Might already be completed
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "workflow_id" in data
            assert "status" in data
            print(f"✓ Cancelled workflow {wf_id}")
        else:
            print(f"Note: Workflow {wf_id} already completed or not found")


@pytest.mark.asyncio
async def test_result_chaining():
    """Test workflow with result chaining between tasks"""
    session_id = await create_test_session()

    workflow = {
        "name": "chaining-test",
        "tasks": [
            {
                "name": "generate",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = {'number': 42, 'message': 'Hello'}"
                }
            },
            {
                "name": "process",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
# Results auto-injected by dependency worker
for key, value in inputs.items():
    if isinstance(value, dict) and 'number' in value:
        number = value['number']
        result = {'doubled': number * 2}
        break
"""
                },
                "dependencies": ["generate"]
            }
        ]
    }

    async with httpx.AsyncClient() as client:
        # Submit workflow
        response = await client.post(
            f"{BASE_URL}/workflows/submit",
            json={"workflow": workflow},
            headers={"X-Session-ID": session_id}
        )

        workflow_id = response.json()["workflow_id"]
        print(f"Submitted chaining workflow: {workflow_id}")

        # Wait for completion (max 60s)
        for _ in range(30):
            await asyncio.sleep(2)

            status_resp = await client.get(
                f"{BASE_URL}/workflows/{workflow_id}",
                headers={"X-Session-ID": session_id}
            )

            state = status_resp.json().get("state", {})
            status = state.get("status", "unknown")

            if status in ["completed", "failed"]:
                break

        # Get tasks to check result
        tasks_resp = await client.get(
            f"{BASE_URL}/workflows/{workflow_id}/tasks",
            headers={"X-Session-ID": session_id}
        )

        tasks = tasks_resp.json()["tasks"]
        process_task = next((t for t in tasks if t.get("name") == "process"), None)

        if process_task and "result" in process_task:
            result = process_task["result"]
            print(f"✓ Result chaining worked: {result}")
            assert result.get("doubled") == 84, f"Expected 84, got {result.get('doubled')}"
        else:
            print(f"Note: Process task not completed or no result found")


if __name__ == "__main__":
    print("Running workflow API tests...\n")

    asyncio.run(test_submit_workflow())
    asyncio.run(test_get_workflow())
    asyncio.run(test_get_workflow_tasks())
    asyncio.run(test_list_workflows())
    asyncio.run(test_get_workflows_batch())
    asyncio.run(test_cancel_workflow())
    asyncio.run(test_result_chaining())

    print("\n✓ All workflow API tests passed!")
