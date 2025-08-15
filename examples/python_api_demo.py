#!/usr/bin/env python3
"""
Gleitzeit Python API Demo
Demonstrates various ways to use the Gleitzeit Python client.
"""

import asyncio
import sys
import os

# Add the src directory to the path if running from examples
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from gleitzeit import GleitzeitClient


async def demo_simple_chat():
    """Demo: Simple chat interaction."""
    print("\n" + "="*60)
    print("DEMO 1: Simple Chat")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        response = await client.chat(
            prompt="What is the capital of France?",
            temperature=0.3  # Lower temperature for factual response
        )
        print(f"Response: {response}")


async def demo_workflow_creation():
    """Demo: Create and run a workflow programmatically."""
    print("\n" + "="*60)
    print("DEMO 2: Programmatic Workflow Creation")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        # Create a workflow with dependent tasks
        workflow = await client.create_workflow(
            name="Story Generator",
            tasks=[
                {
                    "id": "generate_character",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [{
                            "role": "user",
                            "content": "Create a fictional character name and one-line description"
                        }],
                        "temperature": 0.9
                    }
                },
                {
                    "id": "write_story",
                    "dependencies": ["generate_character"],
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [{
                            "role": "user",
                            "content": "Write a 3-sentence story about: ${generate_character.response}"
                        }],
                        "temperature": 0.8
                    }
                }
            ]
        )
        
        print("Running workflow...")
        results = await client.run_workflow(workflow)
        
        # Display results
        for task_id in ["generate_character", "write_story"]:
            if task_id in results:
                result = results[task_id]
                if hasattr(result, 'result') and isinstance(result.result, dict):
                    response = result.result.get('response', str(result.result))
                    print(f"\n{task_id}:")
                    print(f"  {response[:200]}...")


async def demo_mixed_processing():
    """Demo: Mix Python and LLM processing."""
    print("\n" + "="*60)
    print("DEMO 3: Mixed Python + LLM Processing")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        workflow = await client.create_workflow(
            name="Data Analysis Pipeline",
            tasks=[
                {
                    "id": "generate_data",
                    "method": "python/execute",
                    "params": {
                        "file": "examples/scripts/generate_numbers.py",
                        "timeout": 5
                    }
                },
                {
                    "id": "analyze_data",
                    "dependencies": ["generate_data"],
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [{
                            "role": "user",
                            "content": "Analyze this data and provide one insight: ${generate_data.result}"
                        }],
                        "temperature": 0.5
                    }
                }
            ]
        )
        
        print("Running mixed workflow...")
        results = await client.run_workflow(workflow)
        
        # Show Python result
        if "generate_data" in results:
            data_result = results["generate_data"]
            if hasattr(data_result, 'result'):
                print(f"\nGenerated data: {data_result.result}")
        
        # Show LLM analysis
        if "analyze_data" in results:
            analysis = results["analyze_data"]
            if hasattr(analysis, 'result') and isinstance(analysis.result, dict):
                response = analysis.result.get('response', '')
                print(f"\nAnalysis: {response[:300]}...")


async def demo_mcp_tools():
    """Demo: Use MCP tools for computation."""
    print("\n" + "="*60)
    print("DEMO 4: MCP Tools")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        workflow = await client.create_workflow(
            name="Calculator",
            tasks=[
                {
                    "id": "add",
                    "method": "mcp/tool.add",
                    "params": {"a": 15, "b": 27}
                },
                {
                    "id": "multiply",
                    "dependencies": ["add"],
                    "method": "mcp/tool.multiply",
                    "params": {
                        "a": "${add.result}",
                        "b": 3
                    }
                },
                {
                    "id": "display",
                    "dependencies": ["add", "multiply"],
                    "method": "mcp/tool.concat",
                    "params": {
                        "strings": [
                            "15 + 27 = ${add.result}",
                            "Result × 3 = ${multiply.result}"
                        ],
                        "separator": " | "
                    }
                }
            ]
        )
        
        print("Running MCP workflow...")
        results = await client.run_workflow(workflow)
        
        # Show calculation results
        for task_id in ["add", "multiply", "display"]:
            if task_id in results:
                result = results[task_id]
                if hasattr(result, 'result'):
                    if isinstance(result.result, dict):
                        value = result.result.get('result', result.result.get('response', result.result))
                    else:
                        value = result.result
                    print(f"{task_id}: {value}")


async def demo_batch_processing():
    """Demo: Batch process multiple files."""
    print("\n" + "="*60)
    print("DEMO 5: Batch Processing")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        print("Processing documents in batch...")
        
        results = await client.batch_chat(
            directory="examples/documents",
            pattern="*.txt",
            prompt="Summarize this document in exactly 10 words",
            model="llama3.2:latest"
        )
        
        print(f"\nBatch Results:")
        print(f"  Batch ID: {results.get('batch_id')}")
        print(f"  Total files: {results.get('total_files', 0)}")
        print(f"  Successful: {results.get('successful', 0)}")
        print(f"  Failed: {results.get('failed', 0)}")


async def demo_yaml_workflow():
    """Demo: Run an existing YAML workflow."""
    print("\n" + "="*60)
    print("DEMO 6: YAML Workflow Execution")
    print("="*60)
    
    async with GleitzeitClient(persistence="memory") as client:
        print("Running simple_llm_workflow.yaml...")
        
        results = await client.run_workflow("examples/simple_llm_workflow.yaml")
        
        print(f"\nExecuted {len(results)} tasks:")
        for task_id, result in results.items():
            if hasattr(result, 'status'):
                print(f"  - {task_id}: {result.status}")


async def main():
    """Run all demos."""
    print("="*60)
    print("Gleitzeit Python API Demonstrations")
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
        print("⚠️  Ollama is not available - LLM demos will be skipped")
    
    # Run demos
    try:
        # MCP demo (always available)
        await demo_mcp_tools()
        
        # LLM-dependent demos
        if ollama_available:
            await demo_simple_chat()
            await demo_workflow_creation()
            await demo_mixed_processing()
            await demo_batch_processing()
            await demo_yaml_workflow()
        else:
            print("\nSkipping LLM demos - Ollama not available")
        
        print("\n" + "="*60)
        print("All demos completed successfully!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)