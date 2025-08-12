#!/usr/bin/env python3
"""
Multiple Local Ollama Hosts Example

This example shows how to configure Gleitzeit to use multiple local Ollama
servers for distributed LLM processing with the unified Socket.IO architecture.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.execution.ollama_endpoint_manager import EndpointConfig, LoadBalancingStrategy


async def setup_multiple_ollama_hosts():
    """
    Configure multiple local Ollama hosts for distributed LLM processing
    """
    
    print("🚀 Multiple Local Ollama Hosts Example")
    print("=" * 50)
    
    # Step 1: Configure multiple local Ollama endpoints
    print("📋 Configuring Ollama endpoints...")
    
    endpoints = [
        # Primary local server (default port)
        EndpointConfig(
            name="local_primary",
            url="http://localhost:11434",
            priority=5,                    # Highest priority
            max_concurrent=8,
            models=["llama3", "llava", "mistral"],  # Preferred models
            tags={"local", "primary", "fast"}
        ),
        
        # Secondary local server (different port)  
        EndpointConfig(
            name="local_secondary", 
            url="http://localhost:11435",  # Different port
            priority=4,
            max_concurrent=6,
            models=["llama3", "codellama"],
            tags={"local", "secondary", "code"}
        ),
        
        # GPU server (if you have one)
        EndpointConfig(
            name="local_gpu",
            url="http://localhost:11436",  # Another port
            priority=6,                    # Highest for GPU
            max_concurrent=10,
            models=["llava", "llama3"],    # Vision + text models
            tags={"local", "gpu", "vision", "fast"}
        ),
        
        # Backup/overflow server
        EndpointConfig(
            name="local_backup",
            url="http://localhost:11437",  # Yet another port
            priority=2,
            max_concurrent=4,
            models=["llama3"],
            tags={"local", "backup"}
        )
    ]
    
    print(f"✅ Configured {len(endpoints)} Ollama endpoints:")
    for endpoint in endpoints:
        print(f"   - {endpoint.name}: {endpoint.url} (priority={endpoint.priority})")
    
    # Step 2: Create cluster with multi-endpoint configuration
    print("\n🏗️ Creating Gleitzeit cluster with multi-endpoint support...")
    
    cluster = GleitzeitCluster(
        # Multi-endpoint configuration
        ollama_endpoints=endpoints,
        ollama_strategy=LoadBalancingStrategy.LEAST_LOADED,  # Best for mixed workloads
        
        # Standard configuration 
        enable_redis=False,      # Simplified for demo
        enable_socketio=False,   # Simplified for demo
        enable_real_execution=False,  # Demo mode
        auto_start_services=False
    )
    
    await cluster.start()
    print("✅ Cluster started with multi-endpoint Ollama support")
    
    # Step 3: Create workflow that uses multiple endpoints
    print("\n📊 Creating multi-endpoint LLM workflow...")
    
    workflow = cluster.create_workflow("Multi-Endpoint Demo", "Distribute tasks across multiple Ollama hosts")
    
    # These tasks will be automatically distributed across your Ollama hosts
    tasks = [
        # Text generation tasks (will route to best available endpoint)
        ("Analysis 1", "Analyze the benefits of distributed AI systems", "llama3"),
        ("Analysis 2", "Explain load balancing in distributed computing", "llama3"), 
        ("Analysis 3", "Describe fault tolerance in distributed systems", "llama3"),
        
        # Code generation task (will prefer endpoints tagged with 'code')
        ("Code Generation", "Write a Python function for distributed task scheduling", "codellama"),
        
        # Vision task (will prefer GPU endpoint if available)
        ("Vision Analysis", "Describe what makes a good user interface", "llava"),
    ]
    
    created_tasks = []
    for name, prompt, model in tasks:
        if model == "llava":
            # Vision task
            task = workflow.add_vision_task(
                name=name,
                prompt=prompt,
                model=model,
                image_path=None  # Would normally have an image path
            )
        else:
            # Text task
            task = workflow.add_text_task(
                name=name,
                prompt=prompt,
                model=model
            )
        created_tasks.append(name)
    
    # Summary task that depends on all others
    workflow.add_text_task(
        name="Summary Report",
        prompt=f"Create a comprehensive summary based on these analyses: " + 
               " ".join([f"{{{task}.result}}" for task in created_tasks[:3]]),  # Only text tasks
        model="llama3",
        dependencies=created_tasks[:3]  # Only depend on text tasks for demo
    )
    
    print(f"✅ Created workflow with {len(workflow.tasks)} tasks")
    
    # Step 4: Show task routing (without execution in demo mode)
    print("\n🎯 Task Routing Preview:")
    for task_name, task in workflow.tasks.items():
        service = task.parameters.service_name
        model = task.parameters.external_parameters.get('model', 'unknown')
        task_type = task.parameters.external_parameters.get('task_type', task.task_type.value)
        print(f"   {task_name}: {model} → {service} ({task_type})")
    
    # Step 5: Simulate endpoint health and load balancing info
    print("\n📊 Multi-Endpoint Features:")
    print("   ⚡ Automatic Load Balancing - Tasks distributed based on current load")
    print("   🔄 Automatic Failover - Failed requests retry on other endpoints") 
    print("   🏥 Health Monitoring - Unhealthy endpoints automatically excluded")
    print("   🎯 Model Affinity - Tasks routed to endpoints with required models")
    print("   📈 Real-time Stats - Monitor performance across all endpoints")
    
    print("\n✅ Multi-endpoint configuration complete!")
    print("\n📋 To use this setup:")
    print("1. Start multiple Ollama servers on different ports:")
    print("   - ollama serve --port 11434  # Primary")
    print("   - ollama serve --port 11435  # Secondary") 
    print("   - ollama serve --port 11436  # GPU server")
    print("   - ollama serve --port 11437  # Backup")
    print("2. Pull models on each server as needed:")
    print("   - ollama pull llama3")
    print("   - ollama pull llava")
    print("   - ollama pull codellama")
    print("3. Enable real execution: enable_real_execution=True")
    print("4. Your workflows will automatically distribute across all healthy endpoints!")
    
    await cluster.stop()
    return True


async def simple_multi_endpoint_example():
    """
    Minimal example for just 2 local Ollama servers
    """
    
    print("\n" + "="*50)
    print("🎯 Simple 2-Server Example")
    print("=" * 50)
    
    # Just 2 local servers - minimal setup
    endpoints = [
        EndpointConfig(
            name="main", 
            url="http://localhost:11434",  # Default port
            priority=5,
            tags={"primary"}
        ),
        EndpointConfig(
            name="backup",
            url="http://localhost:11435",  # Second instance
            priority=3,
            tags={"backup"}
        )
    ]
    
    # Simple cluster configuration
    cluster = GleitzeitCluster(
        ollama_endpoints=endpoints,
        ollama_strategy=LoadBalancingStrategy.LEAST_LOADED,
        enable_real_execution=False  # Change to True for real execution
    )
    
    await cluster.start()
    
    # Simple workflow
    workflow = cluster.create_workflow("Simple Distributed Workflow")
    
    # Add a few tasks that will distribute across both servers
    workflow.add_text_task("Task 1", "What is artificial intelligence?", "llama3")
    workflow.add_text_task("Task 2", "Explain machine learning", "llama3") 
    workflow.add_text_task("Task 3", "Describe neural networks", "llama3")
    
    print("✅ Simple multi-endpoint setup ready!")
    print("   📍 3 tasks will be distributed between 2 Ollama servers")
    print("   ⚡ Load balancing: LEAST_LOADED strategy")
    print("   🔄 Automatic failover if one server fails")
    
    await cluster.stop()
    return True


async def monitoring_example():
    """
    Show how to monitor multiple endpoints
    """
    
    print("\n" + "="*50) 
    print("📊 Multi-Endpoint Monitoring")
    print("=" * 50)
    
    # This would show real stats in a running system
    print("Example endpoint statistics:")
    print("""
    {
        "local_primary": {
            "config": {"url": "http://localhost:11434", "priority": 5},
            "stats": {
                "is_healthy": true,
                "current_load": 2,
                "total_requests": 150,
                "success_rate": 0.98,
                "average_response_time": 1.2,
                "available_models": ["llama3", "llava", "mistral"]
            }
        },
        "local_gpu": {
            "config": {"url": "http://localhost:11436", "priority": 6},
            "stats": {
                "is_healthy": true, 
                "current_load": 1,
                "total_requests": 89,
                "success_rate": 1.0,
                "average_response_time": 0.8,
                "available_models": ["llava", "llama3"]
            }
        }
    }
    """)
    
    print("📋 Monitoring Commands:")
    print("   # Get endpoint health")
    print("   manager = cluster.task_executor.ollama_manager")
    print("   healthy = manager.get_healthy_endpoints()")
    print("   ")
    print("   # Get detailed statistics") 
    print("   stats = manager.get_endpoint_stats()")
    print("   ")
    print("   # Force health check")
    print("   await manager._check_all_endpoints_health()")


async def main():
    """Run all multi-endpoint examples"""
    
    try:
        await setup_multiple_ollama_hosts()
        await simple_multi_endpoint_example()
        await monitoring_example()
        
        print("\n🎉 Multi-Endpoint Examples Complete!")
        return True
        
    except Exception as e:
        print(f"❌ Example failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print(__doc__)
    success = asyncio.run(main())
    sys.exit(0 if success else 1)