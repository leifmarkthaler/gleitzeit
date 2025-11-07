#!/usr/bin/env python3
"""
Test ValidationHandler to verify it's working correctly.
"""

import asyncio
import sys
sys.path.insert(0, 'src')

from gleitzeit.handlers.validation import ValidationHandler
from gleitzeit.core.models import Task, TaskStatus


async def test_basic_evaluation():
    """Test basic condition evaluation"""
    print("\n=== Test 1: Basic Evaluation ===")

    handler = ValidationHandler()

    task = Task(
        id="test-1",
        workflow_id="test-workflow",
        name="test_evaluation",
        method="validation/evaluate",
        params={
            "conditions": [
                "x > 5",
                "y < 10"
            ],
            "mode": "all",
            "context": {
                "x": 10,
                "y": 5
            }
        }
    )

    result = await handler.execute(task)

    print(f"Status: {result.status}")
    print(f"Valid: {result.result.get('valid')}")
    print(f"Summary: {result.result.get('summary')}")
    print(f"Details: {result.result.get('details')}")

    assert result.status == TaskStatus.COMPLETED, f"Expected COMPLETED, got {result.status}"
    assert result.result.get('valid') == True, "Expected valid=True"
    print("✅ PASSED")

    return result


async def test_failed_conditions():
    """Test when conditions fail"""
    print("\n=== Test 2: Failed Conditions ===")

    handler = ValidationHandler()

    task = Task(
        id="test-2",
        workflow_id="test-workflow",
        name="test_failed",
        method="validation/evaluate",
        params={
            "conditions": [
                "x > 100",  # This will fail
                "y < 10"
            ],
            "mode": "all",
            "context": {
                "x": 10,
                "y": 5
            }
        }
    )

    result = await handler.execute(task)

    print(f"Status: {result.status}")
    print(f"Valid: {result.result.get('valid')}")
    print(f"Summary: {result.result.get('summary')}")

    assert result.status == TaskStatus.COMPLETED, f"Expected COMPLETED, got {result.status}"
    assert result.result.get('valid') == False, "Expected valid=False"
    print("✅ PASSED")

    return result


async def test_missing_variable():
    """Test NameNotDefined error handling"""
    print("\n=== Test 3: Missing Variable (NameNotDefined) ===")

    handler = ValidationHandler()

    task = Task(
        id="test-3",
        workflow_id="test-workflow",
        name="test_missing_var",
        method="validation/evaluate",
        params={
            "conditions": [
                "missing_variable > 5"  # Variable not in context
            ],
            "mode": "all",
            "context": {
                "x": 10
            }
        }
    )

    result = await handler.execute(task)

    print(f"Status: {result.status}")
    print(f"Valid: {result.result.get('valid')}")
    print(f"Details: {result.result.get('details')}")

    # Check that it's handled gracefully
    assert result.status == TaskStatus.COMPLETED, f"Expected COMPLETED, got {result.status}"
    assert result.result.get('valid') == False, "Expected valid=False when variable missing"

    details = result.result.get('details', [])
    assert len(details) > 0, "Expected details about the error"
    assert 'error' in details[0], "Expected error in details"
    assert 'not found' in details[0]['error'].lower(), "Expected 'not found' in error message"

    print(f"Error message: {details[0].get('error')}")
    print("✅ PASSED - Missing variable handled gracefully")

    return result


async def test_assertion_pass():
    """Test assertion that passes"""
    print("\n=== Test 4: Assertion (Pass) ===")

    handler = ValidationHandler()

    task = Task(
        id="test-4",
        workflow_id="test-workflow",
        name="test_assertion_pass",
        method="validation/assert",
        params={
            "assertions": [
                "x > 5",
                "y < 10"
            ],
            "context": {
                "x": 10,
                "y": 5
            }
        }
    )

    result = await handler.execute(task)

    print(f"Status: {result.status}")
    print(f"Valid: {result.result.get('valid')}")
    print(f"Assertions passed: {result.result.get('assertions_passed')}")

    assert result.status == TaskStatus.COMPLETED, f"Expected COMPLETED, got {result.status}"
    assert result.result.get('valid') == True, "Expected valid=True"
    print("✅ PASSED")

    return result


async def test_assertion_fail():
    """Test assertion that fails"""
    print("\n=== Test 5: Assertion (Fail) ===")

    handler = ValidationHandler()

    task = Task(
        id="test-5",
        workflow_id="test-workflow",
        name="test_assertion_fail",
        method="validation/assert",
        params={
            "assertions": [
                "x > 100"  # This will fail
            ],
            "context": {
                "x": 10
            }
        }
    )

    result = await handler.execute(task)

    print(f"Status: {result.status}")
    print(f"Error: {result.error}")
    print(f"Valid: {result.result.get('valid')}")

    # Assertions should FAIL the task
    assert result.status == TaskStatus.FAILED, f"Expected FAILED, got {result.status}"
    assert result.result.get('valid') == False, "Expected valid=False"
    assert result.error is not None, "Expected error message"
    print("✅ PASSED - Assertion correctly failed the task")

    return result


async def test_mode_any():
    """Test 'any' mode - only one condition needs to pass"""
    print("\n=== Test 6: Mode 'any' ===")

    handler = ValidationHandler()

    task = Task(
        id="test-6",
        workflow_id="test-workflow",
        name="test_mode_any",
        method="validation/evaluate",
        params={
            "conditions": [
                "x > 100",  # Fails
                "y < 10"    # Passes
            ],
            "mode": "any",
            "context": {
                "x": 10,
                "y": 5
            }
        }
    )

    result = await handler.execute(task)

    print(f"Status: {result.status}")
    print(f"Valid: {result.result.get('valid')}")
    print(f"Summary: {result.result.get('summary')}")

    assert result.status == TaskStatus.COMPLETED, f"Expected COMPLETED, got {result.status}"
    assert result.result.get('valid') == True, "Expected valid=True with 'any' mode"
    print("✅ PASSED")

    return result


async def main():
    """Run all tests"""
    print("=" * 60)
    print("ValidationHandler Test Suite")
    print("=" * 60)

    try:
        await test_basic_evaluation()
        await test_failed_conditions()
        await test_missing_variable()
        await test_assertion_pass()
        await test_assertion_fail()
        await test_mode_any()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
