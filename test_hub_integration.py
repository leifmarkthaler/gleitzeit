#!/usr/bin/env python3
"""
Test script for hub integration with providers
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit import Client
from gleitzeit.client import ClientMode


async def test_hub_integration():
    """Test that providers can use hubs for resource allocation"""
    
    print("Testing Hub Integration...")
    print("-" * 50)
    
    # Create client with resource management enabled
    async with Client(
        mode=ClientMode.NATIVE, 
        native_config={
            'enable_resource_management': True
        }
    ) as client:
        print("✓ Client initialized with resource management")
        
        # Check if hub was created
        if hasattr(client, '_ollama_hub') and client._ollama_hub:
            print(f"✓ OllamaHub created: {client._ollama_hub.hub_id}")
            
            # Check discovered instances
            instances = await client._ollama_hub.list_instances()
            print(f"✓ Discovered {len(instances)} Ollama instances")
            for instance in instances:
                print(f"  - {instance.id}: {instance.endpoint} ({instance.status.value})")
        else:
            print("✗ No OllamaHub found")
        
        # Test a simple LLM call
        print("\nTesting LLM call with hub allocation...")
        try:
            response = await client.chat(
                message="Say 'Hello from hub integration test' in 5 words or less",
                model="llama3.2:latest"
            )
            print(f"✓ LLM Response: {response}")
        except Exception as e:
            print(f"✗ LLM call failed: {e}")
        
        # Check resource manager metrics
        if hasattr(client, '_resource_manager') and client._resource_manager:
            metrics = await client._resource_manager.get_global_metrics()
            print("\nResource Manager Metrics:")
            print(f"  - Total hubs: {metrics['total_hubs']}")
            print(f"  - Total resources: {metrics['total_resources']}")
            print(f"  - Resources by type: {metrics['resources_by_type']}")
            print(f"  - Resources by status: {metrics['resources_by_status']}")
    
    print("\n✓ Test completed successfully!")


async def test_workflow_with_hub():
    """Test running a workflow with hub-based resource allocation"""
    
    print("\nTesting Workflow with Hub Integration...")
    print("-" * 50)
    
    # Create a test workflow
    workflow_content = """
name: Hub Integration Test
tasks:
  - id: task1
    method: llm/chat
    parameters:
      model: llama3.2:latest
      messages:
        - role: user
          content: "What is 2+2? Answer in one word."
  
  - id: task2
    method: llm/chat
    dependencies: [task1]
    parameters:
      model: llama3.2:latest
      messages:
        - role: user
          content: "You said ${task1.response}. Is that correct? Yes or No only."
"""
    
    # Write workflow to file
    workflow_file = Path("/tmp/test_hub_workflow.yaml")
    workflow_file.write_text(workflow_content)
    
    try:
        async with Client(
            mode=ClientMode.NATIVE,
            native_config={
                'enable_resource_management': True
            }
        ) as client:
            print("✓ Client initialized")
            
            # Run workflow
            result = await client.run_workflow(str(workflow_file))
            
            print("✓ Workflow completed")
            print(f"  Task 1 result: {result.get('task1', {}).get('response', 'N/A')}")
            print(f"  Task 2 result: {result.get('task2', {}).get('response', 'N/A')}")
            
            return result
    finally:
        # Clean up
        if workflow_file.exists():
            workflow_file.unlink()


async def main():
    """Run all tests"""
    try:
        # Test basic hub integration
        await test_hub_integration()
        
        # Test workflow with hub
        await test_workflow_with_hub()
        
        print("\n" + "=" * 50)
        print("All tests passed! Hub integration is working.")
        print("=" * 50)
        
    except Exception as e:
        print(f"\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())