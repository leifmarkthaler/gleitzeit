#!/usr/bin/env python3
"""
Test more complex workflows including mixed Python+LLM and batch processing.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit import GleitzeitClient
from gleitzeit.core.workflow_loader import load_workflow_from_file


async def test_mixed_workflow():
    """Test mixed Python + LLM workflow."""
    print("\n" + "="*60)
    print("TEST: Mixed Python + LLM Workflow")
    print("="*60)
    
    yaml_path = "examples/mixed_workflow.yaml"
    print(f"Loading: {yaml_path}")
    
    try:
        workflow = load_workflow_from_file(yaml_path)
        print(f"Workflow: {workflow.name}")
        print(f"Tasks: {len(workflow.tasks)}")
        
        async with GleitzeitClient(persistence="memory") as client:
            results = await client.run_workflow(workflow)
            print(f"✅ Success! Results:")
            
            for task_id, result in results.items():
                print(f"\n  Task: {task_id}")
                if hasattr(result, 'result'):
                    if isinstance(result.result, dict):
                        if 'response' in result.result:
                            preview = result.result['response'][:100]
                        elif 'result' in result.result:
                            preview = str(result.result['result'])[:100]
                        else:
                            preview = str(result.result)[:100]
                    else:
                        preview = str(result.result)[:100]
                    print(f"    Result: {preview}...")
            
            return True
            
    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_dependent_workflow():
    """Test dependent workflow with parameter substitution."""
    print("\n" + "="*60)
    print("TEST: Dependent Workflow")
    print("="*60)
    
    yaml_path = "examples/dependent_workflow.yaml"
    print(f"Loading: {yaml_path}")
    
    try:
        workflow = load_workflow_from_file(yaml_path)
        print(f"Workflow: {workflow.name}")
        print(f"Tasks:")
        for task in workflow.tasks:
            print(f"  - {task.id}: depends on {task.dependencies}")
        
        async with GleitzeitClient(persistence="memory") as client:
            results = await client.run_workflow(workflow)
            print(f"\n✅ Success! Results:")
            
            for task_id, result in results.items():
                print(f"\n  Task: {task_id}")
                if hasattr(result, 'result') and isinstance(result.result, dict):
                    if 'response' in result.result:
                        preview = result.result['response'][:150]
                        print(f"    Response: {preview}...")
            
            return True
            
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False


async def test_parallel_workflow():
    """Test parallel task execution."""
    print("\n" + "="*60)
    print("TEST: Parallel Workflow")
    print("="*60)
    
    yaml_path = "examples/parallel_workflow.yaml"
    print(f"Loading: {yaml_path}")
    
    try:
        workflow = load_workflow_from_file(yaml_path)
        print(f"Workflow: {workflow.name}")
        print(f"Tasks: {len(workflow.tasks)} (should run in parallel)")
        
        async with GleitzeitClient(persistence="memory") as client:
            import time
            start_time = time.time()
            
            results = await client.run_workflow(workflow)
            
            elapsed = time.time() - start_time
            print(f"\n✅ Success! Completed in {elapsed:.2f} seconds")
            print(f"Tasks executed: {len(results)}")
            
            return True
            
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False


async def test_python_context_workflow():
    """Test Python workflow with context passing."""
    print("\n" + "="*60)
    print("TEST: Python Context Passing")
    print("="*60)
    
    yaml_path = "examples/test_context_workflow.yaml"
    print(f"Loading: {yaml_path}")
    
    try:
        workflow = load_workflow_from_file(yaml_path)
        print(f"Workflow: {workflow.name}")
        
        async with GleitzeitClient(persistence="memory") as client:
            results = await client.run_workflow(workflow)
            print(f"\n✅ Success! Results:")
            
            for task_id, result in results.items():
                print(f"  Task: {task_id}")
                if hasattr(result, 'result'):
                    print(f"    Result: {result.result}")
            
            return True
            
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False


async def test_batch_processing():
    """Test batch processing functionality."""
    print("\n" + "="*60)
    print("TEST: Batch Processing")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        try:
            # Test 1: Batch process text documents
            print("\n1. Batch processing text documents...")
            results = await client.batch_chat(
                directory="examples/documents",
                pattern="*.txt",
                prompt="Summarize this document in exactly 10 words",
                model="llama3.2:latest"
            )
            
            print(f"   ✅ Batch ID: {results.get('batch_id')}")
            print(f"   Files: {results.get('total_files', 0)}")
            
            # Test 2: Process specific files
            print("\n2. Processing specific files...")
            files = ["examples/doc1.txt", "examples/doc2.txt"]
            results = await client.batch_process(
                files=files,
                prompt="What is the main topic?",
                model="llama3.2:latest"
            )
            
            print(f"   ✅ Processed {len(files)} files")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False


async def test_text_file_workflow():
    """Test workflow that reads and processes text files."""
    print("\n" + "="*60)
    print("TEST: Text File Processing Workflow")
    print("="*60)
    
    yaml_path = "examples/text_file_workflow.yaml"
    print(f"Loading: {yaml_path}")
    
    try:
        workflow = load_workflow_from_file(yaml_path)
        print(f"Workflow: {workflow.name}")
        
        async with GleitzeitClient(persistence="memory") as client:
            results = await client.run_workflow(workflow)
            print(f"\n✅ Success! Processed {len(results)} tasks")
            
            return True
            
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False


async def main():
    """Run complex workflow tests."""
    print("="*60)
    print("Complex Workflow Testing via Python API")
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
        return False
    
    results = []
    
    # Test workflows that require LLM
    if ollama_available:
        # Test 1: Mixed Python + LLM
        success = await test_mixed_workflow()
        results.append(("Mixed Python+LLM", success))
        
        # Test 2: Dependent workflow
        success = await test_dependent_workflow()
        results.append(("Dependent Workflow", success))
        
        # Test 3: Parallel workflow
        success = await test_parallel_workflow()
        results.append(("Parallel Workflow", success))
        
        # Test 4: Text file workflow
        success = await test_text_file_workflow()
        results.append(("Text File Workflow", success))
        
        # Test 5: Batch processing
        success = await test_batch_processing()
        results.append(("Batch Processing", success))
    
    # Test 6: Python context (no LLM needed)
    success = await test_python_context_workflow()
    results.append(("Python Context", success))
    
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