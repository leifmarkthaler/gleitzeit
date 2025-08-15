#!/usr/bin/env python3
"""
Test running example workflows via the Gleitzeit Python API.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit import GleitzeitClient


async def run_example_workflow(client: GleitzeitClient, workflow_path: str, description: str):
    """Run a single example workflow."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"File: {workflow_path}")
    print('='*60)
    
    try:
        results = await client.run_workflow(workflow_path)
        
        print(f"✅ Workflow completed successfully!")
        print(f"   Number of tasks: {len(results)}")
        
        # Show summary of results
        for task_id, result in results.items():
            if hasattr(result, 'status'):
                status = result.status
                if hasattr(result, 'error') and result.error:
                    print(f"   Task {task_id}: {status} - Error: {result.error}")
                else:
                    print(f"   Task {task_id}: {status}")
                    if hasattr(result, 'result') and result.result:
                        # Show a preview of the result
                        result_str = str(result.result)
                        if isinstance(result.result, dict):
                            if 'response' in result.result:
                                result_str = result.result['response']
                            elif 'content' in result.result:
                                result_str = result.result['content']
                        
                        # Truncate long results
                        if len(result_str) > 100:
                            result_str = result_str[:100] + "..."
                        print(f"     Result preview: {result_str}")
        
        return True
        
    except Exception as e:
        print(f"❌ Workflow failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run example workflows via the API."""
    print("="*60)
    print("Testing Gleitzeit Example Workflows via Python API")
    print("="*60)
    
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
        print("⚠️  Ollama is not available - LLM workflows will be skipped")
    
    # Initialize client once for all tests
    client = GleitzeitClient(persistence="memory")
    await client.initialize()
    
    # Define workflows to test
    workflows = []
    
    # Simple workflows that should always work
    workflows.extend([
        ("examples/simple_mcp_workflow.yaml", "Simple MCP Workflow (echo, add, multiply)"),
        ("examples/simple_python_workflow.yaml", "Simple Python Workflow (generate numbers)"),
    ])
    
    # LLM-dependent workflows
    if ollama_available:
        workflows.extend([
            ("examples/simple_llm_workflow.yaml", "Simple LLM Workflow (generate story)"),
            ("examples/dependent_workflow.yaml", "Dependent Workflow (topic generation and expansion)"),
            ("examples/parallel_workflow.yaml", "Parallel Workflow (multiple independent tasks)"),
            ("examples/mixed_workflow.yaml", "Mixed Workflow (Python + LLM)"),
            ("examples/mcp_workflow.yaml", "MCP Workflow (tools integration)"),
        ])
        
        # Text file workflows
        workflows.extend([
            ("examples/text_file_workflow.yaml", "Text File Analysis Workflow"),
            ("examples/meeting_analysis_workflow.yaml", "Meeting Notes Analysis"),
        ])
        
        # Vision workflows (if llava model is available)
        # These might fail if llava model is not installed
        workflows.extend([
            ("examples/vision_workflow.yaml", "Vision Workflow (image analysis)"),
            ("examples/vision_file_workflow.yaml", "Vision File Workflow"),
            ("examples/mixed_vision_text_workflow.yaml", "Mixed Vision and Text Workflow"),
        ])
    
    # Python-only workflows
    workflows.extend([
        ("examples/python_only_workflow.yaml", "Python Only Workflow (data processing)"),
        ("examples/test_context_workflow.yaml", "Context Passing Workflow"),
    ])
    
    # Run all workflows
    results = []
    for workflow_path, description in workflows:
        # Check if file exists
        if not Path(workflow_path).exists():
            print(f"\n⚠️  Skipping {description} - file not found: {workflow_path}")
            continue
        
        success = await run_example_workflow(client, workflow_path, description)
        results.append((description, success))
        
        # Small delay between workflows
        await asyncio.sleep(0.5)
    
    # Cleanup
    await client.shutdown()
    
    # Summary
    print("\n" + "="*60)
    print("Summary of Example Workflows")
    print("="*60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for description, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{description}: {status}")
    
    print(f"\nTotal: {passed}/{total} workflows completed successfully")
    
    # Test batch processing with actual example files
    if ollama_available:
        print("\n" + "="*60)
        print("Testing Batch Processing with Example Files")
        print("="*60)
        
        async with GleitzeitClient(persistence="memory") as batch_client:
            try:
                # Test batch text processing
                print("\nBatch processing text documents...")
                text_results = await batch_client.batch_chat(
                    directory="examples/documents",
                    pattern="*.txt",
                    prompt="Summarize this document in one sentence",
                    model="llama3.2:latest"
                )
                print(f"✅ Batch text processing completed")
                print(f"   Batch ID: {text_results.get('batch_id')}")
                print(f"   Files processed: {text_results.get('total_files', 0)}")
                
            except Exception as e:
                print(f"❌ Batch processing failed: {e}")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)