#!/usr/bin/env python3
"""
Test REAL handler execution with actual results.

No mocks - actually execute Python code and verify results.
"""

import asyncio
import json
from datetime import datetime

from gleitzeit.handlers import handler_loader, HandlerRegistry
from gleitzeit.core.models import Task, TaskStatus

# Trigger handler loading
_ = handler_loader.get_all_capabilities()


async def test_python_handler_real_execution():
    """Test that PythonHandler actually executes code and returns results"""
    print("\n=== Testing REAL Python Code Execution ===")
    
    # Get the actual PythonHandler
    handler_class = HandlerRegistry.get_handler('python/v1')
    assert handler_class is not None, "PythonHandler not found"
    
    handler = handler_class(config={'default_timeout': 10})
    
    # Test 1: Simple arithmetic
    print("\n1. Testing arithmetic (2 + 3)...")
    task = Task(
        id="test-1",
        name="Add Numbers",
        workflow_id="wf-test",
        protocol="python/v1",
        method="python/eval",
        params={'expression': '2 + 3'}
    )
    
    result = await handler.execute(task)
    
    assert result.status == TaskStatus.COMPLETED, f"Expected COMPLETED, got {result.status}"
    assert result.result == 5, f"Expected 5, got {result.result}"
    print(f"   ✓ Result: {result.result} (correct!)")
    
    # Test 2: More complex expression
    print("\n2. Testing complex expression...")
    task2 = Task(
        id="test-2",
        name="Complex Math",
        workflow_id="wf-test",
        protocol="python/v1",
        method="python/eval",
        params={'expression': 'sum([i**2 for i in range(1, 6)])'}
    )
    
    result2 = await handler.execute(task2)
    
    expected = 1 + 4 + 9 + 16 + 25  # 55
    assert result2.status == TaskStatus.COMPLETED
    assert result2.result == expected, f"Expected {expected}, got {result2.result}"
    print(f"   ✓ Result: {result2.result} (sum of squares 1-5)")
    
    # Test 3: Execute code block with result
    print("\n3. Testing code execution...")
    task3 = Task(
        id="test-3",
        name="Execute Code",
        workflow_id="wf-test",
        protocol="python/v1",
        method="python/execute",
        params={
            'code': '''
# Calculate factorial
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

result = factorial(5)
'''
        }
    )
    
    result3 = await handler.execute(task3)
    
    assert result3.status == TaskStatus.COMPLETED
    assert result3.result == 120, f"Expected 120 (5!), got {result3.result}"
    print(f"   ✓ Result: {result3.result} (factorial of 5)")
    
    # Test 4: Execute with inputs
    print("\n4. Testing execution with inputs...")
    task4 = Task(
        id="test-4",
        name="Use Inputs",
        workflow_id="wf-test",
        protocol="python/v1",
        method="python/execute",
        params={
            'code': 'result = inputs["a"] * inputs["b"] + inputs["c"]',
            'inputs': {'a': 7, 'b': 6, 'c': 8}  # 7*6+8 = 50
        }
    )
    
    result4 = await handler.execute(task4)
    
    assert result4.status == TaskStatus.COMPLETED
    assert result4.result == 50, f"Expected 50, got {result4.result}"
    print(f"   ✓ Result: {result4.result} (7*6+8)")
    
    return True


async def test_timer_handler_real_execution():
    """Test that TimerHandler returns proper scheduling info"""
    print("\n=== Testing REAL Timer Handler ===")
    
    handler_class = HandlerRegistry.get_handler('timer/v1')
    handler = handler_class(config={})
    
    # Test sleep task
    print("\n1. Testing sleep task (5 seconds)...")
    task = Task(
        id="timer-1",
        name="Sleep Task",
        workflow_id="wf-test",
        protocol="timer/v1",
        method="timer/sleep",
        params={'duration': 5}
    )
    
    import time
    start = time.time()
    result = await handler.execute(task)
    
    assert result.status == TaskStatus.SCHEDULED, f"Expected SCHEDULED, got {result.status}"
    assert 'wake_time' in result.metadata, "Missing wake_time"
    
    wake_time = result.metadata['wake_time']
    expected_wake = start + 5
    
    # Should be approximately 5 seconds in the future
    diff = abs(wake_time - expected_wake)
    assert diff < 0.1, f"Wake time off by {diff} seconds"
    
    print(f"   ✓ Scheduled to wake at {wake_time:.2f} ({5} seconds from now)")
    print(f"   ✓ Status: {result.status}")
    
    # Test zero duration (immediate completion)
    print("\n2. Testing zero duration...")
    task2 = Task(
        id="timer-2",
        name="No Wait",
        workflow_id="wf-test",
        protocol="timer/v1",
        method="timer/sleep",
        params={'duration': 0}
    )
    
    result2 = await handler.execute(task2)
    
    assert result2.status == TaskStatus.COMPLETED, f"Expected COMPLETED for zero duration"
    print(f"   ✓ Zero duration completed immediately")
    
    return True


async def test_signal_handler_real_execution():
    """Test that SignalHandler returns proper waiting info"""
    print("\n=== Testing REAL Signal Handler ===")
    
    handler_class = HandlerRegistry.get_handler('signal/v1')
    handler = handler_class(config={})
    
    print("\n1. Testing signal wait...")
    task = Task(
        id="signal-1",
        name="Wait for Signal",
        workflow_id="wf-test",
        protocol="signal/v1",
        method="signal/wait",
        params={'signal_name': 'user_approval', 'timeout': 300}
    )
    
    result = await handler.execute(task)
    
    assert result.status == TaskStatus.WAITING, f"Expected WAITING, got {result.status}"
    assert result.metadata['signal_name'] == 'user_approval'
    assert result.metadata['timeout'] == 300
    
    print(f"   ✓ Status: {result.status}")
    print(f"   ✓ Waiting for: {result.metadata['signal_name']}")
    print(f"   ✓ Timeout: {result.metadata['timeout']}s")
    
    return True


async def test_execution_errors():
    """Test that handlers properly handle errors"""
    print("\n=== Testing Error Handling ===")
    
    handler_class = HandlerRegistry.get_handler('python/v1')
    handler = handler_class(config={})
    
    # Test syntax error
    print("\n1. Testing syntax error...")
    task = Task(
        id="error-1",
        name="Bad Code",
        workflow_id="wf-test",
        protocol="python/v1",
        method="python/execute",
        params={'code': 'this is not valid python !!!'}
    )
    
    result = await handler.execute(task)
    
    assert result.status == TaskStatus.FAILED, "Should have failed"
    assert result.error is not None, "Should have error message"
    print(f"   ✓ Failed as expected: {result.error[:50]}...")
    
    # Test runtime error
    print("\n2. Testing runtime error...")
    task2 = Task(
        id="error-2",
        name="Division by Zero",
        workflow_id="wf-test",
        protocol="python/v1",
        method="python/eval",
        params={'expression': '1/0'}
    )
    
    result2 = await handler.execute(task2)
    
    assert result2.status == TaskStatus.FAILED
    assert 'division' in result2.error.lower() or 'zero' in result2.error.lower()
    print(f"   ✓ Failed as expected: {result2.error[:50]}...")
    
    return True


async def main():
    """Run all real execution tests"""
    print("\n" + "="*60)
    print("   REAL HANDLER EXECUTION TESTS")
    print("   (No mocks - actual code execution!)")
    print("="*60)
    
    try:
        await test_python_handler_real_execution()
        await test_timer_handler_real_execution()
        await test_signal_handler_real_execution()
        await test_execution_errors()
        
        print("\n" + "="*60)
        print("     ✅ ALL REAL EXECUTION TESTS PASSED")
        print("="*60 + "\n")
        
        print("\nVerified:")
        print("✓ Python handler executes real code and returns real results")
        print("✓ Complex expressions and functions work correctly")
        print("✓ Timer handler calculates actual wake times")
        print("✓ Signal handler sets up proper waiting state")
        print("✓ Errors are properly caught and reported")
        print("\nThe handlers are ACTUALLY WORKING!")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
