#!/usr/bin/env python3
"""
Test resource management with a regular workflow

This demonstrates how resource management works transparently:
1. Set up resource pools with Ollama instances
2. Run a normal workflow (no changes needed)
3. Gleitzeit automatically allocates resources for LLM tasks
"""

import asyncio
import logging
from gleitzeit import Client

logging.basicConfig(level=logging.INFO)


async def main():
    print("=" * 60)
    print("Testing Resource Management with Workflows")
    print("=" * 60)
    
    # Initialize client with resource management
    async with Client(
        mode="native",
        native_config={'enable_resource_management': True}
    ) as client:
        
        print("\n1. Setting up resource pools...")
        
        # Create an Ollama resource pool
        success = await client.create_resource_pool(
            pool_id="ollama-pool",
            resource_type="ollama",
            min_instances=1,
            max_instances=3
        )
        print(f"   Created pool: {success}")
        
        # Register Ollama instances (assuming they're running)
        print("\n2. Registering Ollama instances...")
        
        # Register primary instance
        await client.register_resource(
            pool_id="ollama-pool",
            instance_id="ollama-primary",
            endpoint="http://localhost:11434",
            capabilities=["llama3.2", "llama3.1", "mistral"],
            max_concurrent=2
        )
        print("   Registered primary Ollama at localhost:11434")
        
        # Register secondary instance (if you have one)
        # await client.register_resource(
        #     pool_id="ollama-pool",
        #     instance_id="ollama-secondary",
        #     endpoint="http://localhost:11435",
        #     capabilities=["llama3.2", "codellama"],
        #     max_concurrent=2
        # )
        # print("   Registered secondary Ollama at localhost:11435")
        
        print("\n3. Running workflow (simple_llm_workflow.yaml)...")
        print("   Note: The workflow doesn't need any changes!")
        print("   Gleitzeit will automatically allocate resources for LLM tasks.\n")
        
        # Run a standard workflow - resource allocation happens automatically
        try:
            results = await client.run_workflow("examples/simple_llm_workflow.yaml")
            
            print("\n4. Workflow Results:")
            for task_id, result in results.items():
                if hasattr(result, 'result'):
                    print(f"\n   Task {task_id}:")
                    if isinstance(result.result, dict):
                        if 'response' in result.result:
                            print(f"   Response: {result.result['response'][:200]}...")
                        elif 'content' in result.result:
                            print(f"   Content: {result.result['content'][:200]}...")
                        else:
                            print(f"   Result: {result.result}")
                    else:
                        print(f"   Result: {result.result}")
        except Exception as e:
            print(f"   Workflow failed: {e}")
        
        # Check resource metrics
        print("\n5. Resource Utilization:")
        metrics = await client.get_resource_metrics()
        if metrics and "allocator" in metrics:
            allocator = metrics["allocator"]
            print(f"   Total instances: {allocator['total_instances']}")
            print(f"   Total allocations: {allocator['stats']['total_allocations']}")
            print(f"   Successful allocations: {allocator['stats']['successful_allocations']}")
            
            # Show per-pool metrics
            for pool_id, pool_metrics in allocator.get("pool_metrics", {}).items():
                print(f"\n   Pool '{pool_id}':")
                print(f"     Total requests: {pool_metrics['requests']['total']}")
                print(f"     Active requests: {pool_metrics['requests']['active']}")


if __name__ == "__main__":
    print("\nIMPORTANT: Make sure Ollama is running!")
    print("Start it with: ollama serve\n")
    
    asyncio.run(main())
    
    print("\n✅ Test completed!")