#!/usr/bin/env python
"""Test task validation through workflow loader"""

import asyncio
from gleitzeit.client import GleitzeitClient

async def test_task_validation():
    """Test that tasks are properly validated"""
    client = GleitzeitClient()
    
    # Test 1: Valid task with correct protocol and method
    print("Test 1: Valid task with python/execute")
    try:
        task = await client.submit_task({
            "name": "valid_task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "code": "print('Hello from valid task')"
            }
        })
        print(f"✓ Valid task submitted: {task['id']}")
    except Exception as e:
        print(f"✗ Valid task failed: {e}")
    
    # Test 2: Invalid method format (missing namespace)
    print("\nTest 2: Invalid method format (missing namespace)")
    try:
        task = await client.submit_task(
            name="invalid_method_format",
            protocol="python/v1",
            method="execute",  # Missing namespace
            params={
                "code": "print('This should fail')"
            }
        )
        print(f"✗ Invalid task was accepted (should have failed): {task['id']}")
    except Exception as e:
        print(f"✓ Invalid method format rejected: {e}")
    
    # Test 3: Mismatched protocol and method namespace
    print("\nTest 3: Mismatched protocol and method namespace")
    try:
        task = await client.submit_task(
            name="mismatched_namespace",
            protocol="python/v1",
            method="llm/chat",  # Wrong namespace for python protocol
            params={
                "prompt": "This should fail"
            }
        )
        print(f"✗ Mismatched namespace was accepted (should have failed): {task['id']}")
    except Exception as e:
        print(f"✓ Mismatched namespace rejected: {e}")
    
    # Test 4: Missing protocol
    print("\nTest 4: Missing protocol")
    try:
        task = await client.submit_task(
            name="missing_protocol",
            method="python/execute",
            params={
                "code": "print('No protocol')"
            }
        )
        print(f"✓ Task submitted without explicit protocol (inferred): {task['id']}")
    except Exception as e:
        print(f"Note: Missing protocol handling: {e}")
    
    # Test 5: Valid LLM task
    print("\nTest 5: Valid LLM task")
    try:
        task = await client.submit_task(
            name="valid_llm_task",
            protocol="llm/v1",
            method="llm/chat",
            params={
                "prompt": "Say hello"
            }
        )
        print(f"✓ Valid LLM task submitted: {task['id']}")
    except Exception as e:
        print(f"✗ Valid LLM task failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_task_validation())