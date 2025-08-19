"""
Example demonstrating resource management in Gleitzeit

This example shows how to:
1. Create resource pools
2. Register resource instances
3. Allocate resources to tasks
4. Enable auto-scaling
5. Monitor resource metrics
"""

import asyncio
from gleitzeit import Client


async def main():
    # Initialize client with resource management enabled
    async with Client(
        mode="native",
        native_config={'enable_resource_management': True}
    ) as client:
        
        print("🚀 Resource Management Example\n")
        
        # 1. Create an Ollama resource pool
        print("1. Creating Ollama resource pool...")
        success = await client.create_resource_pool(
            pool_id="ollama-pool",
            resource_type="ollama",
            min_instances=1,
            max_instances=5,
            endpoints=["http://localhost:11434"]  # Initial instance
        )
        print(f"   Pool created: {success}")
        
        # 2. Register additional Ollama instances
        print("\n2. Registering additional Ollama instances...")
        await client.register_resource(
            pool_id="ollama-pool",
            instance_id="ollama-2",
            endpoint="http://localhost:11435",
            resource_type="ollama",
            capabilities=["llama3.2", "codellama", "mistral"],
            max_concurrent=3
        )
        print("   Instance ollama-2 registered")
        
        # 3. Create a Docker pool for Python execution
        print("\n3. Creating Docker resource pool...")
        await client.create_resource_pool(
            pool_id="docker-pool",
            resource_type="docker",
            min_instances=0,
            max_instances=10
        )
        print("   Docker pool created")
        
        # 4. Enable auto-scaling
        print("\n4. Enabling auto-scaling...")
        await client.enable_auto_scaling(
            scale_up_threshold=0.8,   # Scale up at 80% utilization
            scale_down_threshold=0.2  # Scale down at 20% utilization
        )
        print("   Auto-scaling enabled")
        
        # 5. Allocate resources for tasks
        print("\n5. Allocating resources for tasks...")
        
        # Allocate Ollama resource for LLM task
        llm_resource = await client.allocate_resource(
            task_id="llm-task-1",
            resource_type="ollama",
            capabilities=["llama3.2"],
            strategy="least_loaded"
        )
        if llm_resource:
            print(f"   Allocated {llm_resource['id']} for LLM task")
            print(f"   Endpoint: {llm_resource['endpoint']}")
            print(f"   Status: {llm_resource['status']}")
        
        # Allocate another resource
        code_resource = await client.allocate_resource(
            task_id="code-task-1",
            resource_type="ollama",
            capabilities=["codellama"],
            strategy="best_fit"
        )
        if code_resource:
            print(f"   Allocated {code_resource['id']} for code task")
        
        # 6. Get resource metrics
        print("\n6. Resource Metrics:")
        metrics = await client.get_resource_metrics()
        
        if metrics and "allocator" in metrics:
            allocator_metrics = metrics["allocator"]
            print(f"   Total pools: {allocator_metrics['pools']}")
            print(f"   Total instances: {allocator_metrics['total_instances']}")
            print(f"   Available instances: {allocator_metrics['available_instances']}")
            print(f"   Active allocations: {allocator_metrics['active_allocations']}")
            
            # Show pool-specific metrics
            for pool_id, pool_metrics in allocator_metrics.get("pool_metrics", {}).items():
                print(f"\n   Pool '{pool_id}':")
                instances = pool_metrics.get("instances", {})
                print(f"     - Total instances: {instances.get('total', 0)}")
                print(f"     - Available: {instances.get('available', 0)}")
                print(f"     - Busy: {instances.get('busy', 0)}")
        
        # 7. Submit a task that will use allocated resources
        print("\n7. Submitting task with resource requirements...")
        task = await client.submit_task(
            name="Generate Code",
            protocol="llm/v1",
            method="chat",
            params={
                "model": "codellama",
                "messages": [
                    {"role": "user", "content": "Write a Python hello world"}
                ]
            }
        )
        print(f"   Task {task.id} submitted")
        
        # 8. Release resources
        print("\n8. Releasing allocated resources...")
        await client.release_resource("llm-task-1")
        await client.release_resource("code-task-1")
        print("   Resources released")
        
        # Final metrics
        print("\n9. Final Resource Status:")
        final_metrics = await client.get_resource_metrics()
        if final_metrics and "allocator" in final_metrics:
            print(f"   Active allocations: {final_metrics['allocator']['active_allocations']}")
            
            stats = final_metrics['allocator'].get('stats', {})
            if stats:
                print(f"   Total allocations made: {stats.get('total_allocations', 0)}")
                print(f"   Successful allocations: {stats.get('successful_allocations', 0)}")
                print(f"   Failed allocations: {stats.get('failed_allocations', 0)}")
                print(f"   Average wait time: {stats.get('avg_wait_time_ms', 0):.2f}ms")


if __name__ == "__main__":
    print("=" * 60)
    print("Gleitzeit Resource Management Example")
    print("=" * 60)
    
    asyncio.run(main())
    
    print("\n✅ Example completed successfully!")