#!/usr/bin/env python3
"""
Test that Ollama workflows work with hub integration
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit import Client
from gleitzeit.client import ClientMode


async def test_ollama_workflow():
    """Test Ollama workflow with hub integration"""
    
    print("Testing Ollama Workflow with Hub Integration...")
    print("-" * 50)
    
    # Create a simple Ollama workflow
    workflow = {
        "name": "Ollama Test Workflow",
        "tasks": [
            {
                "id": "task1",
                "method": "llm/chat",
                "parameters": {
                    "model": "llama3.2:latest",
                    "messages": [
                        {"role": "user", "content": "What is 2+2? Answer in one word."}
                    ]
                }
            },
            {
                "id": "task2", 
                "method": "llm/chat",
                "dependencies": ["task1"],
                "parameters": {
                    "model": "llama3.2:latest",
                    "messages": [
                        {"role": "user", "content": "You said ${task1.response}. Is that the correct answer to 2+2? Yes or No only."}
                    ]
                }
            }
        ]
    }
    
    # Test in native mode with resource management
    async with Client(
        mode=ClientMode.NATIVE,
        native_config={'enable_resource_management': True}
    ) as client:
        print("✓ Client initialized with resource management")
        
        # Check hub status
        if hasattr(client, '_ollama_hub') and client._ollama_hub:
            instances = await client._ollama_hub.list_instances()
            print(f"✓ Found {len(instances)} Ollama instances via hub")
            for instance in instances:
                print(f"  - {instance.id}: {instance.endpoint}")
        
        # Save workflow to file
        import json
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name
        
        # Run the workflow
        print("\nRunning Ollama workflow...")
        try:
            results = await client.run_workflow(workflow_file)
            
            print("✓ Workflow completed successfully!")
            
            # Check results
            workflow_results = results.get('results', {})
            
            if 'task1' in workflow_results:
                task1_result = workflow_results['task1'].get('result', {})
                print(f"  Task 1 response: {task1_result.get('response', 'N/A')}")
            else:
                print("  Task 1: No result")
                
            if 'task2' in workflow_results:
                task2_result = workflow_results['task2'].get('result', {})
                print(f"  Task 2 response: {task2_result.get('response', 'N/A')}")
            else:
                print("  Task 2: No result")
                
            return True
            
        except Exception as e:
            print(f"✗ Workflow failed: {e}")
            import traceback
            traceback.print_exc()
            return False


async def test_direct_ollama_call():
    """Test direct Ollama call with hub"""
    
    print("\n" + "="*50)
    print("Testing Direct Ollama Call with Hub...")
    print("-" * 50)
    
    async with Client(
        mode=ClientMode.NATIVE,
        native_config={'enable_resource_management': True}
    ) as client:
        
        # Test direct chat call
        try:
            response = await client.chat(
                "What is the capital of France? Answer in one word.",
                model="llama3.2:latest"
            )
            print(f"✓ Direct chat works: {response}")
            return True
        except Exception as e:
            print(f"✗ Direct chat failed: {e}")
            return False


async def main():
    """Run all tests"""
    
    # Test workflow
    workflow_ok = await test_ollama_workflow()
    
    # Test direct call
    direct_ok = await test_direct_ollama_call()
    
    print("\n" + "="*50)
    if workflow_ok and direct_ok:
        print("✅ All Ollama tests passed! Hub integration is working.")
    else:
        print("❌ Some Ollama tests failed. Check hub integration.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())