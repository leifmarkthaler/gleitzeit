#!/usr/bin/env python3
"""
End-to-end test of workflow execution with handler architecture.

Tests the complete flow:
1. Workflow loading and validation
2. Task transformation with protocols
3. Task execution with handlers
4. Result handling
"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
from gleitzeit.workers.task_execution_worker_v4 import TaskExecutionWorkerV4
from gleitzeit.workers.base import WorkerConfig
from gleitzeit.core.models import Task, TaskStatus


async def test_simple_workflow_execution():
    """Test executing a simple workflow with Python tasks"""
    print("\n=== Testing Simple Workflow Execution ===")
    
    # Create mock Redis client
    mock_redis = AsyncMock()
    mock_redis.hset = AsyncMock()
    mock_redis.xadd = AsyncMock()
    mock_redis.hget = AsyncMock(return_value=None)
    
    # Create workers
    loader_config = WorkerConfig(
        worker_type="workflow_loader",
        worker_id="test-loader",
        consumer_group="test-group"
    )
    
    exec_config = WorkerConfig(
        worker_type="task_execution",
        worker_id="test-exec",
        consumer_group="test-group"
    )
    exec_config.__dict__['enabled_task_types'] = ['all']
    
    # Initialize workers
    loader = WorkflowLoaderWorkerV2(loader_config)
    executor = TaskExecutionWorkerV4(exec_config)
    executor.redis = mock_redis
    
    # Test workflow
    raw_workflow = {
        'name': 'test-workflow',
        'tasks': [
            {
                'id': 'add_numbers',
                'name': 'Add Numbers',
                'type': 'python',
                'method': 'python/eval',
                'params': {
                    'expression': '2 + 3'
                }
            },
            {
                'id': 'multiply',
                'name': 'Multiply Result',
                'type': 'python',
                'params': {
                    'code': 'result = 5 * 4'
                },
                'dependencies': ['add_numbers']
            }
        ]
    }
    
    # Step 1: Transform and validate workflow
    print("\n1. Transforming workflow...")
    transformed = await loader.transform_workflow(raw_workflow, 'wf-123')
    
    print(f"   Tasks: {len(transformed['tasks'])}")
    for task in transformed['tasks']:
        print(f"   - {task['name']}: protocol={task['protocol']}, method={task['method']}")
    
    # Validate
    errors = loader.validate_workflow(transformed)
    assert len(errors) == 0, f"Validation failed: {errors}"
    print("   ✓ Workflow validated successfully")
    
    # Step 2: Execute first task
    print("\n2. Executing first task (add_numbers)...")
    task1_data = transformed['tasks'][0]
    
    # Simulate task ready message
    message_data = {
        'workflow_id': 'wf-123',
        'task_id': 'add_numbers',
        'task': task1_data
    }
    
    await executor.process_message('task:ready:0', 'msg-1', message_data)
    
    # Check that completion was emitted
    assert mock_redis.xadd.called, "Task completion not emitted"
    call_args = mock_redis.xadd.call_args[0]
    stream_name = call_args[0].decode()
    assert 'task:completed' in stream_name, f"Wrong stream: {stream_name}"
    print("   ✓ Task executed and completed")
    
    # Step 3: Execute second task
    print("\n3. Executing second task (multiply)...")
    task2_data = transformed['tasks'][1]
    
    # Reset mock
    mock_redis.xadd.reset_mock()
    
    message_data = {
        'workflow_id': 'wf-123',
        'task_id': 'multiply',
        'task': task2_data,
        'resolved_inputs': {'add_numbers': 5}  # Simulate resolved dependency
    }
    
    await executor.process_message('task:ready:0', 'msg-2', message_data)
    
    assert mock_redis.xadd.called, "Task completion not emitted"
    print("   ✓ Task executed with resolved inputs")
    
    return True


async def test_timer_task_execution():
    """Test executing timer tasks"""
    print("\n=== Testing Timer Task Execution ===")
    
    # Create mock Redis
    mock_redis = AsyncMock()
    mock_redis.hset = AsyncMock()
    mock_redis.xadd = AsyncMock()
    
    # Create executor
    exec_config = WorkerConfig(
        worker_type="task_execution",
        worker_id="test-exec",
        consumer_group="test-group"
    )
    exec_config.__dict__['enabled_task_types'] = ['timer']
    
    executor = TaskExecutionWorkerV4(exec_config)
    executor.redis = mock_redis
    
    # Timer task
    task_data = {
        'id': 'wait_task',
        'name': 'Wait 5 seconds',
        'workflow_id': 'wf-456',
        'protocol': 'timer/v1',
        'method': 'timer/sleep',
        'params': {'duration': 5}
    }
    
    message_data = {
        'workflow_id': 'wf-456',
        'task_id': 'wait_task',
        'task': task_data
    }
    
    print("1. Executing timer task...")
    await executor.process_message('task:ready:0', 'msg-1', message_data)
    
    # Check that scheduled event was emitted (not completed)
    assert mock_redis.xadd.called, "Timer scheduled event not emitted"
    call_args = mock_redis.xadd.call_args[0]
    stream_name = call_args[0].decode()
    assert 'timer:scheduled' in stream_name, f"Expected timer:scheduled stream, got: {stream_name}"
    
    print("   ✓ Timer task scheduled (not completed immediately)")
    
    # Check task status was set to SCHEDULED
    hset_calls = mock_redis.hset.call_args_list
    assert any(
        b'status' in call[1]['mapping'] and 
        call[1]['mapping'][b'status'] == TaskStatus.SCHEDULED.encode()
        for call in hset_calls
    ), "Task status not set to SCHEDULED"
    
    print("   ✓ Task status set to SCHEDULED")
    
    return True


async def test_signal_task_execution():
    """Test executing signal tasks"""
    print("\n=== Testing Signal Task Execution ===")
    
    # Create mock Redis
    mock_redis = AsyncMock()
    mock_redis.hset = AsyncMock()
    mock_redis.xadd = AsyncMock()
    
    # Create executor
    exec_config = WorkerConfig(
        worker_type="task_execution",
        worker_id="test-exec",
        consumer_group="test-group"
    )
    exec_config.__dict__['enabled_task_types'] = ['signal']
    
    executor = TaskExecutionWorkerV4(exec_config)
    executor.redis = mock_redis
    
    # Signal task
    task_data = {
        'id': 'wait_signal',
        'name': 'Wait for ready signal',
        'workflow_id': 'wf-789',
        'protocol': 'signal/v1',
        'method': 'signal/wait',
        'params': {'signal_name': 'ready', 'timeout': 60}
    }
    
    message_data = {
        'workflow_id': 'wf-789',
        'task_id': 'wait_signal',
        'task': task_data
    }
    
    print("1. Executing signal task...")
    await executor.process_message('task:ready:0', 'msg-1', message_data)
    
    # Check that waiting event was emitted
    assert mock_redis.xadd.called, "Signal waiting event not emitted"
    call_args = mock_redis.xadd.call_args[0]
    stream_name = call_args[0].decode()
    assert 'signal:waiting' in stream_name, f"Expected signal:waiting stream, got: {stream_name}"
    
    print("   ✓ Signal task set to waiting")
    
    # Check task status was set to WAITING
    hset_calls = mock_redis.hset.call_args_list
    assert any(
        b'status' in call[1]['mapping'] and 
        call[1]['mapping'][b'status'] == TaskStatus.WAITING.encode()
        for call in hset_calls
    ), "Task status not set to WAITING"
    
    print("   ✓ Task status set to WAITING")
    
    return True


async def test_type_specific_worker():
    """Test worker that only handles specific task types"""
    print("\n=== Testing Type-Specific Worker ===")
    
    # Create worker that only handles Python tasks
    exec_config = WorkerConfig(
        worker_type="task_execution",
        worker_id="python-worker",
        consumer_group="test-group"
    )
    exec_config.__dict__['enabled_task_types'] = ['python']
    
    executor = TaskExecutionWorkerV4(exec_config)
    executor.redis = AsyncMock()
    
    print(f"1. Worker initialized with handlers: {list(executor.handlers.keys())}")
    assert 'python/v1' in executor.handlers, "Python handler not loaded"
    assert 'timer/v1' not in executor.handlers, "Timer handler should not be loaded"
    assert 'signal/v1' not in executor.handlers, "Signal handler should not be loaded"
    
    print("   ✓ Worker correctly loaded only Python handler")
    
    # Try to process a timer task (should skip)
    timer_task = {
        'id': 'timer_task',
        'name': 'Timer Task',
        'workflow_id': 'wf-999',
        'protocol': 'timer/v1',
        'method': 'timer/sleep',
        'params': {'duration': 1}
    }
    
    message_data = {
        'workflow_id': 'wf-999',
        'task_id': 'timer_task',
        'task': timer_task
    }
    
    print("\n2. Attempting to process timer task...")
    await executor.process_message('task:ready:0', 'msg-1', message_data)
    
    # Should not execute (no xadd calls)
    assert not executor.redis.xadd.called, "Timer task should not be executed"
    print("   ✓ Timer task correctly skipped by Python-only worker")
    
    return True


async def main():
    """Run all E2E tests"""
    print("\n" + "="*60)
    print("   WORKFLOW EXECUTION END-TO-END TESTS")
    print("="*60)
    
    try:
        # Run tests
        await test_simple_workflow_execution()
        await test_timer_task_execution()
        await test_signal_task_execution()
        await test_type_specific_worker()
        
        print("\n" + "="*60)
        print("     ✅ ALL E2E TESTS PASSED")
        print("="*60 + "\n")
        
        print("\nSummary:")
        print("✓ Workflows are validated with handler capabilities")
        print("✓ Tasks are transformed with correct protocols")
        print("✓ Python tasks execute and complete")
        print("✓ Timer tasks return SCHEDULED status")
        print("✓ Signal tasks return WAITING status")
        print("✓ Type-specific workers only load needed handlers")
        print("\nThe handler architecture is working correctly!")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
