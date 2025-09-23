#!/usr/bin/env python3
"""
Test WorkflowLoaderWorkerV2 integration with handler system.

Verifies that the workflow loader:
- Discovers handlers dynamically
- Validates methods against handler capabilities
- Properly transforms tasks with protocol/method
"""

import asyncio
import json
from datetime import datetime

from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
from gleitzeit.workers.base import WorkerConfig


async def test_protocol_mapping():
    """Test that protocol mappings are built from handlers"""
    print("\n=== Testing Protocol Mapping ===")
    
    # Create worker config
    config = WorkerConfig(
        worker_type="workflow_loader",
        worker_id="test-loader",
        consumer_group="test-group"
    )
    
    # Create loader worker
    loader = WorkflowLoaderWorkerV2(config)
    
    # Check protocol mappings
    print(f"Task type mappings discovered:")
    for task_type, protocol in loader.type_to_protocol.items():
        print(f"  {task_type} -> {protocol}")
    
    # Verify core handlers are mapped
    assert loader.type_to_protocol.get('python') == 'python/v1', "Python handler not mapped"
    assert loader.type_to_protocol.get('timer') == 'timer/v1', "Timer handler not mapped"
    assert loader.type_to_protocol.get('signal') == 'signal/v1', "Signal handler not mapped"
    
    print("✓ Protocol mappings correctly built from handlers")
    
    # Check supported methods
    print(f"\nSupported methods by protocol:")
    for protocol, methods in loader.supported_methods.items():
        print(f"  {protocol}: {', '.join(methods)}")
    
    # Verify methods are discovered
    assert 'python/execute' in loader.supported_methods.get('python/v1', []), "Python methods not discovered"
    assert 'timer/sleep' in loader.supported_methods.get('timer/v1', []), "Timer methods not discovered"
    assert 'signal/wait' in loader.supported_methods.get('signal/v1', []), "Signal methods not discovered"
    
    print("✓ Methods correctly discovered from handlers")


async def test_workflow_validation():
    """Test workflow validation with handler capabilities"""
    print("\n=== Testing Workflow Validation ===")
    
    config = WorkerConfig(worker_type="workflow_loader", worker_id="test-loader", consumer_group="test-group")
    loader = WorkflowLoaderWorkerV2(config)
    
    # Test valid workflow
    valid_workflow = {
        'name': 'test-workflow',
        'tasks': [
            {
                'id': 'task1',
                'protocol': 'python/v1',
                'method': 'python/execute',
                'params': {'code': 'print("hello")'}
            },
            {
                'id': 'task2',
                'protocol': 'timer/v1',
                'method': 'timer/sleep',
                'params': {'duration': 1},
                'dependencies': ['task1']
            },
            {
                'id': 'task3',
                'protocol': 'signal/v1',
                'method': 'signal/wait',
                'params': {'signal_name': 'ready'},
                'dependencies': ['task2']
            }
        ]
    }
    
    errors = loader.validate_workflow(valid_workflow)
    assert len(errors) == 0, f"Valid workflow should have no errors, got: {errors}"
    print("✓ Valid workflow passes validation")
    
    # Test invalid method
    invalid_method_workflow = {
        'name': 'test-workflow',
        'tasks': [
            {
                'id': 'task1',
                'protocol': 'python/v1',
                'method': 'python/invalid_method',  # Invalid method
                'params': {}
            }
        ]
    }
    
    errors = loader.validate_workflow(invalid_method_workflow)
    assert len(errors) > 0, "Should detect invalid method"
    assert any('invalid_method' in err for err in errors), "Should mention invalid method"
    print(f"✓ Invalid method detected: {errors[0]}")
    
    # Test unsupported protocol
    invalid_protocol_workflow = {
        'name': 'test-workflow',
        'tasks': [
            {
                'id': 'task1',
                'protocol': 'unknown/v1',  # Unknown protocol
                'method': 'unknown/execute',
                'params': {}
            }
        ]
    }
    
    errors = loader.validate_workflow(invalid_protocol_workflow)
    assert len(errors) > 0, "Should detect unsupported protocol"
    assert any('unsupported protocol' in err for err in errors), "Should mention unsupported protocol"
    print(f"✓ Unsupported protocol detected: {errors[0]}")


async def test_task_transformation():
    """Test task transformation with handler protocols"""
    print("\n=== Testing Task Transformation ===")
    
    config = WorkerConfig(worker_type="workflow_loader", worker_id="test-loader", consumer_group="test-group")
    loader = WorkflowLoaderWorkerV2(config)
    
    # Test Python task transformation
    python_task = {
        'name': 'calculate',
        'type': 'python',
        'code': 'result = 2 + 2'
    }
    
    transformed = await loader.transform_task(python_task, 'workflow-1')
    
    assert transformed['protocol'] == 'python/v1', f"Expected python/v1, got {transformed['protocol']}"
    assert transformed['method'] == 'python/execute', f"Expected python/execute, got {transformed['method']}"
    assert transformed['params']['code'] == 'result = 2 + 2', "Code not preserved"
    
    print("✓ Python task correctly transformed")
    
    # Test Timer task transformation
    timer_task = {
        'name': 'wait',
        'type': 'timer',
        'delay': 5
    }
    
    transformed = await loader.transform_task(timer_task, 'workflow-1')
    
    assert transformed['protocol'] == 'timer/v1', f"Expected timer/v1, got {transformed['protocol']}"
    assert transformed['method'] == 'timer/sleep', f"Expected timer/sleep, got {transformed['method']}"
    assert transformed['params']['duration'] == 5, "Duration not set from delay"
    
    print("✓ Timer task correctly transformed")
    
    # Test Signal task transformation with wait_any
    signal_task = {
        'name': 'wait_signals',
        'type': 'signal',
        'signal_action': 'wait_any',
        'signal_names': ['sig1', 'sig2']
    }
    
    transformed = await loader.transform_task(signal_task, 'workflow-1')
    
    assert transformed['protocol'] == 'signal/v1', f"Expected signal/v1, got {transformed['protocol']}"
    assert transformed['method'] == 'signal/wait_any', f"Expected signal/wait_any, got {transformed['method']}"
    assert transformed['params']['signal_names'] == ['sig1', 'sig2'], "Signal names not preserved"
    
    print("✓ Signal task correctly transformed")


async def test_method_selection():
    """Test correct method selection based on task configuration"""
    print("\n=== Testing Method Selection ===")
    
    config = WorkerConfig(worker_type="workflow_loader", worker_id="test-loader", consumer_group="test-group")
    loader = WorkflowLoaderWorkerV2(config)
    
    # Test signal task with different actions
    signal_wait = {'type': 'signal', 'signal_action': 'wait'}
    method = loader._get_method_for_task(signal_wait, 'signal')
    assert method == 'signal/wait', f"Expected signal/wait, got {method}"
    print("✓ Signal wait method correctly selected")
    
    signal_wait_any = {'type': 'signal', 'signal_action': 'wait_any'}
    method = loader._get_method_for_task(signal_wait_any, 'signal')
    assert method == 'signal/wait_any', f"Expected signal/wait_any, got {method}"
    print("✓ Signal wait_any method correctly selected")
    
    signal_wait_all = {'type': 'signal', 'signal_action': 'wait_all'}
    method = loader._get_method_for_task(signal_wait_all, 'signal')
    assert method == 'signal/wait_all', f"Expected signal/wait_all, got {method}"
    print("✓ Signal wait_all method correctly selected")
    
    # Test explicit method override
    task_with_method = {'type': 'python', 'method': 'python/eval'}
    method = loader._get_method_for_task(task_with_method, 'python')
    assert method == 'python/eval', f"Expected python/eval, got {method}"
    print("✓ Explicit method override works")


async def test_complete_workflow_transformation():
    """Test complete workflow transformation with all handler types"""
    print("\n=== Testing Complete Workflow Transformation ===")
    
    config = WorkerConfig(worker_type="workflow_loader", worker_id="test-loader", consumer_group="test-group")
    loader = WorkflowLoaderWorkerV2(config)
    
    # Create a complex workflow using all handler types
    raw_workflow = {
        'name': 'multi-handler-workflow',
        'description': 'Test workflow using multiple handlers',
        'tasks': [
            {
                'name': 'compute',
                'type': 'python',
                'code': 'result = sum([1, 2, 3, 4, 5])'
            },
            {
                'name': 'wait_a_bit',
                'type': 'timer',
                'delay': 2,
                'dependencies': ['compute']
            },
            {
                'name': 'wait_signal',
                'type': 'signal',
                'signal_action': 'wait',
                'signal_name': 'proceed',
                'timeout': 60,
                'dependencies': ['wait_a_bit']
            },
            {
                'name': 'eval_result',
                'type': 'python',
                'method': 'python/eval',  # Explicit method
                'params': {'expression': '6 * 7'},
                'dependencies': ['wait_signal']
            }
        ]
    }
    
    # Transform workflow
    transformed = await loader.transform_workflow(raw_workflow, 'test-workflow-123')
    
    # Verify structure
    assert transformed['name'] == 'multi-handler-workflow'
    assert len(transformed['tasks']) == 4
    
    # Verify each task
    tasks_by_name = {t['name']: t for t in transformed['tasks']}
    
    # Check Python compute task
    compute = tasks_by_name['compute']
    assert compute['protocol'] == 'python/v1'
    assert compute['method'] == 'python/execute'
    assert 'result = sum' in compute['params']['code']
    
    # Check Timer task
    timer = tasks_by_name['wait_a_bit']
    assert timer['protocol'] == 'timer/v1'
    assert timer['method'] == 'timer/sleep'
    assert timer['params']['duration'] == 2
    assert timer['dependencies'] == ['compute']
    
    # Check Signal task
    signal = tasks_by_name['wait_signal']
    assert signal['protocol'] == 'signal/v1'
    assert signal['method'] == 'signal/wait'
    assert signal['params']['signal_name'] == 'proceed'
    assert signal['params']['timeout'] == 60
    assert signal['dependencies'] == ['wait_a_bit']
    
    # Check Python eval task
    eval_task = tasks_by_name['eval_result']
    assert eval_task['protocol'] == 'python/v1'
    assert eval_task['method'] == 'python/eval'
    assert eval_task['params']['expression'] == '6 * 7'
    assert eval_task['dependencies'] == ['wait_signal']
    
    print("✓ Complete workflow transformation successful")
    print(f"  - {len(transformed['tasks'])} tasks transformed")
    print(f"  - All protocols assigned: {set(t['protocol'] for t in transformed['tasks'])}")
    print(f"  - All methods assigned: {set(t['method'] for t in transformed['tasks'])}")


async def main():
    """Run all integration tests"""
    print("\n" + "="*50)
    print("   WORKFLOW LOADER INTEGRATION TEST SUITE")
    print("="*50)
    
    try:
        await test_protocol_mapping()
        await test_workflow_validation()
        await test_task_transformation()
        await test_method_selection()
        await test_complete_workflow_transformation()
        
        print("\n" + "="*50)
        print("     ✅ ALL INTEGRATION TESTS PASSED")
        print("="*50 + "\n")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
