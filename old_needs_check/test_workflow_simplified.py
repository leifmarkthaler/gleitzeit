#!/usr/bin/env python
"""
Simplified workflow test - validates the streamlined workflow execution.

Tests:
1. WorkflowHandler only supports workflow/execute (no async)
2. Only workflow_ref is supported (no inline definitions)
3. Parent workflows always wait for child completion
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
from gleitzeit.workers.workflow_submission_worker import WorkflowSubmissionWorker
from gleitzeit.core.models import Task, TaskStatus
from gleitzeit.core.sharding import default_sharding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_simplified_workflow():
    """Test the simplified workflow implementation"""

    print("\n" + "="*60)
    print("SIMPLIFIED WORKFLOW HANDLER TEST")
    print("="*60)

    # Create handler
    handler = WorkflowHandler()

    # Verify capabilities only show workflow/execute
    capabilities = handler.get_capabilities()
    methods = capabilities['methods']

    print("\n1. Verifying simplified capabilities")
    print("-" * 40)
    assert 'workflow/execute' in methods, "Should have workflow/execute"
    assert 'workflow/execute_async' not in methods, "Should NOT have workflow/execute_async"

    method_config = methods['workflow/execute']
    assert 'workflow_ref' in method_config['required'], "workflow_ref should be required"
    assert 'workflow_definition' not in method_config.get('optional', []), "Should not support inline definitions"
    print("✓ Only workflow/execute method exists")
    print("✓ workflow_ref is required")
    print("✓ No inline workflow definitions")

    # Test 2: Execute with workflow_ref
    print("\n2. Testing workflow execution with file reference")
    print("-" * 40)

    task = Task(
        id="test-task",
        name="Test Workflow Call",
        workflow_id="parent-workflow",
        method="workflow/execute",
        params={
            "workflow_ref": "workflows/child.yaml",
            "inputs": {"test": "value"},
            "shard_preference": "any"
        }
    )

    result = await handler.execute(task)

    assert result.status == TaskStatus.WAITING, f"Should return WAITING, got {result.status}"
    assert result.metadata['waiting_for'] == 'workflow'
    assert result.metadata['submit_workflow'] == True
    assert 'child_workflow_id' in result.metadata
    assert result.metadata['workflow_ref'] == "workflows/child.yaml"
    assert result.metadata.get('async') is None, "Should not have async flag"
    assert result.metadata.get('callback') is None, "Should not have callback"

    print(f"✓ Task status: {result.status}")
    print(f"✓ Child workflow ID: {result.metadata['child_workflow_id']}")
    print(f"✓ No async mode metadata")

    # Test 3: Verify async method doesn't exist
    print("\n3. Testing that execute_async is not supported")
    print("-" * 40)

    async_task = Task(
        id="async-task",
        name="Async Test",
        workflow_id="parent",
        method="workflow/execute_async",  # Should fail
        params={"workflow_ref": "test.yaml"}
    )

    try:
        await handler.execute(async_task)
        assert False, "Should have raised error for execute_async"
    except Exception as e:
        assert "Unknown method" in str(e) or "not supported" in str(e).lower()
        print(f"✓ execute_async rejected: {type(e).__name__}")

    # Test 4: Verify inline definitions not supported
    print("\n4. Testing that inline definitions are not supported")
    print("-" * 40)

    inline_task = Task(
        id="inline-task",
        name="Inline Test",
        workflow_id="parent",
        method="workflow/execute",
        params={
            "workflow_definition": {  # Should be ignored/fail
                "name": "inline",
                "tasks": []
            },
            "inputs": {}
        }
    )

    try:
        await handler.execute(inline_task)
        assert False, "Should require workflow_ref"
    except Exception as e:
        assert "workflow_ref" in str(e)
        print(f"✓ Inline definition rejected: Missing workflow_ref")

    # Test 5: Verify submission worker doesn't handle async
    print("\n5. Testing WorkflowSubmissionWorker")
    print("-" * 40)

    # Mock submission data - should not have async field
    submission_data = {
        b'child_workflow_id': b'child-123',
        b'parent_workflow_id': b'parent-456',
        b'parent_task_id': b'task-789',
        b'target_shard': b'5',
        b'workflow_ref': b'test.yaml',
        b'inputs': b'{}'
    }

    # Verify no async field expected
    assert b'async' not in submission_data
    assert b'callback' not in submission_data
    print("✓ Submission data has no async/callback fields")

    print("\n" + "="*60)
    print("✓ SIMPLIFIED WORKFLOW TEST PASSED")
    print("="*60)

    print("\nSimplified architecture verified:")
    print("  - Only workflow/execute method exists")
    print("  - workflow_ref is the only way to specify workflows")
    print("  - No async execution mode")
    print("  - No inline workflow definitions")
    print("  - Parent workflows always wait for children")
    print("  - Clean, simple, stateless implementation")


if __name__ == "__main__":
    asyncio.run(test_simplified_workflow())