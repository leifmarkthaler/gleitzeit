#!/usr/bin/env python3
"""
Test script for Gleitzeit Python client API.
"""

import asyncio
import tempfile
from pathlib import Path
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from gleitzeit import GleitzeitClient
from gleitzeit.client import chat, vision, run_workflow, batch_process, execute_python


async def test_basic_chat():
    """Test basic chat functionality."""
    print("\n=== Testing Basic Chat ===")
    
    async with GleitzeitClient(persistence="memory") as client:
        try:
            response = await client.chat(
                prompt="What is 2+2?",
                model="llama3.2:latest",
                temperature=0.1
            )
            print(f"Chat response: {response}")
            print("✅ Basic chat test passed")
            return True
        except Exception as e:
            print(f"❌ Basic chat test failed: {e}")
            return False


async def test_workflow_creation():
    """Test programmatic workflow creation."""
    print("\n=== Testing Workflow Creation ===")
    
    async with GleitzeitClient(persistence="memory") as client:
        try:
            # Create a simple workflow
            workflow = await client.create_workflow(
                name="Test Workflow",
                tasks=[
                    {
                        "id": "task1",
                        "name": "Generate topic",
                        "method": "llm/chat",
                        "params": {
                            "model": "llama3.2:latest",
                            "messages": [
                                {"role": "user", "content": "Generate a random topic in 3 words"}
                            ],
                            "temperature": 0.8
                        }
                    },
                    {
                        "id": "task2", 
                        "name": "Expand topic",
                        "method": "llm/chat",
                        "dependencies": ["task1"],
                        "params": {
                            "model": "llama3.2:latest",
                            "messages": [
                                {"role": "user", "content": "Write one sentence about: ${task1.response}"}
                            ],
                            "temperature": 0.7
                        }
                    }
                ]
            )
            
            print(f"Created workflow: {workflow.name} with {len(workflow.tasks)} tasks")
            
            # Run the workflow
            results = await client.run_workflow(workflow)
            
            print(f"Workflow completed with {len(results)} task results")
            for task_id, result in results.items():
                print(f"  Task {task_id}: {result}")
            
            print("✅ Workflow creation test passed")
            return True
        except Exception as e:
            print(f"❌ Workflow creation test failed: {e}")
            return False


async def test_python_execution():
    """Test Python script execution."""
    print("\n=== Testing Python Execution ===")
    
    # Create a test Python script
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("""
def process_data(context):
    # Simple computation
    x = context.get('x', 10)
    y = context.get('y', 20)
    result = x + y
    return {'sum': result, 'product': x * y}

# Execute the function
result = process_data(context)
""")
        script_path = f.name
    
    try:
        async with GleitzeitClient(persistence="memory") as client:
            result = await client.execute_python(
                script_file=script_path,
                context={'x': 5, 'y': 3},
                timeout=5
            )
            print(f"Python execution result: {result}")
            print("✅ Python execution test passed")
            return True
    except Exception as e:
        print(f"❌ Python execution test failed: {e}")
        return False
    finally:
        # Clean up
        Path(script_path).unlink(missing_ok=True)


async def test_batch_processing():
    """Test batch processing with sample files."""
    print("\n=== Testing Batch Processing ===")
    
    # Create test directory with sample files
    test_dir = Path(tempfile.mkdtemp())
    
    # Create some test text files
    for i in range(3):
        file_path = test_dir / f"test_{i}.txt"
        file_path.write_text(f"This is test document {i}. It contains sample text for processing.")
    
    try:
        async with GleitzeitClient(persistence="memory") as client:
            results = await client.batch_chat(
                directory=str(test_dir),
                pattern="*.txt",
                prompt="Summarize this in 5 words or less",
                model="llama3.2:latest"
            )
            
            print(f"Batch processing results:")
            print(f"  Batch ID: {results.get('batch_id')}")
            print(f"  Total files: {results.get('total_files')}")
            print(f"  Successful: {results.get('successful')}")
            print(f"  Failed: {results.get('failed')}")
            
            if 'file_results' in results:
                for file_result in results['file_results']:
                    print(f"  File: {file_result.get('file_path')}")
                    print(f"    Status: {file_result.get('status')}")
            
            print("✅ Batch processing test passed")
            return True
    except Exception as e:
        print(f"❌ Batch processing test failed: {e}")
        return False
    finally:
        # Clean up
        for file in test_dir.glob("*.txt"):
            file.unlink()
        test_dir.rmdir()


async def test_workflow_from_yaml():
    """Test running workflow from YAML file."""
    print("\n=== Testing Workflow from YAML ===")
    
    # Create a test workflow YAML
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("""
name: "Test YAML Workflow"
tasks:
  - id: "joke"
    name: "Tell a joke"
    method: "llm/chat"
    params:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "Tell me a very short joke"
      temperature: 0.9
      max_tokens: 50
""")
        yaml_path = f.name
    
    try:
        async with GleitzeitClient(persistence="memory") as client:
            results = await client.run_workflow(yaml_path)
            
            print(f"YAML workflow results:")
            for task_id, result in results.items():
                print(f"  Task {task_id}: {result}")
            
            print("✅ YAML workflow test passed")
            return True
    except Exception as e:
        print(f"❌ YAML workflow test failed: {e}")
        return False
    finally:
        Path(yaml_path).unlink(missing_ok=True)


async def test_mcp_tools():
    """Test MCP tool execution."""
    print("\n=== Testing MCP Tools ===")
    
    async with GleitzeitClient(persistence="memory") as client:
        try:
            # Create workflow with MCP tools
            workflow = await client.create_workflow(
                name="MCP Test Workflow",
                tasks=[
                    {
                        "id": "echo_test",
                        "name": "Echo test",
                        "method": "mcp/tool.echo",
                        "params": {
                            "message": "Hello from MCP!"
                        }
                    },
                    {
                        "id": "math_test",
                        "name": "Math test",
                        "method": "mcp/tool.add",
                        "params": {
                            "a": 10,
                            "b": 20
                        }
                    },
                    {
                        "id": "concat_test",
                        "name": "String concat",
                        "method": "mcp/tool.concat",
                        "params": {
                            "strings": ["Hello", " ", "World"]
                        }
                    }
                ]
            )
            
            results = await client.run_workflow(workflow)
            
            print(f"MCP tool results:")
            for task_id, result in results.items():
                print(f"  {task_id}: {result}")
            
            print("✅ MCP tools test passed")
            return True
        except Exception as e:
            print(f"❌ MCP tools test failed: {e}")
            return False


async def test_convenience_functions():
    """Test convenience functions for quick usage."""
    print("\n=== Testing Convenience Functions ===")
    
    try:
        # Test the convenience chat function
        response = await chat("Say 'Hello World' and nothing else", temperature=0.1)
        print(f"Convenience chat response: {response}")
        
        print("✅ Convenience functions test passed")
        return True
    except Exception as e:
        print(f"❌ Convenience functions test failed: {e}")
        return False


async def main():
    """Run all tests."""
    print("=" * 50)
    print("Gleitzeit Python Client Test Suite")
    print("=" * 50)
    
    # Check if Ollama is available
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
    
    tests = []
    
    # MCP tests (always available)
    tests.append(("MCP Tools", test_mcp_tools))
    
    # Python execution test (always available)
    tests.append(("Python Execution", test_python_execution))
    
    # LLM-dependent tests
    if ollama_available:
        tests.extend([
            ("Basic Chat", test_basic_chat),
            ("Workflow Creation", test_workflow_creation),
            ("Batch Processing", test_batch_processing),
            ("YAML Workflow", test_workflow_from_yaml),
            ("Convenience Functions", test_convenience_functions),
        ])
    
    # Run tests
    results = []
    for name, test_func in tests:
        try:
            success = await test_func()
            results.append((name, success))
        except Exception as e:
            print(f"❌ Test {name} crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("Test Summary")
    print("=" * 50)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)