#!/usr/bin/env python3
"""
Test suite for running various workflow types via the Gleitzeit Python API.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit import GleitzeitClient


async def test_workflow(client: GleitzeitClient, workflow_path: str, test_name: str):
    """Run and test a single workflow."""
    print(f"\n{'='*60}")
    print(f"Test: {test_name}")
    print(f"File: {workflow_path}")
    print('='*60)
    
    if not Path(workflow_path).exists():
        print(f"❌ File not found: {workflow_path}")
        return False
    
    try:
        # Run the workflow
        print("Running workflow...")
        results = await client.run_workflow(workflow_path)
        
        print(f"✅ Workflow completed!")
        print(f"   Tasks executed: {len(results)}")
        
        # Show results for each task
        for task_id, result in results.items():
            if hasattr(result, 'status'):
                status = result.status
                print(f"\n   Task '{task_id}': {status}")
                
                if hasattr(result, 'error') and result.error:
                    print(f"      Error: {result.error}")
                elif hasattr(result, 'result') and result.result:
                    # Show result preview
                    if isinstance(result.result, dict):
                        if 'response' in result.result:
                            preview = str(result.result['response'])[:100]
                        elif 'result' in result.result:
                            preview = str(result.result['result'])[:100]
                        else:
                            preview = str(result.result)[:100]
                    else:
                        preview = str(result.result)[:100]
                    
                    if len(str(result.result)) > 100:
                        preview += "..."
                    print(f"      Result: {preview}")
        
        return True
        
    except Exception as e:
        print(f"❌ Workflow failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_mcp_workflow(client: GleitzeitClient):
    """Test MCP workflow with tools."""
    return await test_workflow(
        client,
        "examples/simple_mcp_workflow.yaml",
        "MCP Workflow (echo, add, multiply, concat)"
    )


async def test_python_workflow(client: GleitzeitClient):
    """Test Python-only workflow."""
    return await test_workflow(
        client,
        "examples/simple_python_workflow.yaml",
        "Python Script Execution"
    )


async def test_python_only_workflow(client: GleitzeitClient):
    """Test Python workflow with multiple tasks."""
    return await test_workflow(
        client,
        "examples/python_only_workflow.yaml",
        "Python Only Multi-Task Workflow"
    )


async def test_dependent_workflow(client: GleitzeitClient):
    """Test workflow with task dependencies."""
    return await test_workflow(
        client,
        "examples/dependent_workflow.yaml",
        "Dependent LLM Workflow"
    )


async def test_mixed_workflow(client: GleitzeitClient):
    """Test mixed Python + LLM workflow."""
    return await test_workflow(
        client,
        "examples/mixed_workflow.yaml",
        "Mixed Python + LLM Workflow"
    )


async def test_parallel_workflow(client: GleitzeitClient):
    """Test parallel task execution."""
    return await test_workflow(
        client,
        "examples/parallel_workflow.yaml",
        "Parallel Task Execution"
    )


async def test_context_workflow(client: GleitzeitClient):
    """Test context passing between Python tasks."""
    return await test_workflow(
        client,
        "examples/test_context_workflow.yaml",
        "Context Passing Workflow"
    )


async def test_batch_workflows(client: GleitzeitClient):
    """Test batch processing capabilities."""
    print(f"\n{'='*60}")
    print("Test: Batch Processing")
    print('='*60)
    
    try:
        # Test batch text processing
        print("\nTesting batch text processing...")
        results = await client.batch_chat(
            directory="examples/documents",
            pattern="*.txt",
            prompt="Summarize this document in one sentence",
            model="llama3.2:latest"
        )
        
        print(f"✅ Batch completed!")
        print(f"   Batch ID: {results.get('batch_id')}")
        print(f"   Files: {results.get('total_files', 0)}")
        print(f"   Successful: {results.get('successful', 0)}")
        print(f"   Failed: {results.get('failed', 0)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Batch processing failed: {e}")
        return False


async def main():
    """Run the workflow test suite."""
    print("="*60)
    print("Gleitzeit Workflow Test Suite via Python API")
    print("="*60)
    
    # Check Ollama availability
    import aiohttp
    ollama_available = False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:11434/api/tags", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status == 200:
                    ollama_available = True
                    print("✅ Ollama is available")
    except:
        print("⚠️  Ollama is not available - LLM tests will be skipped")
    
    # Initialize client
    client = GleitzeitClient(persistence="memory")
    await client.initialize()
    
    results = []
    
    # Test 1: MCP Workflow (no LLM needed)
    print("\n" + "="*60)
    print("TESTING NON-LLM WORKFLOWS")
    print("="*60)
    
    success = await test_mcp_workflow(client)
    results.append(("MCP Workflow", success))
    
    # Test 2: Python Script Execution
    success = await test_python_workflow(client)
    results.append(("Python Script", success))
    
    # Test 3: Python Only Multi-Task
    success = await test_python_only_workflow(client)
    results.append(("Python Multi-Task", success))
    
    # Test 4: Context Passing
    success = await test_context_workflow(client)
    results.append(("Context Passing", success))
    
    # LLM-dependent tests
    if ollama_available:
        print("\n" + "="*60)
        print("TESTING LLM WORKFLOWS")
        print("="*60)
        
        # Test 5: Dependent Workflow
        success = await test_dependent_workflow(client)
        results.append(("Dependent Workflow", success))
        
        # Test 6: Mixed Workflow
        success = await test_mixed_workflow(client)
        results.append(("Mixed Workflow", success))
        
        # Test 7: Parallel Workflow  
        success = await test_parallel_workflow(client)
        results.append(("Parallel Workflow", success))
        
        # Test 8: Batch Processing
        success = await test_batch_workflows(client)
        results.append(("Batch Processing", success))
    
    # Cleanup
    await client.shutdown()
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)