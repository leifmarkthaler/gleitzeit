#!/usr/bin/env python3
"""
Multi-Endpoint Ollama Demo

Demonstrates how to configure and use multiple Ollama endpoints
with load balancing, model routing, and health monitoring.
"""

import asyncio
import sys
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.execution.ollama_endpoint_manager import (
    EndpointConfig, LoadBalancingStrategy, OllamaEndpointManager
)


async def demo_basic_multi_endpoint():
    """Basic demonstration of multiple Ollama endpoints"""
    
    print("🔄 Basic Multi-Endpoint Demo")
    print("=" * 40)
    
    # Configure multiple Ollama endpoints
    endpoints = [
        EndpointConfig(
            name="main_server",
            url="http://localhost:11434",
            priority=3,
            max_concurrent=5,
            tags={"primary", "fast"}
        ),
        EndpointConfig(
            name="backup_server",
            url="http://localhost:11435",  # Different port
            priority=2,
            max_concurrent=3,
            tags={"backup", "secondary"}
        ),
        EndpointConfig(
            name="gpu_server",
            url="http://gpu-server:11434",  # Remote server
            priority=4,
            max_concurrent=10,
            tags={"gpu", "fast", "vision"},
            models=["llava", "codellama"]  # Preferred models
        )
    ]
    
    # Create cluster with multi-endpoint configuration
    cluster = GleitzeitCluster(
        enable_real_execution=True,
        enable_redis=False,  # Simplified for demo
        enable_socketio=False,
        ollama_endpoints=endpoints,
        ollama_strategy=LoadBalancingStrategy.LEAST_LOADED
    )
    
    try:
        await cluster.start()
        print("✅ Cluster started with multi-endpoint support")
        
        # Show endpoint status
        if cluster.task_executor and cluster.task_executor._multi_endpoint_mode:
            endpoint_stats = cluster.task_executor.ollama_manager.get_endpoint_stats()
            
            print(f"\n📊 Endpoint Status:")
            for name, info in endpoint_stats.items():
                config = info["config"]
                stats = info["stats"]
                
                status = "🟢 Healthy" if stats["is_healthy"] else "🔴 Unhealthy"
                print(f"   {name}: {status}")
                print(f"      URL: {config['url']}")
                print(f"      Priority: {config['priority']}")
                print(f"      Tags: {config['tags']}")
                print(f"      Load: {stats['current_load']}/{config['max_concurrent']}")
                print(f"      Success Rate: {stats['success_rate']:.1%}")
                print()
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await cluster.stop()


async def demo_load_balancing_strategies():
    """Demonstrate different load balancing strategies"""
    
    print("⚖️  Load Balancing Strategies Demo")
    print("=" * 40)
    
    # Simple endpoint configuration for testing
    endpoints = [
        EndpointConfig(name="server1", url="http://localhost:11434", priority=1),
        EndpointConfig(name="server2", url="http://localhost:11435", priority=2),
        EndpointConfig(name="server3", url="http://localhost:11436", priority=3),
    ]
    
    strategies = [
        LoadBalancingStrategy.ROUND_ROBIN,
        LoadBalancingStrategy.LEAST_LOADED,
        LoadBalancingStrategy.FASTEST_RESPONSE,
        LoadBalancingStrategy.MODEL_AFFINITY
    ]
    
    for strategy in strategies:
        print(f"🔄 Testing {strategy.value} strategy:")
        
        manager = OllamaEndpointManager(
            endpoints=endpoints,
            strategy=strategy,
            health_check_interval=0  # Disable for demo
        )
        
        try:
            await manager.start()
            
            # Simulate endpoint selection
            print("   Endpoint selections for 5 requests:")
            for i in range(5):
                selected = manager.select_endpoint(model="llama3")
                if selected:
                    print(f"     Request {i+1}: {selected}")
                else:
                    print(f"     Request {i+1}: No healthy endpoint")
        
        except Exception as e:
            print(f"   ❌ Strategy test failed: {e}")
        
        finally:
            await manager.stop()
        
        print()


async def demo_model_routing():
    """Demonstrate model-specific endpoint routing"""
    
    print("🎯 Model-Specific Routing Demo")
    print("=" * 40)
    
    # Configure endpoints with model preferences
    endpoints = [
        EndpointConfig(
            name="general_server",
            url="http://localhost:11434",
            models=None,  # Can handle any model
            tags={"general"}
        ),
        EndpointConfig(
            name="vision_server", 
            url="http://vision-server:11434",
            models=["llava", "bakllava"],  # Vision models only
            tags={"vision", "gpu"}
        ),
        EndpointConfig(
            name="code_server",
            url="http://code-server:11434", 
            models=["codellama", "starcoder"],  # Code models only
            tags={"coding"}
        )
    ]
    
    manager = OllamaEndpointManager(
        endpoints=endpoints,
        strategy=LoadBalancingStrategy.MODEL_AFFINITY,
        health_check_interval=0
    )
    
    try:
        await manager.start()
        
        # Test different model routing
        test_models = ["llama3", "llava", "codellama", "mistral"]
        
        print("🔍 Model routing decisions:")
        for model in test_models:
            selected = manager.select_endpoint(model=model)
            if selected:
                endpoint_config = manager.endpoints[selected]
                preferred_models = endpoint_config.models or ["any"]
                print(f"   {model}: → {selected} (handles: {preferred_models})")
            else:
                print(f"   {model}: → No suitable endpoint")
        
        print()
        
        # Test tag-based routing
        print("🏷️  Tag-based routing:")
        tag_tests = [
            {"vision"},
            {"coding"}, 
            {"gpu"},
            {"general"}
        ]
        
        for tags in tag_tests:
            selected = manager.select_endpoint(tags=tags)
            if selected:
                endpoint_tags = manager.endpoints[selected].tags
                print(f"   Tags {tags}: → {selected} (tags: {endpoint_tags})")
            else:
                print(f"   Tags {tags}: → No matching endpoint")
    
    except Exception as e:
        print(f"❌ Routing demo failed: {e}")
    
    finally:
        await manager.stop()
    
    print()


async def demo_cluster_usage():
    """Show how to use multi-endpoint cluster for actual workflows"""
    
    print("🚀 Multi-Endpoint Cluster Usage")
    print("=" * 40)
    
    # Real-world endpoint configuration
    endpoints = [
        EndpointConfig(
            name="local_primary",
            url="http://localhost:11434",
            priority=3,
            max_concurrent=5,
            tags={"local", "primary"}
        ),
        # Note: These endpoints may not be available, but show the configuration
        EndpointConfig(
            name="cloud_backup",
            url="http://cloud-ollama:11434", 
            priority=2,
            max_concurrent=10,
            tags={"cloud", "backup"}
        )
    ]
    
    cluster = GleitzeitCluster(
        ollama_endpoints=endpoints,
        ollama_strategy=LoadBalancingStrategy.LEAST_LOADED,
        enable_redis=False,
        enable_socketio=False
    )
    
    try:
        await cluster.start()
        
        # Create and execute workflow
        workflow = cluster.create_workflow("multi_endpoint_test", "Test multi-endpoint routing")
        
        # Add tasks that will be distributed across endpoints
        task1 = workflow.add_text_task(
            "analysis_1",
            "Explain the benefits of distributed AI systems",
            "llama3"
        )
        
        task2 = workflow.add_text_task(
            "analysis_2", 
            "Compare centralized vs distributed architectures",
            "llama3"
        )
        
        print("📋 Executing workflow with automatic endpoint selection...")
        
        # Execute workflow - tasks will be automatically routed to best endpoints
        result = await cluster.execute_workflow(workflow)
        
        print(f"✅ Workflow completed: {result.status.value}")
        print(f"📊 Tasks completed: {result.completed_tasks}")
        
        # Show which endpoints were used (if available in logs)
        if hasattr(cluster.task_executor, 'ollama_manager'):
            stats = cluster.task_executor.ollama_manager.get_endpoint_stats()
            print(f"\n📈 Endpoint Usage:")
            for name, info in stats.items():
                requests = info["stats"]["total_requests"] 
                if requests > 0:
                    print(f"   {name}: {requests} requests")
    
    except Exception as e:
        print(f"❌ Cluster usage demo failed: {e}")
        print("💡 This is expected if Ollama endpoints are not running")
    
    finally:
        await cluster.stop()


async def demo_runtime_endpoint_management():
    """Demonstrate adding/removing endpoints at runtime"""
    
    print("🔧 Runtime Endpoint Management")
    print("=" * 40)
    
    # Start with minimal configuration
    initial_endpoints = [
        EndpointConfig(
            name="initial_server",
            url="http://localhost:11434"
        )
    ]
    
    manager = OllamaEndpointManager(
        endpoints=initial_endpoints,
        health_check_interval=0
    )
    
    try:
        await manager.start()
        print(f"📊 Started with {len(manager.endpoints)} endpoint(s)")
        
        # Add endpoint at runtime
        new_endpoint = EndpointConfig(
            name="runtime_server",
            url="http://localhost:11435",
            tags={"runtime", "added"}
        )
        
        manager.add_endpoint(new_endpoint)
        print(f"➕ Added endpoint: {new_endpoint.name}")
        print(f"📊 Now have {len(manager.endpoints)} endpoint(s)")
        
        # List all endpoints
        print("\n📋 Current endpoints:")
        for name, config in manager.endpoints.items():
            print(f"   • {name}: {config.url}")
        
        # Remove endpoint
        manager.remove_endpoint("runtime_server")
        print(f"\n➖ Removed endpoint: runtime_server") 
        print(f"📊 Back to {len(manager.endpoints)} endpoint(s)")
    
    except Exception as e:
        print(f"❌ Runtime management demo failed: {e}")
    
    finally:
        await manager.stop()


async def main():
    """Run all multi-endpoint demonstrations"""
    
    print("🚀 Multi-Endpoint Ollama System Demo")
    print("=" * 60)
    print()
    
    demos = [
        demo_basic_multi_endpoint,
        demo_load_balancing_strategies,
        demo_model_routing,
        demo_runtime_endpoint_management,
        demo_cluster_usage
    ]
    
    for demo in demos:
        try:
            await demo()
        except Exception as e:
            print(f"💥 {demo.__name__} crashed: {e}")
        
        print("-" * 60)
        print()
    
    print("🎯 Multi-Endpoint System Features:")
    print("✅ Multiple Ollama server support")
    print("✅ Intelligent load balancing (4 strategies)")  
    print("✅ Model-aware endpoint routing")
    print("✅ Tag-based endpoint selection")
    print("✅ Automatic failover and health monitoring")
    print("✅ Runtime endpoint management")
    print("✅ Priority-based selection")
    print("✅ Concurrent request tracking")
    print()
    print("💡 Configure multiple endpoints for production scaling!")


if __name__ == "__main__":
    asyncio.run(main())