#!/usr/bin/env python3
"""
Step-by-step testing of workflows to debug dependency issues.
"""

import asyncio
import sys
import os
import json

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit import GleitzeitClient
from gleitzeit.core.workflow_loader import load_workflow_from_file


async def test_simple_mcp():
    """Test the simplest MCP workflow - just echo."""
    print("\n" + "="*60)
    print("TEST 1: Simple MCP Echo (no dependencies)")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        # Create a simple workflow with just one MCP task
        workflow = await client.create_workflow(
            name="Simple Echo Test",
            tasks=[
                {
                    "id": "echo_test",
                    "name": "Echo Message",
                    "method": "mcp/tool.echo",
                    "params": {
                        "message": "Hello from MCP!"
                    }
                }
            ]
        )
        
        print(f"Workflow created with {len(workflow.tasks)} task(s)")
        print(f"Task IDs: {[t.id for t in workflow.tasks]}")
        
        try:
            results = await client.run_workflow(workflow)
            print(f"✅ Success! Results:")
            for task_id, result in results.items():
                print(f"  {task_id}: {result}")
            return True
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False


async def test_mcp_with_dependency():
    """Test MCP workflow with a simple dependency."""
    print("\n" + "="*60)
    print("TEST 2: MCP with Dependency")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        # Create workflow with dependency
        workflow = await client.create_workflow(
            name="MCP Dependency Test",
            tasks=[
                {
                    "id": "add_numbers",
                    "name": "Add Numbers",
                    "method": "mcp/tool.add",
                    "params": {
                        "a": 10,
                        "b": 20
                    }
                },
                {
                    "id": "multiply_result",
                    "name": "Multiply Result",
                    "method": "mcp/tool.multiply",
                    "dependencies": ["add_numbers"],
                    "params": {
                        "a": "${add_numbers.result}",
                        "b": 2
                    }
                }
            ]
        )
        
        print(f"Workflow created with {len(workflow.tasks)} task(s)")
        for task in workflow.tasks:
            print(f"  Task '{task.id}' depends on: {task.dependencies}")
        
        try:
            results = await client.run_workflow(workflow)
            print(f"✅ Success! Results:")
            for task_id, result in results.items():
                if hasattr(result, 'result'):
                    print(f"  {task_id}: {result.result}")
                else:
                    print(f"  {task_id}: {result}")
            return True
        except Exception as e:
            print(f"❌ Failed: {e}")
            import traceback
            traceback.print_exc()
            return False


async def test_load_yaml_workflow():
    """Test loading and running a YAML workflow."""
    print("\n" + "="*60)
    print("TEST 3: Load YAML Workflow")
    print("="*60)
    
    # First, let's examine the YAML workflow
    yaml_path = "examples/simple_mcp_workflow.yaml"
    print(f"Loading workflow from: {yaml_path}")
    
    try:
        workflow = load_workflow_from_file(yaml_path)
        print(f"Loaded workflow: {workflow.name}")
        print(f"Tasks in workflow:")
        for task in workflow.tasks:
            print(f"  - ID: {task.id}")
            print(f"    Method: {task.method}")
            print(f"    Dependencies: {task.dependencies}")
            print(f"    Params: {json.dumps(task.params, indent=6)}")
        
        # Now try to run it
        async with GleitzeitClient(persistence="memory") as client:
            print("\nRunning workflow...")
            results = await client.run_workflow(workflow)
            print(f"✅ Success! Got {len(results)} results")
            for task_id, result in results.items():
                if hasattr(result, 'result'):
                    print(f"  {task_id}: {result.result}")
                else:
                    print(f"  {task_id}: {result}")
            return True
            
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_python_workflow():
    """Test a simple Python workflow."""
    print("\n" + "="*60)
    print("TEST 4: Simple Python Workflow")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        # Create a simple Python workflow
        workflow = await client.create_workflow(
            name="Python Test",
            tasks=[
                {
                    "id": "generate_numbers",
                    "name": "Generate Numbers",
                    "method": "python/execute",
                    "params": {
                        "file": "examples/scripts/generate_numbers.py",
                        "timeout": 5
                    }
                }
            ]
        )
        
        print(f"Workflow created with {len(workflow.tasks)} task(s)")
        
        try:
            results = await client.run_workflow(workflow)
            print(f"✅ Success! Results:")
            for task_id, result in results.items():
                if hasattr(result, 'result'):
                    print(f"  {task_id}: {result.result}")
                else:
                    print(f"  {task_id}: {result}")
            return True
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False


async def test_llm_workflow():
    """Test a simple LLM workflow."""
    print("\n" + "="*60)
    print("TEST 5: Simple LLM Workflow")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        # Create a simple LLM workflow
        workflow = await client.create_workflow(
            name="LLM Test",
            tasks=[
                {
                    "id": "generate_joke",
                    "name": "Generate Joke",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [
                            {"role": "user", "content": "Tell me a short joke"}
                        ],
                        "temperature": 0.9
                    }
                }
            ]
        )
        
        print(f"Workflow created with {len(workflow.tasks)} task(s)")
        
        try:
            results = await client.run_workflow(workflow)
            print(f"✅ Success! Results:")
            for task_id, result in results.items():
                if hasattr(result, 'result') and isinstance(result.result, dict):
                    if 'response' in result.result:
                        print(f"  {task_id}: {result.result['response'][:100]}...")
                    else:
                        print(f"  {task_id}: {result.result}")
                else:
                    print(f"  {task_id}: {result}")
            return True
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False


async def main():
    """Run step-by-step tests."""
    print("="*60)
    print("Step-by-Step Workflow Testing")
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
    
    results = []
    
    # Test 1: Simple MCP echo
    success = await test_simple_mcp()
    results.append(("Simple MCP Echo", success))
    
    # Test 2: MCP with dependency
    success = await test_mcp_with_dependency()
    results.append(("MCP with Dependency", success))
    
    # Test 3: Load YAML workflow
    success = await test_load_yaml_workflow()
    results.append(("YAML Workflow Loading", success))
    
    # Test 4: Python workflow
    success = await test_python_workflow()
    results.append(("Python Workflow", success))
    
    # Test 5: LLM workflow (if available)
    if ollama_available:
        success = await test_llm_workflow()
        results.append(("LLM Workflow", success))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    passed = sum(1 for _, s in results if s)
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)