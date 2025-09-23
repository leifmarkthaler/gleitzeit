#!/usr/bin/env python3
"""
Test that unsupported task types are properly rejected.
"""

import asyncio
from gleitzeit.workers.workflow_loader_worker_v2 import WorkflowLoaderWorkerV2
from gleitzeit.workers.base import WorkerConfig


async def test_unsupported_types():
    """Test that task types without handlers are rejected"""
    print("\n=== Testing Unsupported Task Types ===")
    
    config = WorkerConfig(
        worker_type="workflow_loader",
        worker_id="test-loader",
        consumer_group="test-group"
    )
    
    loader = WorkflowLoaderWorkerV2(config)
    
    # Show what IS supported
    print(f"Supported task types: {list(loader.type_to_protocol.keys())}")
    print(f"Supported protocols: {list(loader.supported_methods.keys())}")
    
    # Try to create a workflow with unsupported task type
    unsupported_workflow = {
        'name': 'test-unsupported',
        'tasks': [
            {
                'id': 'shell-task',
                'type': 'shell',  # Shell has no handler
                'command': 'echo hello'
            }
        ]
    }
    
    # Transform should work but assign unknown protocol
    transformed = await loader.transform_workflow(unsupported_workflow, 'test-id')
    shell_task = transformed['tasks'][0]
    
    print(f"\nShell task (no handler):")
    print(f"  Protocol: {shell_task.get('protocol', 'NONE')}")
    print(f"  Method: {shell_task.get('method', 'NONE')}")
    
    # Validation should fail
    errors = loader.validate_workflow(transformed)
    
    if errors:
        print(f"\n✓ Validation correctly failed:")
        for error in errors:
            print(f"  - {error}")
    else:
        print(f"\n❌ ERROR: Validation should have failed for unsupported type!")
        return False
    
    # Test with explicit protocol that doesn't exist
    explicit_unknown = {
        'name': 'test-unknown-protocol',
        'tasks': [
            {
                'id': 'unknown-task',
                'protocol': 'unknown/v1',
                'method': 'unknown/execute',
                'params': {}
            }
        ]
    }
    
    errors = loader.validate_workflow(explicit_unknown)
    
    if errors:
        print(f"\n✓ Unknown protocol correctly rejected:")
        for error in errors:
            print(f"  - {error}")
    else:
        print(f"\n❌ ERROR: Should have rejected unknown protocol!")
        return False
    
    return True


async def main():
    print("\n" + "="*50)
    print("   UNSUPPORTED TYPE TEST")
    print("="*50)
    
    success = await test_unsupported_types()
    
    if success:
        print("\n✅ Test passed: Unsupported types are properly rejected")
        return 0
    else:
        print("\n❌ Test failed: Unsupported types not properly handled")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
