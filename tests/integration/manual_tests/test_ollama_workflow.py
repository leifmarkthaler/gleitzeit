#!/usr/bin/env python3
"""
Test Ollama workflow execution through Gleitzeit.
"""

import asyncio
import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

async def test_ollama_workflow():
    """Test Ollama LLM workflow execution."""
    
    print("Testing Ollama Workflow")
    print("=" * 50)
    
    # Import required modules
    from gleitzeit.system.system_manager import SystemManager
    from gleitzeit.system.models import SystemConfig
    from gleitzeit.core import Task, Workflow
    import uuid
    
    # Create test configuration with Ollama provider
    config = SystemConfig(
        environment="test",
        persistence_backend="redis",  # Use Redis if available for better performance
        enable_auth=False,
        default_providers=["python", "ollama"]  # Include Ollama provider
    )
    
    # Initialize system
    print("1. Initializing SystemManager...")
    system_manager = SystemManager(config=config)
    await system_manager.initialize()
    
    # Start system - this will automatically register Ollama provider
    print("2. Starting system (will register Ollama provider)...")
    await system_manager.start_system()
    print("✓ System started with Ollama provider")
    
    print("\n3. Creating Ollama workflow tasks...")
    
    # Create multiple LLM tasks
    tasks = []
    
    # Task 1: Simple generation
    task1 = Task(
        id=f"ollama_generate_{uuid.uuid4().hex[:8]}",
        name="Generate Text",
        protocol="llm/v1",
        method="llm/generate",
        params={
            "model": "llama3.2:latest",
            "prompt": "Write a haiku about programming:",
            "max_tokens": 100,
            "temperature": 0.7
        }
    )
    tasks.append(task1)
    
    # Task 2: Chat completion
    task2 = Task(
        id=f"ollama_chat_{uuid.uuid4().hex[:8]}",
        name="Chat Completion",
        protocol="llm/v1",
        method="llm/chat",
        params={
            "model": "llama3.2:latest",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is the capital of France? Answer in one word."}
            ],
            "max_tokens": 50,
            "temperature": 0.1
        }
    )
    tasks.append(task2)
    
    # Task 3: Another generation with dependency on task1
    task3 = Task(
        id=f"ollama_followup_{uuid.uuid4().hex[:8]}",
        name="Follow-up Generation",
        protocol="llm/v1",
        method="llm/generate",
        params={
            "model": "llama3.2:latest",
            "prompt": "Explain recursion in one sentence:",
            "max_tokens": 100,
            "temperature": 0.5
        },
        dependencies=[task1.id]  # Depends on task1 completing first
    )
    tasks.append(task3)
    
    # Create workflow
    workflow = Workflow(
        id=f"ollama_workflow_{uuid.uuid4().hex[:8]}",
        name="Ollama Test Workflow",
        description="Test workflow for Ollama LLM tasks",
        tasks=tasks
    )
    
    print(f"✓ Created workflow with {len(tasks)} tasks")
    
    # Execute workflow
    print("\n4. Executing Ollama workflow...")
    result = await system_manager.workflow_manager.execute_workflow(workflow)
    print(f"✓ Workflow submitted: {result['execution_id']}")
    
    # Poll for completion
    print("\n5. Waiting for completion...")
    max_wait = 30  # seconds
    poll_interval = 2
    elapsed = 0
    
    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        
        # Check workflow status
        status = await system_manager.workflow_manager.get_execution_status(result['execution_id'])
        if status:
            print(f"  Status: {status['status']}, Progress: {status['progress']:.0f}%")
            
            if status['status'] in ['completed', 'failed']:
                break
    
    # Get results
    print("\n6. Retrieving results...")
    completed_count = 0
    for task in tasks:
        task_result = await system_manager.persistence.get_task_result(task.id)
        if task_result:
            print(f"\n✓ Task: {task.name}")
            print(f"  Status: {task_result.status}")
            
            if task_result.status == "completed":
                completed_count += 1
                if task_result.result:
                    # Pretty print the result
                    if isinstance(task_result.result, dict):
                        if 'response' in task_result.result:
                            print(f"  Response: {task_result.result['response'][:200]}...")
                        elif 'content' in task_result.result:
                            print(f"  Content: {task_result.result['content'][:200]}...")
                        else:
                            print(f"  Result: {json.dumps(task_result.result, indent=2)[:200]}...")
            else:
                if task_result.error:
                    print(f"  Error: {task_result.error}")
    
    # Cleanup
    await system_manager.shutdown()
    
    print("\n" + "=" * 50)
    if completed_count == len(tasks):
        print(f"✅ All {completed_count} Ollama tasks completed successfully!")
    else:
        print(f"⚠️  {completed_count}/{len(tasks)} tasks completed")
    
    return completed_count == len(tasks)

if __name__ == "__main__":
    try:
        success = asyncio.run(test_ollama_workflow())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)