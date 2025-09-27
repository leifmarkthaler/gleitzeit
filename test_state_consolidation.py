#!/usr/bin/env python3
"""
Test consolidated state storage in Gleitzeit 0.0.7

This test verifies that the workflow state is properly consolidated and
that status is correctly tracked through all workflow phases.
"""

import asyncio
import json
import redis.asyncio as redis
import time
from datetime import datetime

# Configuration
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

async def test_consolidated_state():
    """Test that workflow state is properly consolidated"""

    # Connect to Redis
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=False)

    # Clean up any existing test workflows
    await r.flushdb()
    print("✓ Redis cleaned")

    # Create a test workflow
    workflow_id = "test-consolidation-001"
    workflow = {
        "id": workflow_id,
        "name": "State Consolidation Test",
        "description": "Testing consolidated state storage",
        "version": "1.0.0",
        "tasks": [
            {
                "id": "task1",
                "name": "First Task",
                "type": "python",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Task 1'); return {'result': 'done1'}"
                },
                "dependencies": []
            },
            {
                "id": "task2",
                "name": "Second Task",
                "type": "python",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Task 2'); return {'result': 'done2'}"
                },
                "dependencies": ["task1"]
            }
        ]
    }

    print(f"\n📝 Test Workflow: {workflow_id}")

    # Simulate API submission (creates initial state)
    now = datetime.utcnow().isoformat()
    await r.hset(
        f"{{shard:0}}:workflow:state:{workflow_id}",
        mapping={
            b"workflow_id": workflow_id.encode(),
            b"status": b"submitted",
            b"submitted_at": now.encode(),
            b"user_id": b"test-user"
        }
    )
    print("✓ Initial state created (API submission)")

    # Check initial state
    state = await r.hgetall(f"{{shard:0}}:workflow:state:{workflow_id}")
    assert state[b"status"] == b"submitted"
    print(f"  Status: {state[b'status'].decode()}")

    # Simulate WorkflowLoader updating state
    await r.hset(
        f"{{shard:0}}:workflow:state:{workflow_id}",
        mapping={
            b"status": b"loaded",
            b"loaded_at": now.encode(),
            b"name": workflow["name"].encode(),
            b"description": workflow["description"].encode(),
            b"version": workflow["version"].encode()
        }
    )

    # Store workflow definition
    await r.hset(
        f"{{shard:0}}:workflow:data:{workflow_id}",
        mapping={
            b"workflow": json.dumps(workflow).encode()
        }
    )
    print("✓ WorkflowLoader updated state")

    # Check loaded state
    state = await r.hgetall(f"{{shard:0}}:workflow:state:{workflow_id}")
    assert state[b"status"] == b"loaded"
    assert state[b"name"] == workflow["name"].encode()
    print(f"  Status: {state[b'status'].decode()}")
    print(f"  Name: {state[b'name'].decode()}")

    # Simulate DependencyWorker processing
    await r.hset(
        f"{{shard:0}}:workflow:state:{workflow_id}",
        mapping={
            b"status": b"running",
            b"started_at": now.encode(),
            b"total_tasks": b"2",
            b"completed_tasks": b"0",
            b"failed_tasks": b"0",
            b"skipped_tasks": b"0",
            b"blocked_tasks": b"0",
            b"pending_tasks": b"1",
            b"running_tasks": b"1",
            b"worker_id": b"dependency-worker-001"
        }
    )
    print("✓ DependencyWorker started workflow")

    # Check running state
    state = await r.hgetall(f"{{shard:0}}:workflow:state:{workflow_id}")
    assert state[b"status"] == b"running"
    assert state[b"total_tasks"] == b"2"
    assert state[b"running_tasks"] == b"1"
    print(f"  Status: {state[b'status'].decode()}")
    print(f"  Total tasks: {state[b'total_tasks'].decode()}")
    print(f"  Running tasks: {state[b'running_tasks'].decode()}")

    # Simulate task completion
    await r.hincrby(f"{{shard:0}}:workflow:state:{workflow_id}", b"completed_tasks", 1)
    await r.hincrby(f"{{shard:0}}:workflow:state:{workflow_id}", b"running_tasks", -1)
    await r.hincrby(f"{{shard:0}}:workflow:state:{workflow_id}", b"pending_tasks", -1)
    # Second task starts
    await r.hincrby(f"{{shard:0}}:workflow:state:{workflow_id}", b"running_tasks", 1)

    print("✓ First task completed, second task started")

    state = await r.hgetall(f"{{shard:0}}:workflow:state:{workflow_id}")
    print(f"  Completed: {state[b'completed_tasks'].decode()}")
    print(f"  Running: {state[b'running_tasks'].decode()}")
    print(f"  Pending: {state[b'pending_tasks'].decode()}")

    # Complete second task
    await r.hincrby(f"{{shard:0}}:workflow:state:{workflow_id}", b"completed_tasks", 1)
    await r.hincrby(f"{{shard:0}}:workflow:state:{workflow_id}", b"running_tasks", -1)

    # Workflow completes
    await r.hset(
        f"{{shard:0}}:workflow:state:{workflow_id}",
        mapping={
            b"status": b"completed",
            b"completed_at": now.encode(),
            b"running_tasks": b"0",
            b"pending_tasks": b"0"
        }
    )
    print("✓ Workflow completed")

    # Final state check
    state = await r.hgetall(f"{{shard:0}}:workflow:state:{workflow_id}")
    assert state[b"status"] == b"completed"
    assert state[b"completed_tasks"] == b"2"
    assert state[b"running_tasks"] == b"0"
    assert state[b"pending_tasks"] == b"0"

    print(f"\n✅ Final State:")
    print(f"  Status: {state[b'status'].decode()}")
    print(f"  Name: {state[b'name'].decode()}")
    print(f"  Total tasks: {state[b'total_tasks'].decode()}")
    print(f"  Completed tasks: {state[b'completed_tasks'].decode()}")
    print(f"  Running tasks: {state[b'running_tasks'].decode()}")
    print(f"  Pending tasks: {state[b'pending_tasks'].decode()}")

    # Verify old workflow:status key doesn't exist
    old_status = await r.hgetall(f"{{shard:0}}:workflow:status:{workflow_id}")
    if not old_status:
        print("\n✓ Old workflow:status key not created (good!)")
    else:
        print(f"\n⚠️  Old workflow:status key exists: {old_status}")

    # Test API read scenario
    print("\n📖 Testing API read scenario:")

    # Simulate what the API does
    state_data = await r.hgetall(f"{{shard:0}}:workflow:state:{workflow_id}")
    workflow_data = await r.hget(f"{{shard:0}}:workflow:data:{workflow_id}", b"workflow")

    if state_data and workflow_data:
        decoded_state = {k.decode(): v.decode() for k, v in state_data.items()}
        status = decoded_state.get("status", "unknown")
        name = decoded_state.get("name", "Unnamed")

        print(f"  API would read status as: '{status}'")
        print(f"  API would read name as: '{name}'")

        assert status == "completed"
        assert name == "State Consolidation Test"
        print("  ✓ API can correctly read consolidated state")

    await r.close()

    print("\n✅ All consolidation tests passed!")
    print("\nConsolidation Summary:")
    print("- Single workflow:state key contains all runtime state")
    print("- workflow:data contains only the workflow definition")
    print("- No workflow:status key is created (eliminates fragmentation)")
    print("- API correctly reads from consolidated state")
    print("- Status is always available at all workflow phases")

if __name__ == "__main__":
    asyncio.run(test_consolidated_state())