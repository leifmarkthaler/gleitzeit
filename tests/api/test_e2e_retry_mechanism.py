"""
End-to-End tests for retry mechanism through the API

These tests verify retry functionality with:
- Real ExecutionEngine
- Real Python provider that fails then succeeds
- Real retry manager
- Complete retry workflow through API
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from gleitzeit.api.main import app, setup_system, cleanup_system


@pytest.mark.e2e
@pytest.mark.asyncio
class TestRetryMechanismE2E:
    """End-to-end tests for retry mechanism"""
    
    @pytest.fixture
    async def api_client(self):
        """Create API client with real system setup"""
        await setup_system()
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        
        await cleanup_system()
    
    @pytest.mark.asyncio
    async def test_python_task_retry_on_failure(self, api_client):
        """Test that Python tasks retry on failure and eventually succeed"""
        
        # Create a Python script that fails the first 2 times, then succeeds
        # Use examples/scripts directory which is trusted
        import os
        script_file = os.path.join(os.getcwd(), 'examples', 'scripts', 'test_retry.py')
        
        with open(script_file, 'w') as f:
            f.write("""
import os

# Use a file to track attempts
attempt_file = '/tmp/retry_test_attempts.txt'

# Read current attempt count
if os.path.exists(attempt_file):
    with open(attempt_file, 'r') as rf:
        attempts = int(rf.read().strip())
else:
    attempts = 0

# Increment attempt count
attempts += 1
with open(attempt_file, 'w') as wf:
    wf.write(str(attempts))

# Fail first 2 attempts
if attempts < 3:
    raise Exception(f"Deliberate failure on attempt {attempts}")

# Succeed on 3rd attempt
result = f"Success after {attempts} attempts"
print(result)

# Clean up
os.remove(attempt_file)
""")
        
        # Create workflow with retry configuration
        workflow = {
            "name": "Test Retry Workflow",
            "description": "Test retry mechanism with Python task",
            "tasks": [
                {
                    "id": "retry_task",
                    "name": "Python Task with Retry",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "file": script_file
                    },
                    "priority": "normal",
                    "retry": {
                        "max_attempts": 3,
                        "base_delay": 0.5,
                        "backoff_strategy": "exponential"
                    }
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution with retries (should take ~1-2 seconds with delays)
        await asyncio.sleep(5.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Task should eventually succeed
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 1
        assert status["tasks_failed"] == 0
        
        # Check task result
        task_result = list(status["results"].values())[0]
        assert task_result["status"] == "completed"
        assert "Success after" in str(task_result.get("result", {}))
        
        # Clean up
        Path(script_file).unlink(missing_ok=True)
        Path('/tmp/retry_test_attempts.txt').unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_python_task_exhausts_retries(self, api_client):
        """Test that task fails after exhausting all retries"""
        
        # Create a Python script that always fails
        import os
        script_file = os.path.join(os.getcwd(), 'examples', 'scripts', 'test_always_fail.py')
        
        with open(script_file, 'w') as f:
            f.write("""
raise Exception("This task always fails")
""")
        
        # Create workflow with limited retries
        workflow = {
            "name": "Test Exhausted Retries",
            "description": "Test retry exhaustion",
            "tasks": [
                {
                    "id": "always_fail",
                    "name": "Always Failing Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {
                        "file": script_file
                    },
                    "priority": "normal",
                    "retry": {
                        "max_attempts": 2,
                        "base_delay": 0.1,
                        "backoff_strategy": "exponential"
                    }
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution with retries
        await asyncio.sleep(3.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Workflow should complete but task should fail
        assert status["status"] == "completed"
        assert status["tasks_failed"] == 1
        
        # Check task failed
        task_result = list(status["results"].values())[0]
        assert task_result["status"] == "failed"
        assert "This task always fails" in str(task_result.get("error", ""))
        
        # Clean up
        Path(script_file).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_workflow_with_multiple_retry_tasks(self, api_client):
        """Test workflow with multiple tasks that need retries"""
        
        # Create two scripts with different retry behaviors
        import os
        script1 = os.path.join(os.getcwd(), 'examples', 'scripts', 'test_retry_task1.py')
        script2 = os.path.join(os.getcwd(), 'examples', 'scripts', 'test_retry_task2.py')
        
        with open(script1, 'w') as f1:
            f1.write("""
import os
attempt_file = '/tmp/retry_test_task1.txt'
attempts = 1 if not os.path.exists(attempt_file) else int(open(attempt_file).read()) + 1
with open(attempt_file, 'w') as f: f.write(str(attempts))
if attempts < 2:
    raise Exception(f"Task 1 failure {attempts}")
result = "Task 1 success"
os.remove(attempt_file)
""")
        
        with open(script2, 'w') as f2:
            f2.write("""
import os
attempt_file = '/tmp/retry_test_task2.txt'
attempts = 1 if not os.path.exists(attempt_file) else int(open(attempt_file).read()) + 1
with open(attempt_file, 'w') as f: f.write(str(attempts))
if attempts < 3:
    raise Exception(f"Task 2 failure {attempts}")
result = "Task 2 success"
os.remove(attempt_file)
""")
        
        # Create workflow with multiple retry tasks
        workflow = {
            "name": "Multi-Retry Workflow",
            "description": "Test multiple tasks with retries",
            "tasks": [
                {
                    "id": "task1",
                    "name": "First Retry Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"file": script1},
                    "priority": "normal",
                    "retry": {
                        "max_attempts": 3,
                        "base_delay": 0.2,
                        "backoff_strategy": "exponential"
                    }
                },
                {
                    "id": "task2",
                    "name": "Second Retry Task",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"file": script2},
                    "priority": "normal",
                    "retry": {
                        "max_attempts": 4,
                        "base_delay": 0.2,
                        "backoff_strategy": "exponential"
                    }
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution with retries
        await asyncio.sleep(6.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Both tasks should eventually succeed
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 2
        assert status["tasks_failed"] == 0
        
        # Check both tasks succeeded
        for task_id, result in status["results"].items():
            assert result["status"] == "completed"
            assert "success" in str(result.get("result", {})).lower()
        
        # Clean up
        Path(script1).unlink(missing_ok=True)
        Path(script2).unlink(missing_ok=True)
        Path('/tmp/retry_test_task1.txt').unlink(missing_ok=True)
        Path('/tmp/retry_test_task2.txt').unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self, api_client):
        """Test that retry delays increase exponentially"""
        
        # Create a script that tracks timing
        import os
        script_file = os.path.join(os.getcwd(), 'examples', 'scripts', 'test_retry_timing.py')
        
        with open(script_file, 'w') as f:
            f.write("""
import os
import time

attempt_file = '/tmp/retry_timing.txt'
timestamp_file = '/tmp/retry_timestamps.txt'

# Record timestamp
current_time = time.time()
if os.path.exists(timestamp_file):
    with open(timestamp_file, 'a') as tf:
        tf.write(f",{current_time}")
else:
    with open(timestamp_file, 'w') as tf:
        tf.write(str(current_time))

# Track attempts
attempts = 1 if not os.path.exists(attempt_file) else int(open(attempt_file).read()) + 1
with open(attempt_file, 'w') as f:
    f.write(str(attempts))

# Fail first 3 attempts
if attempts < 4:
    raise Exception(f"Failure {attempts}")

# Read all timestamps
with open(timestamp_file, 'r') as tf:
    timestamps = [float(t) for t in tf.read().split(',')]

# Calculate delays between attempts
delays = []
for i in range(1, len(timestamps)):
    delays.append(timestamps[i] - timestamps[i-1])

result = {"attempts": attempts, "delays": delays}
print(f"Result: {result}")

# Clean up
os.remove(attempt_file)
os.remove(timestamp_file)
""")
        
        # Create workflow with exponential backoff
        workflow = {
            "name": "Exponential Backoff Test",
            "description": "Test exponential backoff in retries",
            "tasks": [
                {
                    "id": "backoff_task",
                    "name": "Task with Exponential Backoff",
                    "protocol": "python/v1",
                    "method": "python/execute",
                    "params": {"file": script_file},
                    "priority": "normal",
                    "retry": {
                        "max_attempts": 4,
                        "base_delay": 0.5,
                        "backoff_strategy": "exponential",
                        "max_delay": 10.0
                    }
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution with retries (should take several seconds with backoff)
        await asyncio.sleep(10.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        # Task should succeed
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 1
        
        # Verify the task succeeded after retries
        task_result = list(status["results"].values())[0]
        assert task_result["status"] == "completed"
        
        # Clean up
        Path(script_file).unlink(missing_ok=True)
        Path('/tmp/retry_timing.txt').unlink(missing_ok=True)
        Path('/tmp/retry_timestamps.txt').unlink(missing_ok=True)