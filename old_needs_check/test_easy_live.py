#!/usr/bin/env python3
"""
Test Easy Client enhancements with live Gleitzeit system.
Submits actual workflows to the running API.
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.easy import t, w


def test_simple_workflow():
    """Test a simple validated workflow."""
    print("\n" + "="*60)
    print("TEST 1: Simple Validated Workflow")
    print("="*60)

    # Create workflow with validation
    print("\n1. Creating workflow with validation...")
    workflow = w(
        t("greet", "python/v1:execute")
            .require('code')
            .expect_types(code=str)
            .with_(code="print('Hello from validated Easy Client!')")
            .validate()
    ).name("simple_validated_workflow")

    print("   ✅ Workflow created and validated")
    print("\n   Workflow structure:")
    workflow.print_dag()

    # Submit
    print("\n2. Submitting to Gleitzeit...")
    try:
        response = workflow.submit(api_url="http://localhost:8000")
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        print(f"      Status: {response.get('status')}")
        return response.get('workflow_id')
    except Exception as e:
        print(f"   ❌ Submission failed: {e}")
        return None


def test_fan_out_workflow():
    """Test fan-out pattern workflow."""
    print("\n" + "="*60)
    print("TEST 2: Fan-Out Pattern Workflow")
    print("="*60)

    print("\n1. Creating fan-out workflow...")
    workflow = w(
        t("source", "python/v1:execute")
            .require('code')
            .with_(code="print('Source task'); result = 'data'")
    ).fan_out("source",
        t("worker1", "python/v1:execute")
            .with_(code="print('Worker 1 processing')"),
        t("worker2", "python/v1:execute")
            .with_(code="print('Worker 2 processing')"),
        t("worker3", "python/v1:execute")
            .with_(code="print('Worker 3 processing')")
    ).name("fan_out_workflow")

    print("   ✅ Fan-out workflow created")
    print("\n   Workflow structure:")
    workflow.print_dag()

    print("\n2. Submitting to Gleitzeit...")
    try:
        response = workflow.submit(api_url="http://localhost:8000")
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        print(f"      Status: {response.get('status')}")
        return response.get('workflow_id')
    except Exception as e:
        print(f"   ❌ Submission failed: {e}")
        return None


def test_diamond_workflow():
    """Test diamond pattern workflow."""
    print("\n" + "="*60)
    print("TEST 3: Diamond Pattern Workflow")
    print("="*60)

    print("\n1. Creating diamond workflow...")
    workflow = w(
        t("fetch", "python/v1:execute")
            .require('code')
            .expect_types(code=str)
            .with_(code="print('Fetching data'); data = [1, 2, 3, 4, 5]")
            .validate()
    ).diamond("fetch",
        t("process1", "python/v1:execute")
            .with_(code="print('Processing path 1')"),
        t("process2", "python/v1:execute")
            .with_(code="print('Processing path 2')"),
        aggregator=t("merge", "python/v1:execute")
            .require('code')
            .with_(code="print('Merging results')")
    ).name("diamond_workflow")

    print("   ✅ Diamond workflow created")
    print("\n   Workflow structure:")
    workflow.print_dag()

    print("\n2. Submitting to Gleitzeit...")
    try:
        response = workflow.submit(api_url="http://localhost:8000")
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        print(f"      Status: {response.get('status')}")
        return response.get('workflow_id')
    except Exception as e:
        print(f"   ❌ Submission failed: {e}")
        return None


def test_pipeline_workflow():
    """Test sequential pipeline workflow."""
    print("\n" + "="*60)
    print("TEST 4: Sequential Pipeline Workflow")
    print("="*60)

    print("\n1. Creating pipeline workflow...")
    workflow = w(
        t("step1", "python/v1:execute")
            .require('code')
            .with_(code="print('Step 1: Initialize'); counter = 1")
    ).sequential(
        t("step2", "python/v1:execute")
            .with_(code="print('Step 2: Process'); counter = 2"),
        t("step3", "python/v1:execute")
            .with_(code="print('Step 3: Finalize'); counter = 3")
    ).name("pipeline_workflow")

    print("   ✅ Pipeline workflow created")
    print("\n   Workflow structure:")
    workflow.print_dag()

    print("\n2. Submitting to Gleitzeit...")
    try:
        response = workflow.submit(api_url="http://localhost:8000")
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        print(f"      Status: {response.get('status')}")
        return response.get('workflow_id')
    except Exception as e:
        print(f"   ❌ Submission failed: {e}")
        return None


def main():
    """Run all live tests."""
    print("\n" + "="*60)
    print("EASY CLIENT LIVE SYSTEM TEST")
    print("Testing against: http://localhost:8000")
    print("="*60)

    workflow_ids = []

    # Run tests
    wf1 = test_simple_workflow()
    if wf1:
        workflow_ids.append(('simple', wf1))

    time.sleep(1)

    wf2 = test_fan_out_workflow()
    if wf2:
        workflow_ids.append(('fan-out', wf2))

    time.sleep(1)

    wf3 = test_diamond_workflow()
    if wf3:
        workflow_ids.append(('diamond', wf3))

    time.sleep(1)

    wf4 = test_pipeline_workflow()
    if wf4:
        workflow_ids.append(('pipeline', wf4))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"\nSubmitted {len(workflow_ids)} workflows:")
    for name, wf_id in workflow_ids:
        print(f"  - {name}: {wf_id}")

    if workflow_ids:
        print("\n✅ All workflows submitted successfully!")
        print("\nYou can check their status with:")
        print("  gleitzeit ps")
        print("\nOr view logs:")
        print("  gleitzeit logs")
    else:
        print("\n⚠️ No workflows were submitted")
        print("Make sure Gleitzeit is running: gleitzeit serve")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
