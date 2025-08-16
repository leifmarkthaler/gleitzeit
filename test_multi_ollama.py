#!/usr/bin/env python
"""
Test multi-instance Ollama load balancing with real instances
"""

import asyncio
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.orchestration.ollama_pool import OllamaPoolManager
from gleitzeit.providers.ollama_pool_provider import OllamaPoolProvider


async def test_real_ollama_instances():
    """Test with real Ollama instances running on different ports"""
    print("\n" + "="*60)
    print("Testing Multi-Instance Ollama Load Balancing")
    print("="*60 + "\n")
    
    # Configuration for 3 real Ollama instances
    instances_config = [
        {
            "id": "ollama-1",
            "url": "http://localhost:11434",
            "models": ["llama3.2"],
            "max_concurrent": 2,
            "tags": ["local", "primary"],
            "weight": 1.0
        },
        {
            "id": "ollama-2", 
            "url": "http://localhost:11435",
            "models": ["llama3.2"],
            "max_concurrent": 2,
            "tags": ["local", "secondary"],
            "weight": 1.0
        },
        {
            "id": "ollama-3",
            "url": "http://localhost:11436",
            "models": ["llama3.2"],
            "max_concurrent": 2,
            "tags": ["local", "tertiary"],
            "weight": 1.0
        }
    ]
    
    # Create pool manager
    pool_manager = OllamaPoolManager(
        instances=instances_config,
        health_check_interval=5
    )
    
    # Initialize and check health
    await pool_manager.initialize()
    print("✓ Pool manager initialized with 3 instances\n")
    
    # Get initial status
    status = await pool_manager.get_pool_status()
    print("Initial Pool Status:")
    print(f"  Total instances: {status['total_instances']}")
    print(f"  Healthy instances: {status['healthy_instances']}")
    for instance_id, info in status['instances'].items():
        print(f"  - {instance_id}: {info['state']} at {info['url']}")
    print()
    
    # Test load balancing strategies
    print("Testing Load Balancing Strategies:\n")
    
    # 1. Round Robin
    print("1. Round Robin Strategy:")
    used_instances = []
    for i in range(6):
        url = await pool_manager.get_instance(strategy="round_robin")
        instance_id = next(k for k, v in pool_manager.instances.items() if v.url == url)
        used_instances.append(instance_id)
        print(f"   Request {i+1} -> {instance_id} ({url})")
        await pool_manager.release_instance(url)
    print(f"   Distribution: {', '.join(used_instances)}\n")
    
    # 2. Least Loaded
    print("2. Least Loaded Strategy:")
    # Simulate different loads
    pool_manager.instances["ollama-1"].metrics.active_requests = 2
    pool_manager.instances["ollama-2"].metrics.active_requests = 0
    pool_manager.instances["ollama-3"].metrics.active_requests = 1
    
    for i in range(3):
        url = await pool_manager.get_instance(strategy="least_loaded")
        instance_id = next(k for k, v in pool_manager.instances.items() if v.url == url)
        print(f"   Request {i+1} -> {instance_id} (load: {pool_manager.instances[instance_id].metrics.active_requests})")
    
    # Reset loads
    for instance in pool_manager.instances.values():
        instance.metrics.active_requests = 0
    print()
    
    # 3. Test actual API calls with provider
    print("3. Testing Actual API Calls with Provider:\n")
    
    provider = OllamaPoolProvider(
        provider_id="ollama_pool",
        instances=instances_config,
        load_balancing_config={
            "strategy": "round_robin",
            "health_check_interval": 5,
            "failover": True,
            "retry_attempts": 3
        }
    )
    
    await provider.initialize()
    print("✓ OllamaPoolProvider initialized\n")
    
    # Make multiple concurrent requests
    print("Making 6 concurrent requests (2 per instance):")
    
    async def make_request(request_id):
        start = time.time()
        try:
            result = await provider.execute(
                method="llm/generate",
                params={
                    "model": "llama3.2",
                    "prompt": f"Say 'Response {request_id}' and nothing else.",
                    "temperature": 0.1,
                    "max_tokens": 10
                }
            )
            elapsed = time.time() - start
            response = result.get("response", "").strip()
            return f"Request {request_id}: {response} (took {elapsed:.2f}s)"
        except Exception as e:
            return f"Request {request_id}: Failed - {e}"
    
    # Launch concurrent requests
    tasks = [make_request(i+1) for i in range(6)]
    results = await asyncio.gather(*tasks)
    
    for result in results:
        print(f"  {result}")
    print()
    
    # Get final pool status
    final_status = await provider.pool_manager.get_pool_status()
    print("Final Pool Metrics:")
    for instance_id, info in final_status['instances'].items():
        print(f"  {instance_id}:")
        print(f"    - Total requests: {info['total_requests']}")
        print(f"    - Avg response time: {info['avg_response_time']:.3f}s")
        print(f"    - Error rate: {info['error_rate']:.1f}%")
        print(f"    - Availability: {info['availability']:.1f}%")
    
    # Test failover
    print("\n4. Testing Failover Mechanism:")
    
    # Simulate instance failure by using wrong URL
    pool_manager.instances["ollama-2"].url = "http://localhost:99999"  # Non-existent
    print("  ✓ Simulated failure of ollama-2")
    
    # Try requests - should failover to working instances
    failed_instance_used = False
    for i in range(3):
        try:
            url = await pool_manager.get_instance(strategy="round_robin")
            if url == "http://localhost:99999":
                failed_instance_used = True
            instance_id = next((k for k, v in pool_manager.instances.items() if v.url == url), "unknown")
            
            # Simulate request
            if url == "http://localhost:99999":
                await pool_manager.record_failure(url, Exception("Connection refused"))
                print(f"  Request {i+1} -> {instance_id} (FAILED, will retry)")
            else:
                await pool_manager.record_success(url, 0.1)
                print(f"  Request {i+1} -> {instance_id} (SUCCESS)")
                
            await pool_manager.release_instance(url)
        except Exception as e:
            print(f"  Request {i+1} failed: {e}")
    
    # Check circuit breaker status
    if pool_manager.circuit_breaker.is_open("ollama-2"):
        print("  ✓ Circuit breaker opened for failed instance")
    
    # Cleanup
    await provider.shutdown()
    await pool_manager.shutdown()
    
    print("\n" + "="*60)
    print("Multi-Instance Testing Complete! 🎉")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_real_ollama_instances())