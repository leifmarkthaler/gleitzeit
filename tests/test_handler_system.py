#!/usr/bin/env python3
"""
Test script for the new handler system.

Tests:
- Handler auto-discovery
- Handler registration
- Handler execution
- Metrics collection
"""

import asyncio
import json
from datetime import datetime

from gleitzeit.handlers import handler_loader, HandlerRegistry
from gleitzeit.core.models import Task, TaskStatus, TaskResult
from gleitzeit.core.errors import GleitzeitError, ErrorCode


async def test_handler_discovery():
    """Test that all handlers are discovered"""
    print("\n=== Testing Handler Discovery ===")
    
    # Get all capabilities
    capabilities = handler_loader.get_all_capabilities()
    
    print(f"Found {len(capabilities)} handlers:")
    for protocol, caps in capabilities.items():
        print(f"  - {protocol}: {caps.get('task_types', [])}")
        methods = caps.get('methods', {})
        if methods:
            print(f"    Methods: {', '.join(methods.keys())}")
    
    # Verify core handlers are present
    assert 'python/v1' in capabilities, "PythonHandler not found"
    assert 'timer/v1' in capabilities, "TimerHandler not found"
    assert 'signal/v1' in capabilities, "SignalHandler not found"
    
    print("✓ All core handlers discovered")


async def test_handler_registry():
    """Test handler registry functions"""
    print("\n=== Testing Handler Registry ===")
    
    # Get handlers by protocol
    python_handler = HandlerRegistry.get_handler('python/v1')
    timer_handler = HandlerRegistry.get_handler('timer/v1')
    signal_handler = HandlerRegistry.get_handler('signal/v1')
    
    assert python_handler is not None, "PythonHandler not in registry"
    assert timer_handler is not None, "TimerHandler not in registry"
    assert signal_handler is not None, "SignalHandler not in registry"
    
    print("✓ Handlers accessible via protocol")
    
    # Get handlers by task type
    python_by_type = HandlerRegistry.get_handler_for_type('python')
    timer_by_type = HandlerRegistry.get_handler_for_type('timer')
    signal_by_type = HandlerRegistry.get_handler_for_type('signal')
    
    assert python_by_type is not None, "PythonHandler not accessible by type"
    assert timer_by_type is not None, "TimerHandler not accessible by type"
    assert signal_by_type is not None, "SignalHandler not accessible by type"
    
    print("✓ Handlers accessible via task type")
    
    # Get handlers by method
    python_by_method = HandlerRegistry.get_handler_for_method('python/execute')
    timer_by_method = HandlerRegistry.get_handler_for_method('timer/sleep')
    signal_by_method = HandlerRegistry.get_handler_for_method('signal/wait')
    
    assert python_by_method is not None, "PythonHandler not accessible by method"
    assert timer_by_method is not None, "TimerHandler not accessible by method"
    assert signal_by_method is not None, "SignalHandler not accessible by method"
    
    print("✓ Handlers accessible via method")


async def test_python_handler():
    """Test PythonHandler execution"""
    print("\n=== Testing PythonHandler ===")
    
    handler_class = HandlerRegistry.get_handler('python/v1')
    handler = handler_class(config={'default_timeout': 10})
    
    # Test simple execution
    task = Task(
        id="test-python-1",
        name="Python Addition Test",
        workflow_id="test-workflow",
        task_type="python",
        protocol="python/v1",
        method="python/execute",
        params={
            'code': 'result = 2 + 2'
        }
    )
    
    result = await handler.execute(task)
    
    assert result.status == TaskStatus.COMPLETED, f"Expected COMPLETED, got {result.status}"
    assert result.result == 4, f"Expected 4, got {result.result}"
    
    print(f"✓ Python execution: 2 + 2 = {result.result}")
    
    # Test evaluation
    task2 = Task(
        id="test-python-2",
        name="Python Eval Test",
        workflow_id="test-workflow",
        task_type="python",
        protocol="python/v1",
        method="python/eval",
        params={
            'expression': '3 * 7',
            'context': {}
        }
    )
    
    result2 = await handler.execute(task2)
    
    assert result2.status == TaskStatus.COMPLETED, f"Expected COMPLETED, got {result2.status}"
    assert result2.result == 21, f"Expected 21, got {result2.result}"
    
    print(f"✓ Python eval: 3 * 7 = {result2.result}")


async def test_timer_handler():
    """Test TimerHandler execution"""
    print("\n=== Testing TimerHandler ===")
    
    handler_class = HandlerRegistry.get_handler('timer/v1')
    handler = handler_class(config={'max_duration': 3600})
    
    # Test sleep task
    task = Task(
        id="test-timer-1",
        name="Timer Sleep Test",
        workflow_id="test-workflow",
        task_type="timer",
        protocol="timer/v1",
        method="timer/sleep",
        params={'duration': 1.5}
    )
    
    result = await handler.execute(task)
    
    # Timer should return SCHEDULED status
    assert result.status == TaskStatus.SCHEDULED, f"Expected SCHEDULED, got {result.status}"
    assert 'wake_time' in result.metadata, "Missing wake_time in metadata"
    assert result.metadata['timer_type'] == 'sleep', "Wrong timer type"
    
    print(f"✓ Timer sleep scheduled for 1.5s")
    
    # Test zero duration (immediate completion)
    task2 = Task(
        id="test-timer-2",
        name="Timer Zero Duration Test",
        workflow_id="test-workflow",
        task_type="timer",
        protocol="timer/v1",
        method="timer/sleep",
        params={'duration': 0}
    )
    
    result2 = await handler.execute(task2)
    
    assert result2.status == TaskStatus.COMPLETED, f"Expected COMPLETED for zero duration, got {result2.status}"
    
    print("✓ Timer with zero duration completed immediately")
    
    # Test schedule task
    task3 = Task(
        id="test-timer-3",
        name="Timer Schedule Test",
        workflow_id="test-workflow",
        task_type="timer",
        protocol="timer/v1",
        method="timer/schedule",
        params={'interval': 60, 'max_runs': 5}
    )
    
    result3 = await handler.execute(task3)
    
    assert result3.status == TaskStatus.SCHEDULED, f"Expected SCHEDULED, got {result3.status}"
    assert result3.metadata['timer_type'] == 'schedule', "Wrong timer type"
    assert result3.metadata['interval'] == 60, "Wrong interval"
    
    print("✓ Timer schedule configured for 60s intervals")


async def test_signal_handler():
    """Test SignalHandler execution"""
    print("\n=== Testing SignalHandler ===")
    
    handler_class = HandlerRegistry.get_handler('signal/v1')
    handler = handler_class(config={})
    
    # Test wait for single signal
    task = Task(
        id="test-signal-1",
        name="Signal Wait Test",
        workflow_id="test-workflow",
        task_type="signal",
        protocol="signal/v1",
        method="signal/wait",
        params={'signal_name': 'test_signal', 'timeout': 30}
    )
    
    result = await handler.execute(task)
    
    assert result.status == TaskStatus.WAITING, f"Expected WAITING, got {result.status}"
    assert result.metadata['signal_type'] == 'wait', "Wrong signal type"
    assert result.metadata['signal_name'] == 'test_signal', "Wrong signal name"
    
    print("✓ Signal wait configured for 'test_signal'")
    
    # Test wait_any
    task2 = Task(
        id="test-signal-2",
        name="Signal Wait Any Test",
        workflow_id="test-workflow",
        task_type="signal",
        protocol="signal/v1",
        method="signal/wait_any",
        params={'signal_names': ['sig1', 'sig2', 'sig3']}
    )
    
    result2 = await handler.execute(task2)
    
    assert result2.status == TaskStatus.WAITING, f"Expected WAITING, got {result2.status}"
    assert result2.metadata['signal_type'] == 'wait_any', "Wrong signal type"
    assert len(result2.metadata['signal_names']) == 3, "Wrong number of signals"
    
    print("✓ Signal wait_any configured for 3 signals")
    
    # Test wait_all
    task3 = Task(
        id="test-signal-3",
        name="Signal Wait All Test",
        workflow_id="test-workflow",
        task_type="signal",
        protocol="signal/v1",
        method="signal/wait_all",
        params={'signal_names': ['ready', 'set', 'go'], 'timeout': 60}
    )
    
    result3 = await handler.execute(task3)
    
    assert result3.status == TaskStatus.WAITING, f"Expected WAITING, got {result3.status}"
    assert result3.metadata['signal_type'] == 'wait_all', "Wrong signal type"
    assert result3.metadata['pending_signals'] == ['ready', 'set', 'go'], "Wrong pending signals"
    assert result3.metadata['received_signals'] == [], "Should start with no received signals"
    
    print("✓ Signal wait_all configured for 3 signals")


async def test_error_handling():
    """Test error handling in handlers"""
    print("\n=== Testing Error Handling ===")
    
    # Test Python handler with invalid code
    handler_class = HandlerRegistry.get_handler('python/v1')
    handler = handler_class(config={})
    
    task = Task(
        id="test-error-1",
        name="Python Error Test",
        workflow_id="test-workflow",
        task_type="python",
        protocol="python/v1",
        method="python/execute",
        params={'code': 'invalid syntax !@#'}
    )
    
    result = await handler.execute(task)
    assert result.status == TaskStatus.FAILED, "Invalid Python should fail"
    print("✓ Python handler properly handles syntax errors")
    
    # Test Timer handler with invalid duration
    timer_handler_class = HandlerRegistry.get_handler('timer/v1')
    timer_handler = timer_handler_class(config={'max_duration': 10})
    
    try:
        task2 = Task(
            id="test-error-2",
            name="Timer Error Test",
            workflow_id="test-workflow",
            task_type="timer",
            protocol="timer/v1",
            method="timer/sleep",
            params={'duration': -5}  # Negative duration
        )
        
        await timer_handler.execute(task2)
        assert False, "Should have raised error for negative duration"
    except GleitzeitError as e:
        assert e.code == ErrorCode.TASK_PARAMETER_ERROR
        print("✓ Timer handler validates duration correctly")
    
    # Test Signal handler with empty signal list
    signal_handler_class = HandlerRegistry.get_handler('signal/v1')
    signal_handler = signal_handler_class(config={})
    
    try:
        task3 = Task(
            id="test-error-3",
            name="Signal Error Test",
            workflow_id="test-workflow",
            task_type="signal",
            protocol="signal/v1",
            method="signal/wait_any",
            params={'signal_names': []}  # Empty list
        )
        
        await signal_handler.execute(task3)
        assert False, "Should have raised error for empty signal list"
    except GleitzeitError as e:
        assert e.code == ErrorCode.TASK_PARAMETER_ERROR
        print("✓ Signal handler validates signal list correctly")


async def test_metrics():
    """Test metrics collection"""
    print("\n=== Testing Metrics ===")
    
    # Create handler with metrics
    from gleitzeit.handlers.metrics import HandlerMetrics
    
    handler_class = HandlerRegistry.get_handler('python/v1')
    handler = handler_class(config={})
    handler.metrics = HandlerMetrics('python/v1')
    
    # Execute some tasks
    for i in range(5):
        task = Task(
            id=f"test-metrics-{i}",
            name=f"Metrics Test {i}",
            workflow_id="test-workflow",
            task_type="python",
            protocol="python/v1",
            method="python/eval",
            params={'expression': f'{i} + {i}'}
        )
        await handler.execute(task)
    
    # Get metrics
    stats = handler.metrics.get_stats()
    
    assert stats['processed'] == 5, f"Expected 5 processed, got {stats['processed']}"
    assert stats['succeeded'] == 5, f"Expected 5 succeeded, got {stats['succeeded']}"
    assert stats['failed'] == 0, f"Expected 0 failed, got {stats['failed']}"
    
    print(f"✓ Metrics collected: {stats['processed']} tasks, {stats['error_rate']} error rate")


async def main():
    """Run all tests"""
    print("\n" + "="*50)
    print("     HANDLER SYSTEM TEST SUITE")
    print("="*50)
    
    try:
        await test_handler_discovery()
        await test_handler_registry()
        await test_python_handler()
        await test_timer_handler()
        await test_signal_handler()
        await test_error_handling()
        await test_metrics()
        
        print("\n" + "="*50)
        print("     ✅ ALL TESTS PASSED")
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
