#!/usr/bin/env python
"""Test method validation at workflow submission time."""

import asyncio
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task

async def test_method_validation():
    """Test that invalid methods fail at submission with protocol error."""
    
    # Create client using new factory pattern with auto-detection
    # This will use API mode since we're not running in-process
    client = await GleitzeitClient.create(mode="api", api_port=8080)
    
    print("Testing method validation...")
    
    # Test 1: Invalid method should fail at submission
    workflow = Workflow(
        id="test-invalid-method",
        name="Invalid Method Test",
        tasks=[
            Task(
                id="invalid-task",
                name="Test Invalid Method",
                protocol="llm/v1",
                method="ollama/generate",  # This should fail - not supported by llm/v1
                params={
                    "model": "llama3.2:latest",
                    "prompt": "Test"
                },
                dependencies=[]
            )
        ]
    )
    
    try:
        result = await client.submit_workflow(workflow)
        print("❌ ERROR: Invalid method was accepted! This should have failed.")
        print(f"Result: {result}")
    except Exception as e:
        print("✅ SUCCESS: Invalid method correctly rejected at submission!")
        print(f"Error: {e}")
        if "not supported" in str(e).lower() and "ollama/generate" in str(e):
            print("✅ Proper protocol error message received")
        else:
            print(f"⚠️ Unexpected error message: {e}")
    
    # Test 2: Valid method should work
    print("\nTesting valid method...")
    workflow2 = Workflow(
        id="test-valid-method",
        name="Valid Method Test",
        tasks=[
            Task(
                id="valid-task",
                name="Test Valid Method",
                protocol="llm/v1",
                method="llm/generate",  # This should work
                params={
                    "model": "llama3.2:latest",
                    "prompt": "Test"
                },
                dependencies=[]
            )
        ]
    )
    
    try:
        result = await client.submit_workflow(workflow2)
        print("✅ SUCCESS: Valid method accepted!")
        print(f"Workflow ID: {result}")
    except Exception as e:
        print(f"⚠️ Valid method failed (might be expected if Ollama not running): {e}")

if __name__ == "__main__":
    asyncio.run(test_method_validation())