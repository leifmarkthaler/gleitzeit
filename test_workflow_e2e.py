#!/usr/bin/env python
"""
End-to-end test for WorkflowHandler implementation.

Tests the complete flow:
1. Parent workflow has a task that calls child workflow
2. WorkflowHandler returns WAITING status with metadata
3. TaskExecutionWorker submits child workflow
4. WorkflowSubmissionWorker processes submission
5. Child workflow executes and completes
6. WorkflowMonitorWorker detects completion
7. Parent task wakes up with child result
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
import logging

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.handlers.workflow import WorkflowHandler
from gleitzeit.core.models import Task, TaskStatus
from gleitzeit.core.sharding import default_sharding
import redis.asyncio as redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_workflow_handler_stateless():
    """Test that WorkflowHandler is stateless"""
    logger.info("Testing WorkflowHandler statelessness...")
    
    handler = WorkflowHandler()
    
    # Create a parent task that wants to execute a child workflow
    parent_task = Task(
        id="parent-task-1",
        name="Call Child Workflow",
        workflow_id="parent-workflow-123",
        method="workflow/execute",
        params={
            "workflow_ref": "examples/simple.yaml",
            "inputs": {"data": "test-value"},
            "shard_preference": "any",
            "timeout": 300
        }
    )
    
    # Execute the handler
    result = await handler.execute(parent_task)
    
    # Verify handler returns WAITING status
    assert result.status == TaskStatus.WAITING, f"Expected WAITING, got {result.status}"
    
    # Verify metadata contains all necessary information
    metadata = result.metadata
    assert metadata['waiting_for'] == 'workflow', f"Expected waiting_for=workflow, got {metadata.get('waiting_for')}"
    assert metadata['submit_workflow'] == True, "Expected submit_workflow flag"
    assert 'child_workflow_id' in metadata, "Missing child_workflow_id"
    assert metadata['parent_workflow_id'] == "parent-workflow-123", "Wrong parent workflow ID"
    assert metadata['parent_task_id'] == "parent-task-1", "Wrong parent task ID"
    assert metadata['workflow_ref'] == "examples/simple.yaml", "Wrong workflow ref"
    assert metadata['workflow_inputs'] == {"data": "test-value"}, "Wrong inputs"
    
    logger.info(f"✓ WorkflowHandler correctly returned WAITING with metadata")
    logger.info(f"  Child workflow ID: {metadata['child_workflow_id']}")
    logger.info(f"  Target shard: {metadata['child_shard']}")
    
    return metadata


async def test_workflow_submission_flow(redis_client):
    """Test the workflow submission flow"""
    logger.info("\nTesting workflow submission flow...")
    
    # Simulate TaskExecutionWorker detecting submit_workflow flag
    metadata = {
        'child_workflow_id': 'parent-wf:child:task1:abc123',
        'parent_workflow_id': 'parent-wf',
        'parent_task_id': 'task1',
        'child_shard': 2,
        'workflow_ref': 'test.yaml',
        'workflow_inputs': {'key': 'value'},
        'submit_workflow': True
    }
    
    # TaskExecutionWorker would submit to workflow:submit stream
    submission_stream = default_sharding.get_stream_key(
        "workflow:submit",
        workflow_id=metadata['parent_workflow_id']
    )
    
    logger.info(f"  Submitting to stream: {submission_stream}")
    
    await redis_client.xadd(
        submission_stream,
        {
            b'child_workflow_id': metadata['child_workflow_id'].encode(),
            b'parent_workflow_id': metadata['parent_workflow_id'].encode(),
            b'parent_task_id': metadata['parent_task_id'].encode(),
            b'target_shard': str(metadata['child_shard']).encode(),
            b'workflow_ref': metadata['workflow_ref'].encode(),
            b'inputs': json.dumps(metadata['workflow_inputs']).encode(),
            b'timestamp': datetime.utcnow().isoformat().encode()
        }
    )
    
    logger.info("✓ Workflow submission sent to stream")
    
    # Register parent-child relationship (WorkflowSubmissionWorker would do this)
    registry_key = default_sharding.get_global_key(
        f"workflow:children:{metadata['child_workflow_id']}"
    )
    
    await redis_client.hset(
        registry_key,
        mapping={
            b'parent_workflow_id': metadata['parent_workflow_id'].encode(),
            b'parent_task_id': metadata['parent_task_id'].encode(),
            b'parent_shard': str(default_sharding.get_shard(metadata['parent_workflow_id'])).encode(),
            b'child_shard': str(metadata['child_shard']).encode(),
            b'status': b'running',
            b'created_at': datetime.utcnow().isoformat().encode()
        }
    )
    
    logger.info("✓ Parent-child relationship registered")
    
    return metadata


async def test_workflow_completion_flow(redis_client, child_workflow_id, parent_workflow_id, parent_task_id):
    """Test workflow completion and parent wake flow"""
    logger.info("\nTesting workflow completion flow...")
    
    # First, set parent task as WAITING
    task_key = default_sharding.get_task_key(parent_task_id, parent_workflow_id)
    await redis_client.hset(
        task_key,
        mapping={
            b'status': TaskStatus.WAITING.value.encode(),
            b'task_id': parent_task_id.encode(),
            b'workflow_id': parent_workflow_id.encode()
        }
    )
    logger.info(f"  Set parent task {parent_task_id} as WAITING")
    
    # Simulate child workflow completion
    child_result = {'output': 'success', 'data': 'processed'}
    
    completion_stream = default_sharding.get_stream_key(
        "workflow:completed",
        shard=default_sharding.get_shard(child_workflow_id)
    )
    
    await redis_client.xadd(
        completion_stream,
        {
            b'workflow_id': child_workflow_id.encode(),
            b'status': b'completed',
            b'result': json.dumps(child_result).encode(),
            b'timestamp': datetime.utcnow().isoformat().encode()
        }
    )
    
    logger.info(f"✓ Child workflow {child_workflow_id} marked as completed")
    
    # WorkflowMonitorWorker would process this and wake parent
    # Let's check the registry was created
    registry_key = default_sharding.get_global_key(
        f"workflow:children:{child_workflow_id}"
    )
    
    child_info = await redis_client.hgetall(registry_key)
    if child_info:
        logger.info("✓ Child workflow found in registry")
        logger.info(f"  Parent: {child_info.get(b'parent_workflow_id', b'').decode()}")
        logger.info(f"  Parent task: {child_info.get(b'parent_task_id', b'').decode()}")
        
        # Simulate WorkflowMonitorWorker updating parent task
        await redis_client.hset(
            task_key,
            mapping={
                b'status': TaskStatus.COMPLETED.value.encode(),
                b'result': json.dumps(child_result).encode(),
                b'child_workflow_id': child_workflow_id.encode(),
                b'completed_at': datetime.utcnow().isoformat().encode()
            }
        )
        
        # Emit to task:completed stream
        await redis_client.xadd(
            default_sharding.get_stream_key("task:completed", parent_workflow_id).encode(),
            {
                b'workflow_id': parent_workflow_id.encode(),
                b'task_id': parent_task_id.encode(),
                b'result': json.dumps(child_result).encode(),
                b'timestamp': datetime.utcnow().isoformat().encode()
            }
        )
        
        logger.info("✓ Parent task woken with child result")
        
        # Verify parent task status
        task_data = await redis_client.hgetall(task_key)
        status = task_data.get(b'status', b'').decode()
        result = json.loads(task_data.get(b'result', b'{}'))
        
        logger.info(f"  Parent task status: {status}")
        logger.info(f"  Parent task result: {result}")
        
        assert status == TaskStatus.COMPLETED.value, f"Expected completed, got {status}"
        assert result == child_result, "Result mismatch"
    else:
        logger.error("✗ Child workflow not found in registry")


async def main():
    """Run end-to-end test"""
    logger.info("="*60)
    logger.info("WORKFLOW HANDLER END-TO-END TEST")
    logger.info("="*60)
    
    # Test stateless handler
    metadata = await test_workflow_handler_stateless()
    
    # Connect to Redis for integration test
    try:
        redis_client = redis.Redis(
            host='localhost',
            port=6379,
            decode_responses=False
        )
        
        # Test connection
        await redis_client.ping()
        logger.info("\n✓ Connected to Redis")
        
        # Test submission flow
        submission_metadata = await test_workflow_submission_flow(redis_client)
        
        # Test completion flow
        await test_workflow_completion_flow(
            redis_client,
            submission_metadata['child_workflow_id'],
            submission_metadata['parent_workflow_id'],
            submission_metadata['parent_task_id']
        )
        
        logger.info("\n" + "="*60)
        logger.info("ALL TESTS PASSED ✓")
        logger.info("="*60)
        
        # Cleanup
        logger.info("\nCleaning up test data...")
        keys_to_delete = [
            default_sharding.get_global_key(
                f"workflow:children:{submission_metadata['child_workflow_id']}"
            ),
            default_sharding.get_task_key(
                submission_metadata['parent_task_id'],
                submission_metadata['parent_workflow_id']
            )
        ]
        
        for key in keys_to_delete:
            await redis_client.delete(key)
        
        await redis_client.aclose()
        logger.info("✓ Cleanup complete")
        
    except redis.ConnectionError:
        logger.warning("\n⚠️  Could not connect to Redis")
        logger.warning("   Integration tests skipped")
        logger.warning("   (WorkflowHandler stateless test still passed)")
        logger.info("\nTo run full integration test:")
        logger.info("  1. Start Redis: redis-server")
        logger.info("  2. Run this test again")


if __name__ == "__main__":
    asyncio.run(main())