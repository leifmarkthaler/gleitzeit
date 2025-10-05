#!/usr/bin/env python3
"""
Test script for Easy Client enhancements.
Tests validation, DAG patterns, and error messages.
"""

import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.easy import t, w


async def test_validation():
    """Test runtime validation framework."""
    print("\n" + "="*60)
    print("TEST 1: Runtime Validation Framework")
    print("="*60)

    # Test valid task with validation
    print("\n1. Creating task with validation rules...")
    task = t("greet", "python/v1:execute")
    task = task.require('code')
    task = task.expect_types(code=str)
    task = task.with_(code="print('Hello from validated task!')")
    task = task.validate()

    print("   ✅ Validation passed!")

    # Test missing required parameter
    print("\n2. Testing missing required parameter...")
    try:
        bad_task = t("bad", "python/v1:execute")
        bad_task = bad_task.require('code')
        bad_task = bad_task.validate()  # Should fail - no code provided
        print("   ❌ Should have failed!")
    except Exception as e:
        print(f"   ✅ Caught error: {e.__class__.__name__}")
        print(f"      Message: {str(e)[:80]}...")


async def test_dag_patterns():
    """Test DAG pattern helpers."""
    print("\n" + "="*60)
    print("TEST 2: DAG Pattern Helpers")
    print("="*60)

    # Test pipeline pattern
    print("\n1. Testing pipeline pattern...")
    workflow = w(
        t("step1", "python/v1:execute").with_(code="print('Step 1')")
    ).sequential(
        t("step2", "python/v1:execute").with_(code="print('Step 2')"),
        t("step3", "python/v1:execute").with_(code="print('Step 3')")
    )

    print("   ✅ Pipeline created")
    print("\n   Workflow structure:")
    workflow.print_dag()

    # Test fan-out pattern
    print("\n2. Testing fan-out pattern...")
    workflow2 = w(
        t("source", "python/v1:execute").with_(code="print('Source')")
    ).fan_out("source",
        t("consumer1", "python/v1:execute").with_(code="print('Consumer 1')"),
        t("consumer2", "python/v1:execute").with_(code="print('Consumer 2')"),
        t("consumer3", "python/v1:execute").with_(code="print('Consumer 3')")
    )

    print("   ✅ Fan-out created")
    print("\n   Workflow structure:")
    workflow2.print_dag()


async def test_error_messages():
    """Test enhanced error messages."""
    print("\n" + "="*60)
    print("TEST 3: Enhanced Error Messages")
    print("="*60)

    # Test protocol typo
    print("\n1. Testing protocol typo detection...")
    try:
        task = t("bad", "pyton/v1:execute")  # Typo: pyton instead of python
    except Exception as e:
        print(f"   ✅ Caught error: {e.__class__.__name__}")
        if hasattr(e, 'data') and 'suggestions' in e.data:
            print(f"      Suggestions: {e.data['suggestions']}")

    # Test parameter validation error
    print("\n2. Testing type validation...")
    try:
        task = t("bad", "python/v1:execute")
        task = task.expect_types(code=str)
        task = task.with_(code=123)  # Wrong type
        task = task.validate()
    except Exception as e:
        print(f"   ✅ Caught error: {e.__class__.__name__}")
        print(f"      Message: {str(e)[:80]}...")


async def test_simple_workflow():
    """Test a simple workflow execution."""
    print("\n" + "="*60)
    print("TEST 4: Simple Workflow Execution")
    print("="*60)

    print("\n1. Creating workflow with validation...")

    # Create a simple workflow
    workflow = w(
        t("hello", "python/v1:execute")
            .require('code')
            .expect_types(code=str)
            .with_(code="print('Hello from Easy Client!')")
            .validate()
    ).name("test_workflow")

    print("   ✅ Workflow created and validated")

    print("\n2. Workflow structure:")
    workflow.print_dag()

    print("\n3. Converting to dict format...")
    workflow_dict = workflow.to_dict()
    print(f"   ✅ Workflow dict created")
    print(f"      Workflow ID: {workflow_dict.get('workflow_id')}")
    print(f"      Tasks: {len(workflow_dict['workflow']['tasks'])}")

    # Submit workflow
    print("\n4. Submitting workflow...")
    try:
        response = workflow.submit()
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        print(f"      Status: {response.get('status')}")
    except Exception as e:
        print(f"   ⚠️  Submission error: {e}")
        print(f"      (This is expected if API is not running)")


async def test_complex_workflow():
    """Test a more complex workflow with patterns."""
    print("\n" + "="*60)
    print("TEST 5: Complex Workflow with Patterns")
    print("="*60)

    print("\n1. Creating complex workflow...")

    # Diamond pattern workflow
    workflow = w(
        t("fetch", "python/v1:execute")
            .require('code')
            .with_(code="data = {'status': 'fetched'}")
    ).diamond("fetch",
        t("process1", "python/v1:execute")
            .with_(code="print('Processing path 1')"),
        t("process2", "python/v1:execute")
            .with_(code="print('Processing path 2')"),
        aggregator=t("merge", "python/v1:execute")
            .with_(code="print('Merging results')")
    )

    print("   ✅ Diamond pattern workflow created")

    print("\n2. Workflow DAG:")
    workflow.print_dag()

    print("\n3. Workflow statistics:")
    print(f"      Total tasks: {workflow.get_task_count()}")
    print(f"      Task IDs: {', '.join(workflow.get_task_ids())}")


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("EASY CLIENT ENHANCEMENTS TEST SUITE")
    print("="*60)

    try:
        await test_validation()
        await test_dag_patterns()
        await test_error_messages()
        await test_simple_workflow()
        await test_complex_workflow()

        print("\n" + "="*60)
        print("ALL TESTS COMPLETED")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
