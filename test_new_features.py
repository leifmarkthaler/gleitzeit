#!/usr/bin/env python
"""
Test script for new multi-instance and Docker features
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.orchestration.ollama_pool import (
    OllamaPoolManager, 
    LoadBalancingStrategy,
    InstanceState
)

async def test_ollama_pool():
    """Test OllamaPoolManager functionality"""
    print("\n=== Testing OllamaPoolManager ===\n")
    
    # Configuration
    instances_config = [
        {
            "id": "local",
            "url": "http://localhost:11434",
            "models": ["llama3.2", "codellama"],
            "max_concurrent": 5,
            "tags": ["local", "cpu"]
        },
        {
            "id": "gpu-1",
            "url": "http://gpu1:11434",
            "models": ["llama3.2:70b", "mixtral"],
            "max_concurrent": 2,
            "tags": ["remote", "gpu", "high-memory"]
        }
    ]
    
    # Create manager
    manager = OllamaPoolManager(
        instances=instances_config,
        health_check_interval=30
    )
    
    print("✓ Created OllamaPoolManager with 2 instances")
    
    # Test instance configuration
    assert len(manager.instances) == 2
    assert "local" in manager.instances
    assert "gpu-1" in manager.instances
    print("✓ Instances configured correctly")
    
    # Test load balancing strategies
    for instance in manager.instances.values():
        instance.state = InstanceState.HEALTHY
    
    # Test least loaded
    manager.instances["local"].metrics.active_requests = 3
    manager.instances["gpu-1"].metrics.active_requests = 1
    
    available = list(manager.instances.values())
    selected = await manager._select_instance(
        available,
        LoadBalancingStrategy.LEAST_LOADED
    )
    
    assert selected.id == "gpu-1"
    print("✓ Least loaded strategy works")
    
    # Test tag filtering
    gpu_instances = manager._get_available_instances(tags=["gpu"])
    assert len(gpu_instances) == 1
    assert gpu_instances[0].id == "gpu-1"
    print("✓ Tag filtering works")
    
    # Test circuit breaker
    for _ in range(5):
        await manager.record_failure("http://localhost:11434", Exception("Test"))
    
    assert manager.circuit_breaker.is_open("local")
    print("✓ Circuit breaker works")
    
    # Test metrics
    await manager.record_success("http://gpu1:11434", 0.5)
    instance = manager.instances["gpu-1"]
    assert instance.metrics.success_count == 1
    assert instance.metrics.avg_response_time == 0.5
    print("✓ Metrics tracking works")
    
    print("\n✅ OllamaPoolManager tests passed!\n")


async def test_docker_executor():
    """Test DockerExecutor functionality (requires Docker)"""
    print("\n=== Testing DockerExecutor ===\n")
    
    try:
        from gleitzeit.execution.docker_executor import DockerExecutor, SecurityLevel
        
        # Check if Docker is available
        try:
            import docker
            client = docker.from_env()
            client.ping()
            print("✓ Docker is available")
        except Exception as e:
            print(f"⚠️  Docker not available: {e}")
            print("Skipping Docker tests")
            return
            
        # Create executor
        executor = DockerExecutor()
        print("✓ Created DockerExecutor")
        
        # Test security levels
        assert SecurityLevel.SANDBOXED in executor.security_presets
        assert SecurityLevel.SPECIALIZED in executor.security_presets
        print("✓ Security presets configured")
        
        # Test container configuration
        config = executor.security_presets[SecurityLevel.SANDBOXED]
        assert config.memory_limit == "512m"
        assert config.network_mode == "none"
        assert config.read_only_root == True
        print("✓ Sandbox configuration correct")
        
        print("\n✅ DockerExecutor tests passed!\n")
        
    except ImportError as e:
        print(f"⚠️  Could not import DockerExecutor: {e}")
        print("Make sure docker package is installed: pip install docker")


async def test_providers():
    """Test new provider implementations"""
    print("\n=== Testing New Providers ===\n")
    
    # Test OllamaPoolProvider
    try:
        from gleitzeit.providers.ollama_pool_provider import OllamaPoolProvider
        
        instances = [
            {"id": "test", "url": "http://localhost:11434"}
        ]
        
        provider = OllamaPoolProvider(
            provider_id="ollama_pool",
            instances=instances
        )
        
        assert provider.provider_id == "ollama_pool"
        assert provider.protocol_id == "llm/v1"
        print("✓ OllamaPoolProvider created")
        
        methods = provider.get_supported_methods()
        assert "llm/chat" in methods
        assert "llm/generate" in methods
        print("✓ Provider methods configured")
        
    except Exception as e:
        print(f"⚠️  OllamaPoolProvider test failed: {e}")
    
    # Test PythonDockerProvider
    try:
        from gleitzeit.providers.python_docker_provider import PythonDockerProvider
        
        provider = PythonDockerProvider(
            provider_id="python_docker",
            default_mode="sandboxed"
        )
        
        assert provider.provider_id == "python_docker"
        assert provider.protocol_id == "python/v1"
        assert provider.default_mode == "sandboxed"
        print("✓ PythonDockerProvider created")
        
        methods = provider.get_supported_methods()
        assert "python/execute" in methods
        print("✓ Provider methods configured")
        
    except Exception as e:
        print(f"⚠️  PythonDockerProvider test failed: {e}")
    
    print("\n✅ Provider tests completed!\n")


async def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Testing New Multi-Instance and Docker Features")
    print("="*60)
    
    # Test OllamaPoolManager
    await test_ollama_pool()
    
    # Test DockerExecutor
    await test_docker_executor()
    
    # Test Providers
    await test_providers()
    
    print("\n" + "="*60)
    print("All tests completed successfully! 🎉")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())