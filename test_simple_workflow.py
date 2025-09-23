#!/usr/bin/env python
"""
Simple test to verify WorkflowHandler works correctly.
"""

import asyncio
import json
import sys
from pathlib import Path
import logging

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.handlers.workflow import WorkflowHandler
from gleitzeit.core.models import Task, TaskStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_workflow_handler():
    """Test WorkflowHandler execution"""
    
    print("\n" + "="*60)
    print("WORKFLOW HANDLER SIMPLE TEST")
    print("="*60)
    
    # Create handler
    handler = WorkflowHandler()
    print(f"\n✓ Created WorkflowHandler with ID: {handler.handler_id}")
    
    # Test 1: Workflow execution
    print("\nTest 1: Workflow execution")
    print("-" * 40)
    
    task1 = Task(
        id="test-task-1",
        name="Execute Child Workflow",
        workflow_id="parent-wf-123",
        method="workflow/execute",
        params={
            "workflow_ref": "child.yaml",
            "inputs": {"key": "value", "number": 42},
            "shard_preference": "any",
            "timeout": 300
        }
    )
    
    result1 = await handler.execute(task1)
    
    print(f"Status: {result1.status}")
    print(f"Metadata keys: {list(result1.metadata.keys())}")
    
    # Verify result
    assert result1.status == TaskStatus.WAITING, f"Expected WAITING, got {result1.status}"
    assert result1.metadata['waiting_for'] == 'workflow'
    assert result1.metadata['submit_workflow'] == True
    assert 'child_workflow_id' in result1.metadata
    assert result1.metadata['parent_workflow_id'] == "parent-wf-123"
    assert result1.metadata['workflow_ref'] == "child.yaml"
    
    print(f"\n✓ Test 1 passed!")
    print(f"  Child workflow ID: {result1.metadata['child_workflow_id']}")
    print(f"  Target shard: {result1.metadata['child_shard']}")
    
    # Test 2: Different shard preference
    print("\nTest 2: Different shard preference")
    print("-" * 40)

    task2 = Task(
        id="test-task-2",
        name="Same Shard Child Workflow",
        workflow_id="parent-wf-456",
        method="workflow/execute",
        params={
            "workflow_ref": "background.yaml",
            "inputs": {"job": "cleanup"},
            "shard_preference": "same"
        }
    )

    result2 = await handler.execute(task2)

    print(f"Status: {result2.status}")
    print(f"Metadata keys: {list(result2.metadata.keys())}")

    # Verify result
    assert result2.status == TaskStatus.WAITING, f"Expected WAITING, got {result2.status}"
    assert result2.metadata['waiting_for'] == 'workflow'
    assert 'child_workflow_id' in result2.metadata
    assert result2.metadata['submit_workflow'] == True

    print(f"\n✓ Test 2 passed!")
    print(f"  Child workflow ID: {result2.metadata['child_workflow_id']}")
    
    # Test 3: Workflow with timeout
    print("\nTest 3: Workflow with timeout")
    print("-" * 40)

    task3 = Task(
        id="test-task-3",
        name="Workflow with Timeout",
        workflow_id="parent-wf-789",
        method="workflow/execute",
        params={
            "workflow_ref": "timeout-test.yaml",
            "inputs": {"timeout_test": True},
            "timeout": 60
        }
    )

    result3 = await handler.execute(task3)

    print(f"Status: {result3.status}")

    # Verify result
    assert result3.status == TaskStatus.WAITING
    assert result3.metadata['workflow_ref'] == "timeout-test.yaml"
    assert result3.metadata['timeout'] == 60

    print(f"\n✓ Test 3 passed!")
    
    # Test 4: Shard preferences
    print("\nTest 4: Shard preferences")
    print("-" * 40)

    preferences = ['same', 'any', 'specific:5']
    
    for pref in preferences:
        task = Task(
            id=f"test-task-{pref}",
            name=f"Test {pref}",
            workflow_id="parent-wf-shard",
            method="workflow/execute",
            params={
                "workflow_ref": "test.yaml",
                "shard_preference": pref
            }
        )
        
        result = await handler.execute(task)
        
        print(f"  {pref:15} -> shard {result.metadata['child_shard']}")
        
        if pref == 'same':
            # Should match parent's shard
            from gleitzeit.core.sharding import default_sharding
            parent_shard = default_sharding.get_shard("parent-wf-shard")
            assert result.metadata['child_shard'] == parent_shard
        elif pref == 'specific:5':
            assert result.metadata['child_shard'] == 5
            
    print(f"\n✓ Test 4 passed!")
    
    # Test 5: Error handling
    print("\nTest 5: Error handling")
    print("-" * 40)
    
    # Missing required parameters
    task5 = Task(
        id="test-task-error",
        name="Error Test",
        workflow_id="parent-wf-error",
        method="workflow/execute",
        params={}  # Missing workflow_ref
    )
    
    try:
        result5 = await handler.execute(task5)
        assert False, "Should have raised an error"
    except Exception as e:
        print(f"  Expected error: {type(e).__name__}")
        assert "workflow_ref" in str(e)
        
    print(f"\n✓ Test 5 passed!")
    
    print("\n" + "="*60)
    print("✓ ALL TESTS PASSED!")
    print("="*60)
    print("\nSummary:")
    print("  - WorkflowHandler correctly returns WAITING status")
    print("  - Metadata includes submit_workflow flag")
    print("  - Child workflow IDs are generated properly")
    print("  - Shard preferences work correctly")
    print("  - Workflow references handled properly")
    print("  - Error handling works correctly")
    

if __name__ == "__main__":
    asyncio.run(test_workflow_handler())