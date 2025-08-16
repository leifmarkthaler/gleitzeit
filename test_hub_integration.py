"""
Test hub integration with refactored providers
"""
import asyncio
import logging
from pathlib import Path

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from gleitzeit.hub.ollama_hub import OllamaHub, OllamaConfig
from gleitzeit.hub.docker_hub import DockerHub, DockerConfig
from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.hub.base import ResourceType
from gleitzeit.providers.ollama_pool_provider_v2 import OllamaPoolProviderV2
from gleitzeit.providers.python_docker_provider_v2 import PythonDockerProviderV2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_shared_hub_architecture():
    """Test providers sharing the same hub instances"""
    
    print("\n" + "="*60)
    print("Testing Shared Hub Architecture")
    print("="*60)
    
    # Create shared hubs
    ollama_hub = OllamaHub(
        hub_id="shared-ollama-hub",
        auto_discover=True
    )
    
    docker_hub = DockerHub(
        hub_id="shared-docker-hub"
    )
    
    # Create resource manager
    resource_manager = ResourceManager()
    await resource_manager.add_hub("ollama", ollama_hub)
    await resource_manager.add_hub("docker", docker_hub)
    
    try:
        # Start hubs
        print("\n1. Starting shared hubs...")
        await ollama_hub.start()
        await docker_hub.start()
        print("✅ Hubs started")
        
        # Create multiple providers sharing the same hubs
        print("\n2. Creating providers with shared hubs...")
        
        # Two Ollama providers sharing the same hub
        ollama_provider_1 = OllamaPoolProviderV2(
            provider_id="ollama-provider-1",
            hub=ollama_hub  # Shared hub
        )
        
        ollama_provider_2 = OllamaPoolProviderV2(
            provider_id="ollama-provider-2",
            hub=ollama_hub  # Same shared hub
        )
        
        # Two Python providers sharing the same Docker hub
        python_provider_1 = PythonDockerProviderV2(
            provider_id="python-provider-1",
            hub=docker_hub  # Shared hub
        )
        
        python_provider_2 = PythonDockerProviderV2(
            provider_id="python-provider-2",
            hub=docker_hub  # Same shared hub
        )
        
        # Initialize providers (they won't start new hubs)
        await ollama_provider_1.initialize()
        await ollama_provider_2.initialize()
        await python_provider_1.initialize()
        await python_provider_2.initialize()
        
        print("✅ Providers initialized with shared hubs")
        
        # Test Ollama providers with shared resources
        print("\n3. Testing Ollama providers with shared hub...")
        
        # Both providers should see the same instances
        status1 = await ollama_provider_1.get_status()
        status2 = await ollama_provider_2.get_status()
        
        print(f"Provider 1 hub: {status1['hub_id']}")
        print(f"Provider 2 hub: {status2['hub_id']}")
        print(f"Same hub: {status1['hub_id'] == status2['hub_id']}")
        
        # Execute on provider 1
        try:
            result1 = await ollama_provider_1.execute(
                method="llm/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Say hello in one word",
                    "max_tokens": 10
                }
            )
            print(f"✅ Provider 1 generated: {result1.get('response', 'N/A')}")
        except Exception as e:
            print(f"⚠️ Ollama generation skipped: {e}")
        
        # Test Python providers with shared Docker hub
        print("\n4. Testing Python providers with shared hub...")
        
        # Execute Python code through both providers
        code = """
import sys
result = f"Python {sys.version.split()[0]} running in container"
"""
        
        result1 = await python_provider_1.execute(
            method="python/execute",
            params={
                "code": code,
                "execution_mode": "sandboxed"
            }
        )
        
        result2 = await python_provider_2.execute(
            method="python/execute",
            params={
                "code": "result = 'Hello from provider 2'",
                "execution_mode": "sandboxed"
            }
        )
        
        print(f"✅ Provider 1 result: {result1.get('result', result1.get('stdout', ''))}")
        print(f"✅ Provider 2 result: {result2.get('result', result2.get('stdout', ''))}")
        
        # Check resource sharing
        print("\n5. Checking resource sharing...")
        
        # Get hub metrics to see shared resource usage
        ollama_metrics = await ollama_hub.get_metrics_summary()
        docker_metrics = await docker_hub.get_metrics_summary()
        
        print(f"Ollama hub instances: {ollama_metrics.get('total_instances', 0)}")
        print(f"Docker hub containers: {docker_metrics.get('total_instances', 0)}")
        
        # Test resource manager allocation
        print("\n6. Testing resource manager...")
        
        # Allocate Ollama resource
        ollama_resource = await resource_manager.allocate_resource(
            resource_type=ResourceType.OLLAMA,
            requirements={"model": "llama3.2"}
        )
        if ollama_resource:
            print(f"✅ Allocated Ollama resource: {ollama_resource.id}")
        
        # Allocate Docker resource
        docker_resource = await resource_manager.allocate_resource(
            resource_type=ResourceType.DOCKER,
            requirements={"image": "python:3.11-slim"}
        )
        if docker_resource:
            print(f"✅ Allocated Docker resource: {docker_resource.id}")
        
        # Get overall status
        print("\n7. Overall system status:")
        manager_metrics = await resource_manager.get_global_metrics()
        
        print(f"Total hubs: {manager_metrics['total_hubs']}")
        print(f"Total resources: {manager_metrics['total_resources']}")
        if 'resources_by_type' in manager_metrics:
            print(f"Resources by type: {manager_metrics['resources_by_type']}")
        if 'resources_by_status' in manager_metrics:
            print(f"Resources by status: {dict(manager_metrics['resources_by_status'])}")
        
    finally:
        # Cleanup
        print("\n8. Cleaning up...")
        
        # Shutdown providers (won't stop shared hubs)
        if 'ollama_provider_1' in locals():
            await ollama_provider_1.shutdown()
        if 'ollama_provider_2' in locals():
            await ollama_provider_2.shutdown()
        if 'python_provider_1' in locals():
            await python_provider_1.shutdown()
        if 'python_provider_2' in locals():
            await python_provider_2.shutdown()
        
        # Stop shared hubs
        await ollama_hub.stop()
        await docker_hub.stop()
        
        print("✅ Cleanup complete")


async def test_dedicated_hub_architecture():
    """Test providers with dedicated hubs"""
    
    print("\n" + "="*60)
    print("Testing Dedicated Hub Architecture")
    print("="*60)
    
    # Create providers with their own dedicated hubs
    ollama_provider = OllamaPoolProviderV2(
        provider_id="ollama-dedicated",
        auto_discover=True
        # No hub parameter - will create its own
    )
    
    python_provider = PythonDockerProviderV2(
        provider_id="python-dedicated"
        # No hub parameter - will create its own
    )
    
    try:
        # Initialize providers (will start their own hubs)
        print("\n1. Initializing providers with dedicated hubs...")
        await ollama_provider.initialize()
        await python_provider.initialize()
        print("✅ Providers initialized with dedicated hubs")
        
        # Check that each has its own hub
        ollama_status = await ollama_provider.get_status()
        python_status = await python_provider.get_status()
        
        print(f"\nOllama provider hub: {ollama_status['hub_id']}")
        print(f"Python provider hub: {python_status['hub_id']}")
        print(f"Owns hub: Ollama={ollama_status['owns_hub']}, Python={python_status['owns_hub']}")
        
        # Test execution
        print("\n2. Testing execution with dedicated hubs...")
        
        # Test Python execution
        result = await python_provider.execute(
            method="python/execute",
            params={
                "code": "result = 2 + 2",
                "execution_mode": "sandboxed"
            }
        )
        print(f"✅ Python result: {result.get('result', 'N/A')}")
        
        # Test batch execution
        print("\n3. Testing batch execution...")
        batch_result = await python_provider.execute(
            method="python/batch",
            params={
                "tasks": [
                    {"code": "result = i * 2", "args": {"i": 1}},
                    {"code": "result = i * 2", "args": {"i": 2}},
                    {"code": "result = i * 2", "args": {"i": 3}}
                ],
                "max_concurrent": 2
            }
        )
        
        print(f"✅ Batch execution: {batch_result['summary']}")
        for i, res in enumerate(batch_result['results']):
            print(f"   Task {i+1}: result={res.get('result', 'N/A')}")
        
    finally:
        # Cleanup
        print("\n4. Cleaning up...")
        
        # Shutdown providers (will stop their dedicated hubs)
        await ollama_provider.shutdown()
        await python_provider.shutdown()
        
        print("✅ Cleanup complete")


async def test_hub_features():
    """Test specific hub features"""
    
    print("\n" + "="*60)
    print("Testing Hub Features")
    print("="*60)
    
    # Test circuit breaker and health monitoring
    hub = DockerHub(hub_id="test-hub")
    
    try:
        await hub.start()
        
        # Create a container
        config = DockerConfig(
            image="python:3.11-slim",
            memory_limit="256m"
        )
        
        instance = await hub.start_instance(config)
        if instance:
            print(f"✅ Created instance: {instance.id}")
            
            # Test health monitoring
            print("\n1. Testing health monitoring...")
            health = await hub.check_health(instance)
            print(f"Health status: {health}")
            
            # Test metrics collection
            print("\n2. Testing metrics collection...")
            
            # Execute some commands to generate metrics
            for i in range(3):
                result = await hub.execute_in_container(
                    instance_id=instance.id,
                    command=f"python -c 'print({i} * 2)'"
                )
                print(f"Execution {i+1}: {result.get('stdout', '').strip()}")
            
            # Get metrics
            metrics = await hub.get_metrics_summary()
            print(f"\nMetrics summary:")
            print(f"  Total requests: {metrics.get('total_requests', 0)}")
            print(f"  Success rate: {metrics.get('success_rate', 0)}%")
            print(f"  Avg response time: {metrics.get('avg_response_time_ms', 0)}ms")
            
            # Test circuit breaker (simulate failures)
            print("\n3. Testing circuit breaker...")
            
            # This should work
            from gleitzeit.common.circuit_breaker import CircuitBreaker
            cb = CircuitBreaker()
            cb_status = cb.get_state(instance.id)
            print(f"Initial circuit state: {cb_status.value}")
            
            # Simulate failures
            for i in range(6):
                cb.record_failure(instance.id)
            
            cb_status = cb.get_state(instance.id)
            print(f"Circuit state after failures: {cb_status.value}")
            
            # Check if circuit is open
            can_execute = cb.can_execute(instance.id)
            print(f"Can execute: {can_execute}")
        
    finally:
        await hub.stop()
        print("\n✅ Hub features test complete")


async def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("HUB ARCHITECTURE INTEGRATION TESTS")
    print("="*60)
    
    try:
        # Test shared hub architecture
        await test_shared_hub_architecture()
        
        # Test dedicated hub architecture
        await test_dedicated_hub_architecture()
        
        # Test hub features
        await test_hub_features()
        
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED SUCCESSFULLY")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())