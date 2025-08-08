#!/usr/bin/env python3
"""
Simple Multi-Endpoint Configuration Example

Shows the easiest way to configure and use multiple Ollama endpoints.
"""

import asyncio
import sys
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.execution.ollama_endpoint_manager import EndpointConfig, LoadBalancingStrategy


async def main():
    print("🚀 Simple Multi-Endpoint Configuration")
    print("=" * 50)
    
    # Method 1: Simple configuration with just URLs
    print("Method 1: Basic configuration")
    endpoints_basic = [
        EndpointConfig(name="primary", url="http://localhost:11434"),
        EndpointConfig(name="secondary", url="http://localhost:11435"),
    ]
    
    # Method 2: Advanced configuration with priorities and tags
    print("Method 2: Advanced configuration")
    endpoints_advanced = [
        EndpointConfig(
            name="local_fast",
            url="http://localhost:11434",
            priority=3,
            max_concurrent=5,
            tags={"local", "fast"}
        ),
        EndpointConfig(
            name="cloud_backup",
            url="http://remote-server:11434",
            priority=2,
            max_concurrent=10,
            tags={"cloud", "backup"}
        ),
        EndpointConfig(
            name="gpu_vision",
            url="http://gpu-server:11434",
            priority=4,
            max_concurrent=8,
            models=["llava", "bakllava"],  # Vision models
            tags={"gpu", "vision"}
        )
    ]
    
    # Create cluster with multi-endpoint support
    cluster = GleitzeitCluster(
        # Use your preferred endpoints
        ollama_endpoints=endpoints_basic,
        
        # Choose load balancing strategy
        ollama_strategy=LoadBalancingStrategy.LEAST_LOADED,
        
        # Disable other components for simplicity
        enable_redis=False,
        enable_socketio=False
    )
    
    try:
        await cluster.start()
        
        # Your existing workflow code works unchanged!
        workflow = cluster.create_workflow("test", "Multi-endpoint test")
        task = workflow.add_text_task("hello", "Say hello", "llama3")
        
        result = await cluster.execute_workflow(workflow)
        print(f"✅ Result: {result.results}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("💡 Make sure at least one Ollama server is running!")
    
    finally:
        await cluster.stop()
    
    print("\n📋 Configuration Options:")
    print("• EndpointConfig(name, url)  # Basic")
    print("• priority: Higher = preferred")  
    print("• max_concurrent: Request limit per endpoint")
    print("• models: Preferred models for this endpoint")
    print("• tags: Labels for endpoint selection")
    print("\n⚖️  Load Balancing Strategies:")
    print("• ROUND_ROBIN: Rotate between endpoints")
    print("• LEAST_LOADED: Use endpoint with fewest active requests") 
    print("• FASTEST_RESPONSE: Use endpoint with best response time")
    print("• MODEL_AFFINITY: Prefer endpoints with target model")


if __name__ == "__main__":
    asyncio.run(main())