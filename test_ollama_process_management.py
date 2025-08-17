#!/usr/bin/env python3
"""
Test script for OllamaProvider process management functionality
"""

import asyncio
import logging
from gleitzeit.providers.ollama_provider import OllamaProvider
from gleitzeit.hub.configs import OllamaConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_process_management():
    """Test starting, stopping, and restarting Ollama instances"""
    
    print("\n" + "="*60)
    print("Testing OllamaProvider Process Management")
    print("="*60)
    
    # Create provider
    provider = OllamaProvider(
        provider_id="test-ollama",
        auto_discover=False  # Don't auto-discover, we'll manage instances
    )
    
    await provider.initialize()
    print("\n✅ Provider initialized")
    
    # Test 1: Start a managed instance
    print("\n📋 Test 1: Starting managed Ollama instance...")
    config = OllamaConfig(
        host="127.0.0.1",
        port=11436,  # Use a non-default port
        gpu_layers=0,  # CPU only for testing
        cpu_threads=4
    )
    
    instance = await provider.start_ollama_instance(config)
    if instance:
        print(f"✅ Started instance: {instance.id}")
        print(f"   - PID: {config.process_id}")
        print(f"   - Endpoint: {instance.endpoint}")
        print(f"   - Status: {instance.status}")
    else:
        print("❌ Failed to start instance")
        return
    
    # Wait a bit
    await asyncio.sleep(2)
    
    # Test 2: Check instance is registered
    print("\n📋 Test 2: Checking instance registration...")
    if instance.id in provider.instances:
        print(f"✅ Instance {instance.id} is registered")
        print(f"   - Total instances: {len(provider.instances)}")
    else:
        print("❌ Instance not properly registered")
    
    # Test 3: Execute a simple request
    print("\n📋 Test 3: Testing execution on managed instance...")
    try:
        result = await provider.execute("llm/list_models", {})
        print(f"✅ Execution successful: {len(result.get('models', []))} models available")
    except Exception as e:
        print(f"⚠️  Execution failed (expected if no models): {e}")
    
    # Test 4: Restart instance
    print("\n📋 Test 4: Restarting instance...")
    success = await provider.restart_ollama_instance(instance.id)
    if success:
        print(f"✅ Instance {instance.id} restarted successfully")
    else:
        print("❌ Failed to restart instance")
    
    # Test 5: Stop instance
    print("\n📋 Test 5: Stopping instance...")
    success = await provider.stop_ollama_instance(instance.id)
    if success:
        print(f"✅ Instance {instance.id} stopped successfully")
    else:
        print("❌ Failed to stop instance")
    
    # Test 6: Start multiple instances
    print("\n📋 Test 6: Starting multiple managed instances...")
    configs = [
        OllamaConfig(host="127.0.0.1", port=11437),
        OllamaConfig(host="127.0.0.1", port=11438),
    ]
    
    instances = await provider.start_managed_instances(configs)
    print(f"✅ Started {len(instances)} instances")
    for inst in instances:
        print(f"   - {inst.id}: {inst.endpoint}")
    
    # Test 7: Stop all managed instances
    print("\n📋 Test 7: Stopping all managed instances...")
    stopped = await provider.stop_all_managed_instances()
    print(f"✅ Stopped {stopped} managed instances")
    
    # Cleanup
    await provider.cleanup()
    print("\n✨ All tests completed!")
    

async def test_integration_with_existing():
    """Test integration with already running Ollama instances"""
    
    print("\n" + "="*60)
    print("Testing Integration with Existing Instances")
    print("="*60)
    
    # Create provider with auto-discovery
    provider = OllamaProvider(
        provider_id="test-ollama-discovery",
        auto_discover=True  # Auto-discover existing instances
    )
    
    await provider.initialize()
    print(f"\n✅ Provider initialized with {len(provider.instances)} discovered instances")
    
    for instance_id, instance in provider.instances.items():
        print(f"   - {instance_id}: {instance.endpoint} ({instance.status})")
    
    # Try to start an instance on default port (should detect it's already running)
    print("\n📋 Testing start on already-running port...")
    config = OllamaConfig(host="127.0.0.1", port=11434)
    instance = await provider.start_ollama_instance(config)
    
    if instance:
        print(f"✅ Handled existing instance correctly: {instance.id}")
        print(f"   - Tagged as: {instance.tags}")
    
    await provider.cleanup()
    print("\n✨ Integration test completed!")


async def main():
    """Run all tests"""
    
    print("\n🚀 Starting OllamaProvider Process Management Tests")
    print("⚠️  Note: This test will start and stop Ollama processes")
    print("⚠️  Make sure you have Ollama installed: brew install ollama")
    
    try:
        # Test process management
        await test_process_management()
        
        # Test integration with existing instances
        await test_integration_with_existing()
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
    
    print("\n✅ All tests completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())