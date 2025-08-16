#!/usr/bin/env python
"""
Test the new Resource Hub architecture
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.hub import ResourceManager, ResourceType, ResourceStatus
from gleitzeit.hub.docker_hub import DockerConfig


async def test_resource_hub():
    """Test the unified resource hub system"""
    print("\n" + "="*70)
    print("🎯 Testing Unified Resource Hub Architecture")
    print("="*70 + "\n")
    
    # Create resource manager
    manager = ResourceManager("test-manager")
    
    # 1. Create and configure Ollama hub
    print("1️⃣  Setting up Ollama Hub")
    print("-" * 40)
    
    ollama_hub = await manager.create_ollama_hub(
        hub_id="ollama-main",
        auto_discover=True,  # Will find running instances
        instances=[
            # Can also explicitly add instances
            # {'host': '127.0.0.1', 'port': 11434, 'models': ['llama3.2']}
        ]
    )
    
    print(f"✓ Ollama hub created with auto-discovery")
    
    # 2. Create Docker hub
    print("\n2️⃣  Setting up Docker Hub")
    print("-" * 40)
    
    docker_hub = await manager.create_docker_hub(
        hub_id="docker-main",
        enable_container_reuse=True
    )
    
    print(f"✓ Docker hub created with container reuse")
    
    # 3. Start the manager
    await manager.start()
    print("\n✓ Resource Manager started")
    
    # Wait for health checks to run
    print("⏳ Waiting for health checks...")
    await asyncio.sleep(3)
    
    # 4. Check discovered resources
    print("\n3️⃣  Discovered Resources")
    print("-" * 40)
    
    all_resources = await manager.get_all_resources()
    print(f"Total resources: {len(all_resources)}")
    
    for resource in all_resources:
        print(f"  • {resource.name} ({resource.type.value})")
        print(f"    Status: {resource.status.value}")
        print(f"    Endpoint: {resource.endpoint}")
        print(f"    Tags: {', '.join(resource.tags)}")
    
    # 5. Test Ollama allocation
    print("\n4️⃣  Testing Ollama Resource Allocation")
    print("-" * 40)
    
    ollama_instance = await manager.allocate_resource(
        ResourceType.OLLAMA,
        requirements={
            'capabilities': {'llama3.2'},  # Requires specific model
            'strategy': 'least_loaded'
        }
    )
    
    if ollama_instance:
        print(f"✓ Allocated Ollama instance: {ollama_instance.name}")
        print(f"  Endpoint: {ollama_instance.endpoint}")
        print(f"  Models: {', '.join(ollama_instance.capabilities)}")
    else:
        print("✗ No Ollama instance available")
    
    # 6. Test Docker container creation
    print("\n5️⃣  Testing Docker Container Management")
    print("-" * 40)
    
    # Start a Python container
    docker_config = DockerConfig(
        image="python:3.11-slim",
        name="test-python",
        memory_limit="256m",
        cpu_limit=0.5
    )
    
    try:
        python_container = await docker_hub.start_instance(docker_config)
        print(f"✓ Started Docker container: {python_container.name}")
        print(f"  Image: {docker_config.image}")
        print(f"  Memory: {docker_config.memory_limit}")
        
        # Execute command in container
        result = await docker_hub.execute_in_container(
            python_container.id,
            "python -c 'import sys; print(sys.version)'"
        )
        
        if result['success']:
            print(f"✓ Executed Python in container:")
            print(f"  {result['stdout'].strip()}")
        
    except Exception as e:
        print(f"✗ Docker operations require Docker to be running: {e}")
    
    # 7. Get global metrics
    print("\n6️⃣  Global Resource Metrics")
    print("-" * 40)
    
    metrics = await manager.get_global_metrics()
    
    print(f"Total hubs: {metrics['total_hubs']}")
    print(f"Total resources: {metrics['total_resources']}")
    print(f"\nResources by type:")
    for rtype, count in metrics['resources_by_type'].items():
        print(f"  • {rtype}: {count}")
    
    print(f"\nResources by status:")
    for status, count in metrics['resources_by_status'].items():
        print(f"  • {status}: {count}")
    
    print(f"\nAllocations:")
    print(f"  • Active: {metrics['allocations']['active']}")
    print(f"  • Total: {metrics['allocations']['total']}")
    print(f"  • Failures: {metrics['allocations']['failures']}")
    
    # 8. Hub-specific operations
    print("\n7️⃣  Hub-Specific Operations")
    print("-" * 40)
    
    # Check Ollama hub status
    ollama_status = await ollama_hub.get_status()
    print(f"\nOllama Hub Status:")
    print(f"  • Running: {ollama_status['running']}")
    print(f"  • Healthy instances: {ollama_status['instances']['healthy']}")
    print(f"  • Health check interval: {ollama_status['config']['health_check_interval']}s")
    
    # Check model distribution
    if hasattr(ollama_hub, 'get_model_distribution'):
        model_dist = await ollama_hub.get_model_distribution()
        if model_dist:
            print(f"\nModel Distribution:")
            for model, instances in model_dist.items():
                print(f"  • {model}: {', '.join(instances)}")
    
    # 9. Test scaling
    print("\n8️⃣  Testing Resource Scaling")
    print("-" * 40)
    
    if docker_hub:
        print("Scaling Docker hub to 2 instances...")
        try:
            scaled_instances = await manager.scale_hub(
                "docker-main",
                target_instances=2,
                config_template=DockerConfig(
                    image="alpine:latest",
                    name="scaled-container"
                )
            )
            print(f"✓ Scaled to {len(scaled_instances)} instances")
        except Exception as e:
            print(f"✗ Scaling failed: {e}")
    
    # 10. Cleanup
    print("\n9️⃣  Cleanup")
    print("-" * 40)
    
    # Release allocations
    for alloc_id in list(manager.allocations.keys()):
        await manager.release_allocation(alloc_id)
        print(f"✓ Released allocation: {alloc_id}")
    
    # Stop manager (will stop all hubs)
    await manager.stop()
    print("✓ Resource Manager stopped")
    
    print("\n" + "="*70)
    print("✅ Resource Hub Test Complete!")
    print("="*70)
    print("\nKey Features Demonstrated:")
    print("  • Unified resource management across different types")
    print("  • Automatic discovery of Ollama instances")
    print("  • Docker container lifecycle management")
    print("  • Resource allocation with requirements")
    print("  • Global metrics and monitoring")
    print("  • Hub-specific operations")
    print("  • Resource scaling")
    print("\n")


if __name__ == "__main__":
    asyncio.run(test_resource_hub())