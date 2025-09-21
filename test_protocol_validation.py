#!/usr/bin/env python
"""Test protocol validation through workflow submission"""

import asyncio
from gleitzeit.client import GleitzeitClient

async def test_protocol_validation():
    """Test that protocol validation works correctly"""
    client = await GleitzeitClient.create(mode="api", api_url="http://localhost:8000")
    
    print("=" * 60)
    print("Testing Protocol Validation")
    print("=" * 60)
    
    # Test 1: Valid workflow with correct protocol and method
    print("\n1. Valid workflow with python/execute")
    try:
        result = await client.submit_workflow({
            "name": "Valid Python workflow",
            "tasks": [{
                "name": "python_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "print('Hello from valid task')"
                }
            }]
        })
        print(f"✓ Valid workflow submitted: {result.get('workflow_id')}")
    except Exception as e:
        print(f"✗ Valid workflow failed: {e}")
    
    # Test 2: Invalid method format (missing namespace)
    print("\n2. Invalid method format (missing namespace)")
    try:
        result = await client.submit_workflow({
            "name": "Invalid method format workflow",
            "tasks": [{
                "name": "invalid_method",
                "protocol": "python/v1",
                "method": "execute",  # Missing namespace
                "params": {
                    "code": "print('This should fail')"
                }
            }]
        })
        print(f"✗ Invalid method was accepted (should have failed): {result.get('workflow_id')}")
    except Exception as e:
        print(f"✓ Invalid method format rejected: {e}")
    
    # Test 3: Mismatched protocol and method namespace
    print("\n3. Mismatched protocol and method namespace")
    try:
        result = await client.submit_workflow({
            "name": "Mismatched namespace workflow",
            "tasks": [{
                "name": "mismatched",
                "protocol": "python/v1",
                "method": "llm/chat",  # Wrong namespace for python protocol
                "params": {
                    "prompt": "This should fail"
                }
            }]
        })
        print(f"✗ Mismatched namespace accepted (should have failed): {result.get('workflow_id')}")
    except Exception as e:
        print(f"✓ Mismatched namespace rejected: {e}")
    
    # Test 4: Protocol inferred from method
    print("\n4. Protocol inferred from method")
    try:
        result = await client.submit_workflow({
            "name": "Inferred protocol workflow",
            "tasks": [{
                "name": "inferred",
                "method": "python/execute",  # Protocol should be inferred as python/v1
                "params": {
                    "code": "print('Protocol inferred')"
                }
            }]
        })
        print(f"✓ Protocol inferred successfully: {result.get('workflow_id')}")
    except Exception as e:
        print(f"Note: Protocol inference result: {e}")
    
    # Test 5: Valid LLM workflow
    print("\n5. Valid LLM workflow")
    try:
        result = await client.submit_workflow({
            "name": "Valid LLM workflow",
            "tasks": [{
                "name": "llm_task",
                "protocol": "llm/v1",
                "method": "llm/chat",
                "params": {
                    "prompt": "Say hello"
                }
            }]
        })
        print(f"✓ Valid LLM workflow submitted: {result.get('workflow_id')}")
    except Exception as e:
        print(f"✗ Valid LLM workflow failed: {e}")
    
    # Test 6: Shell protocol validation
    print("\n6. Shell protocol validation")
    try:
        result = await client.submit_workflow({
            "name": "Shell workflow",
            "tasks": [{
                "name": "shell_task",
                "protocol": "shell/v1",
                "method": "shell/exec",
                "params": {
                    "command": "echo 'Hello from shell'"
                }
            }]
        })
        print(f"✓ Shell workflow submitted: {result.get('workflow_id')}")
    except Exception as e:
        print(f"✗ Shell workflow failed: {e}")
    
    # Test 7: Missing protocol and method
    print("\n7. Missing protocol and method")
    try:
        result = await client.submit_workflow({
            "name": "Missing protocol/method workflow",
            "tasks": [{
                "name": "incomplete_task",
                "params": {
                    "code": "print('No protocol or method')"
                }
            }]
        })
        print(f"✗ Incomplete task accepted (should have failed): {result.get('workflow_id')}")
    except Exception as e:
        print(f"✓ Missing protocol/method rejected: {e}")
    
    # Test 8: Unknown protocol (but valid format)
    print("\n8. Unknown protocol with valid format")
    try:
        result = await client.submit_workflow({
            "name": "Unknown protocol workflow",
            "tasks": [{
                "name": "custom_task",
                "protocol": "custom/v1",
                "method": "custom/action",
                "params": {
                    "data": "Custom protocol data"
                }
            }]
        })
        print(f"Note: Unknown protocol result: {result.get('workflow_id') if result.get('success') else result.get('error')}")
    except Exception as e:
        print(f"Unknown protocol handling: {e}")

    print("\n" + "=" * 60)
    print("Protocol Validation Tests Complete")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_protocol_validation())