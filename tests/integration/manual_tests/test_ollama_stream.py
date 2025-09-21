#!/usr/bin/env python
"""Test Ollama workflow execution with stream transport enabled."""

import asyncio
import os
import json
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task

async def test_ollama_workflow():
    """Test workflow with Ollama provider via stream transport."""
    
    # Ensure stream mode is enabled
    os.environ["GLEITZEIT_STREAM_MODE"] = "enabled"
    
    # Create client
    client = GleitzeitClient(base_url="http://localhost:8070")
    await client.initialize()
    
    # Create Ollama workflow with simple prompts
    workflow = Workflow(
        id="test-ollama-stream",
        name="Ollama Stream Transport Test",
        tasks=[
            Task(
                id="ollama1",
                name="Generate Haiku",
                protocol="llm/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2:latest",
                    "prompt": "Write a haiku about Redis streams",
                    "options": {
                        "temperature": 0.7,
                        "max_tokens": 50
                    }
                },
                dependencies=[]
            ),
            Task(
                id="ollama2", 
                name="Generate Joke",
                protocol="llm/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2:latest",
                    "prompt": "Tell a short joke about distributed systems",
                    "options": {
                        "temperature": 0.8,
                        "max_tokens": 100
                    }
                },
                dependencies=["ollama1"]
            ),
            Task(
                id="ollama3",
                name="Generate Summary",
                protocol="llm/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2:latest",
                    "prompt": "In one sentence, explain what Redis is",
                    "options": {
                        "temperature": 0.5,
                        "max_tokens": 50
                    }
                },
                dependencies=["ollama2"]
            )
        ]
    )
    
    print(f"Submitting Ollama workflow: {workflow.id}")
    print("This workflow will test stream transport with real LLM tasks")
    
    # Submit workflow
    result = await client.submit_workflow(workflow)
    
    if isinstance(result, dict):
        workflow_id = result.get("workflow_id")
    else:
        workflow_id = result
    
    print(f"Workflow submitted: {workflow_id}")
    print("Waiting for completion (this may take a minute)...")
    
    # Wait for completion with longer timeout for LLM tasks
    max_attempts = 60  # 2 minutes total
    for i in range(max_attempts):
        await asyncio.sleep(2)
        
        # Check workflow status
        workflow_data = await client.get_workflow(workflow_id)
        
        if workflow_data:
            status = workflow_data.status if hasattr(workflow_data, 'status') else workflow_data.get('status')
            
            if i % 5 == 0:  # Print status every 10 seconds
                print(f"  Status: {status} (attempt {i+1}/{max_attempts})")
            
            if status in ["completed", "failed"]:
                if status == "completed":
                    print("\n✅ Workflow completed successfully!")
                    
                    # Get results
                    results = await client.get_workflow_results(workflow_id)
                    print("\n📝 Results:")
                    
                    if isinstance(results, dict):
                        for task_id, task_result in results.items():
                            print(f"\n  Task: {task_id}")
                            if isinstance(task_result, dict):
                                if 'result' in task_result:
                                    result_data = task_result['result']
                                    if isinstance(result_data, dict) and 'response' in result_data:
                                        print(f"  Response: {result_data['response'][:200]}...")
                                    else:
                                        print(f"  Result: {result_data}")
                                elif 'error' in task_result:
                                    print(f"  Error: {task_result['error']}")
                            else:
                                print(f"  Result: {task_result}")
                    
                    print("\n🎯 Stream transport successfully handled Ollama workflow!")
                else:
                    print(f"\n❌ Workflow failed: {status}")
                    
                    # Try to get error details
                    results = await client.get_workflow_results(workflow_id)
                    if results:
                        print(f"Error details: {json.dumps(results, indent=2)}")
                break
    else:
        print("⏱️ Workflow timed out after 2 minutes")
    
    # await client.close()  # TODO: Add close method to client

if __name__ == "__main__":
    print("=" * 60)
    print("Testing Ollama Workflow with Stream Transport")
    print("=" * 60)
    asyncio.run(test_ollama_workflow())