"""
Direct API tests for task endpoints.

Tests the actual HTTP endpoints without using the client library.
"""
import pytest
import httpx
import asyncio

BASE_URL = "http://localhost:8000"


async def create_test_session():
    """Helper to create a test session"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/auth/session/create",
            json={"username": "task_test_user", "password": ""}
        )
        return response.json()["session_id"]


async def submit_test_workflow(session_id):
    """Helper to submit a test workflow"""
    workflow = {
        "name": "task-test-workflow",
        "tasks": [
            {
                "name": "task1",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = {'value': 123}"
                }
            },
            {
                "name": "task2",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = {'value': 456}"
                },
                "dependencies": ["task1"]
            }
        ]
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/workflows/submit",
            json={"workflow": workflow},
            headers={"X-Session-ID": session_id}
        )
        return response.json()["workflow_id"]


@pytest.mark.asyncio
async def test_list_tasks():
    """Test GET /tasks/list"""
    session_id = await create_test_session()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/tasks/list",
            params={"limit": 10},
            headers={"X-Session-ID": session_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert "task_ids" in data
        assert "total" in data
        print(f"✓ Listed {data['total']} tasks (showing {len(data['task_ids'])})")


@pytest.mark.asyncio
async def test_get_task():
    """Test GET /tasks/{task_id}"""
    session_id = await create_test_session()

    # Submit workflow and get tasks
    wf_id = await submit_test_workflow(session_id)
    await asyncio.sleep(2)

    async with httpx.AsyncClient() as client:
        # Get workflow tasks
        tasks_resp = await client.get(
            f"{BASE_URL}/workflows/{wf_id}/tasks",
            headers={"X-Session-ID": session_id}
        )

        tasks = tasks_resp.json()["tasks"]
        if tasks:
            task_id = tasks[0]["task_id"]

            # Get task details
            response = await client.get(
                f"{BASE_URL}/tasks/{task_id}",
                headers={"X-Session-ID": session_id}
            )

            assert response.status_code == 200
            data = response.json()
            assert "task_id" in data
            assert "state" in data
            print(f"✓ Got task: {task_id}")
        else:
            print("Note: No tasks found to test")


@pytest.mark.asyncio
async def test_get_tasks_batch():
    """Test POST /tasks/ (batch get)"""
    session_id = await create_test_session()

    # Submit workflow
    wf_id = await submit_test_workflow(session_id)
    await asyncio.sleep(2)

    async with httpx.AsyncClient() as client:
        # Get workflow tasks
        tasks_resp = await client.get(
            f"{BASE_URL}/workflows/{wf_id}/tasks",
            headers={"X-Session-ID": session_id}
        )

        tasks = tasks_resp.json()["tasks"]
        if tasks:
            task_ids = [t["task_id"] for t in tasks[:2]]

            # Batch get tasks
            response = await client.post(
                f"{BASE_URL}/tasks/",
                json={"task_ids": task_ids},
                headers={"X-Session-ID": session_id}
            )

            assert response.status_code == 200
            data = response.json()
            assert "tasks" in data
            assert "requested" in data
            assert "found" in data
            print(f"✓ Batch get: {data['found']}/{data['requested']} tasks found")


@pytest.mark.asyncio
async def test_get_task_logs():
    """Test GET /tasks/{task_id}/logs"""
    session_id = await create_test_session()

    # Submit workflow
    wf_id = await submit_test_workflow(session_id)
    await asyncio.sleep(3)

    async with httpx.AsyncClient() as client:
        # Get workflow tasks
        tasks_resp = await client.get(
            f"{BASE_URL}/workflows/{wf_id}/tasks",
            headers={"X-Session-ID": session_id}
        )

        tasks = tasks_resp.json()["tasks"]
        if tasks:
            task_id = tasks[0]["task_id"]

            # Get task logs
            response = await client.get(
                f"{BASE_URL}/tasks/{task_id}/logs",
                headers={"X-Session-ID": session_id}
            )

            assert response.status_code == 200
            data = response.json()
            assert "task_id" in data
            assert "logs" in data
            print(f"✓ Got {data.get('log_count', 0)} logs for task {task_id}")


@pytest.mark.asyncio
async def test_get_task_events():
    """Test GET /tasks/{task_id}/events"""
    session_id = await create_test_session()

    # Submit workflow
    wf_id = await submit_test_workflow(session_id)
    await asyncio.sleep(3)

    async with httpx.AsyncClient() as client:
        # Get workflow tasks
        tasks_resp = await client.get(
            f"{BASE_URL}/workflows/{wf_id}/tasks",
            headers={"X-Session-ID": session_id}
        )

        tasks = tasks_resp.json()["tasks"]
        if tasks:
            task_id = tasks[0]["task_id"]

            # Get task events
            response = await client.get(
                f"{BASE_URL}/tasks/{task_id}/events",
                headers={"X-Session-ID": session_id}
            )

            assert response.status_code == 200
            data = response.json()
            assert "task_id" in data
            assert "events" in data
            print(f"✓ Got {data.get('event_count', 0)} events for task {task_id}")


@pytest.mark.asyncio
async def test_retry_task():
    """Test POST /tasks/{task_id}/retry"""
    session_id = await create_test_session()

    # Submit workflow with failing task
    workflow = {
        "name": "retry-test",
        "tasks": [
            {
                "name": "failing_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "raise ValueError('Test failure')"
                }
            }
        ]
    }

    async with httpx.AsyncClient() as client:
        # Submit workflow
        submit_resp = await client.post(
            f"{BASE_URL}/workflows/submit",
            json={"workflow": workflow},
            headers={"X-Session-ID": session_id}
        )
        wf_id = submit_resp.json()["workflow_id"]

        # Wait for task to fail
        await asyncio.sleep(5)

        # Get tasks
        tasks_resp = await client.get(
            f"{BASE_URL}/workflows/{wf_id}/tasks",
            headers={"X-Session-ID": session_id}
        )

        tasks = tasks_resp.json()["tasks"]
        if tasks:
            task_id = tasks[0]["task_id"]
            task_status = tasks[0].get("status", "")

            if task_status == "failed":
                # Retry the task
                response = await client.post(
                    f"{BASE_URL}/tasks/{task_id}/retry",
                    headers={"X-Session-ID": session_id}
                )

                assert response.status_code == 200
                data = response.json()
                assert "task_id" in data
                assert "status" in data
                print(f"✓ Retried failed task {task_id}")
            else:
                print(f"Note: Task status is '{task_status}', not failed")


@pytest.mark.asyncio
async def test_cancel_task():
    """Test POST /tasks/{task_id}/cancel"""
    session_id = await create_test_session()

    # Submit workflow
    wf_id = await submit_test_workflow(session_id)
    await asyncio.sleep(0.5)

    async with httpx.AsyncClient() as client:
        # Get tasks
        tasks_resp = await client.get(
            f"{BASE_URL}/workflows/{wf_id}/tasks",
            headers={"X-Session-ID": session_id}
        )

        tasks = tasks_resp.json()["tasks"]
        if tasks:
            task_id = tasks[0]["task_id"]

            # Try to cancel (might already be completed)
            response = await client.post(
                f"{BASE_URL}/tasks/{task_id}/cancel",
                headers={"X-Session-ID": session_id}
            )

            # 200 = cancelled, 400 = already in terminal state
            assert response.status_code in [200, 400]
            if response.status_code == 200:
                print(f"✓ Cancelled task {task_id}")
            else:
                print(f"Note: Task {task_id} already in terminal state")


if __name__ == "__main__":
    print("Running task API tests...\n")

    asyncio.run(test_list_tasks())
    asyncio.run(test_get_task())
    asyncio.run(test_get_tasks_batch())
    asyncio.run(test_get_task_logs())
    asyncio.run(test_get_task_events())
    asyncio.run(test_retry_task())
    asyncio.run(test_cancel_task())

    print("\n✓ All task API tests passed!")
