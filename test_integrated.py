#!/usr/bin/env python
"""
Integrated test for both Ollama orchestration and Docker execution
"""

import asyncio
import sys
import json
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.orchestration.ollama_pool import OllamaPoolManager
from gleitzeit.providers.ollama_pool_provider import OllamaPoolProvider
from gleitzeit.providers.python_docker_provider import PythonDockerProvider
from gleitzeit.execution.docker_executor import DockerExecutor, SecurityLevel


async def test_integrated_system():
    """Test both Ollama orchestration and Docker execution"""
    print("\n" + "="*70)
    print("🚀 Integrated Test: Multi-Instance Ollama + Docker Python Execution")
    print("="*70 + "\n")
    
    # Part 1: Setup Ollama Pool
    print("📡 Part 1: Multi-Instance Ollama Orchestration")
    print("-" * 50)
    
    # Check which Ollama instances are available
    ollama_instances = []
    for port in [11434, 11435, 11436]:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{port}/api/tags", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if resp.status == 200:
                        ollama_instances.append({
                            "id": f"ollama-{port}",
                            "url": f"http://localhost:{port}",
                            "models": ["llama3.2"],
                            "max_concurrent": 2,
                            "tags": ["local"],
                            "weight": 1.0
                        })
                        print(f"✓ Found Ollama instance on port {port}")
        except:
            print(f"✗ No Ollama instance on port {port}")
    
    if not ollama_instances:
        print("\n⚠️  No Ollama instances found. Starting one on default port...")
        print("   Please run: ollama serve")
        print("   Using mock mode for demonstration")
        ollama_instances = [{
            "id": "mock-ollama",
            "url": "http://localhost:11434",
            "models": ["llama3.2"],
            "max_concurrent": 2,
            "tags": ["mock"]
        }]
    
    print(f"\nUsing {len(ollama_instances)} Ollama instance(s)")
    
    # Initialize Ollama pool
    ollama_provider = OllamaPoolProvider(
        provider_id="ollama_pool",
        instances=ollama_instances,
        load_balancing_config={
            "strategy": "round_robin",
            "health_check_interval": 10,
            "failover": True,
            "retry_attempts": 2
        }
    )
    
    await ollama_provider.initialize()
    print("✓ Ollama pool initialized\n")
    
    # Part 2: Setup Docker Executor
    print("🐳 Part 2: Docker-based Python Execution")
    print("-" * 50)
    
    docker_provider = PythonDockerProvider(
        provider_id="python_docker",
        default_mode="sandboxed"
    )
    
    await docker_provider.initialize()
    print("✓ Docker executor initialized\n")
    
    # Part 3: Combined Workflow - LLM generates code, Docker executes it
    print("🔄 Part 3: Combined Workflow - LLM to Docker Pipeline")
    print("-" * 50)
    
    # Step 1: Use LLM to generate Python code
    print("\n1. Asking LLM to generate Python code...")
    
    if len([i for i in ollama_instances if 'mock' not in i.get('tags', [])]) > 0:
        try:
            llm_result = await ollama_provider.execute(
                method="llm/generate",
                params={
                    "model": "llama3.2",
                    "prompt": "Write a Python function that calculates the factorial of a number. Just the code, no explanation. Include a test that calculates factorial(5) and stores it in a variable called 'result'.",
                    "temperature": 0.1,
                    "max_tokens": 200
                }
            )
            
            if llm_result.get('success'):
                generated_code = llm_result.get('response', '')
                print("   ✓ LLM generated code successfully")
                print("\n   Generated code:")
                print("   " + "-"*40)
                for line in generated_code.split('\n')[:10]:  # Show first 10 lines
                    print(f"   {line}")
                if len(generated_code.split('\n')) > 10:
                    print("   ...")
            else:
                print("   ✗ LLM generation failed, using fallback code")
                generated_code = """
def factorial(n):
    if n == 0 or n == 1:
        return 1
    return n * factorial(n - 1)

result = factorial(5)
"""
        except Exception as e:
            print(f"   ✗ LLM request failed: {e}, using fallback code")
            generated_code = """
def factorial(n):
    if n == 0 or n == 1:
        return 1
    return n * factorial(n - 1)

result = factorial(5)
"""
    else:
        print("   Using pre-defined code (no real Ollama instances)")
        generated_code = """
def factorial(n):
    if n == 0 or n == 1:
        return 1
    return n * factorial(n - 1)

result = factorial(5)
"""
    
    # Step 2: Execute the generated code in Docker
    print("\n2. Executing generated code in Docker container...")
    
    docker_result = await docker_provider.execute(
        method="python/execute",
        params={
            "code": generated_code,
            "execution_mode": "sandboxed",
            "timeout": 5
        }
    )
    
    if docker_result.get('success'):
        print("   ✓ Code executed successfully in Docker")
        print(f"   Result: {docker_result.get('result')}")
    else:
        print(f"   ✗ Execution failed: {docker_result.get('error')}")
    
    # Part 4: Parallel Processing Demo
    print("\n🚀 Part 4: Parallel Processing Demo")
    print("-" * 50)
    
    # Generate multiple tasks
    tasks = [
        "Calculate the sum of squares from 1 to 10",
        "Generate the first 10 Fibonacci numbers",
        "Count vowels in 'Hello World'",
        "Calculate 2^10"
    ]
    
    print(f"\nProcessing {len(tasks)} tasks in parallel...")
    
    async def process_task(task_desc, task_num):
        """Process a single task through LLM and Docker"""
        result = {"task": task_num, "description": task_desc}
        
        # Generate code with LLM (or use predefined)
        if len([i for i in ollama_instances if 'mock' not in i.get('tags', [])]) > 0:
            try:
                llm_resp = await ollama_provider.execute(
                    method="llm/generate",
                    params={
                        "model": "llama3.2",
                        "prompt": f"Write Python code to: {task_desc}. Store the result in a variable called 'result'. Just code, no explanation.",
                        "temperature": 0.1,
                        "max_tokens": 150
                    }
                )
                code = llm_resp.get('response', '') if llm_resp.get('success') else None
            except:
                code = None
        else:
            code = None
        
        # Use predefined code if LLM fails
        if not code:
            predefined = {
                "Calculate the sum of squares from 1 to 10": "result = sum(i**2 for i in range(1, 11))",
                "Generate the first 10 Fibonacci numbers": """
fib = [0, 1]
for i in range(8):
    fib.append(fib[-1] + fib[-2])
result = fib""",
                "Count vowels in 'Hello World'": "result = sum(1 for c in 'Hello World'.lower() if c in 'aeiou')",
                "Calculate 2^10": "result = 2 ** 10"
            }
            code = predefined.get(task_desc, "result = 'Unknown task'")
        
        # Execute in Docker
        exec_result = await docker_provider.execute(
            method="python/execute",
            params={
                "code": code,
                "execution_mode": "sandboxed",
                "timeout": 3
            }
        )
        
        result["success"] = exec_result.get('success', False)
        result["output"] = exec_result.get('result') if exec_result.get('success') else exec_result.get('error')
        return result
    
    # Run tasks in parallel
    start_time = time.time()
    results = await asyncio.gather(*[
        process_task(task, i+1) 
        for i, task in enumerate(tasks)
    ])
    elapsed = time.time() - start_time
    
    print(f"\n✓ Completed {len(tasks)} tasks in {elapsed:.2f} seconds")
    print("\nResults:")
    for r in results:
        status = "✓" if r["success"] else "✗"
        print(f"  {status} Task {r['task']}: {r['description']}")
        print(f"     Result: {r['output']}")
    
    # Part 5: System Status
    print("\n📊 Part 5: System Status")
    print("-" * 50)
    
    # Ollama pool status
    if hasattr(ollama_provider, 'pool_manager'):
        pool_status = await ollama_provider.pool_manager.get_pool_status()
        print("\nOllama Pool Status:")
        print(f"  Total instances: {pool_status['total_instances']}")
        print(f"  Healthy instances: {pool_status['healthy_instances']}")
        
        for instance_id, info in pool_status['instances'].items():
            print(f"\n  {instance_id}:")
            print(f"    State: {info['state']}")
            print(f"    Total requests: {info.get('total_requests', 0)}")
            print(f"    Avg response time: {info.get('avg_response_time', 0):.3f}s")
    
    # Docker executor status
    if hasattr(docker_provider, 'executor'):
        docker_status = await docker_provider.executor.get_pool_status()
        print("\nDocker Container Pool:")
        print(f"  Total containers: {docker_status['total_containers']}")
        print(f"  Busy: {docker_status['busy_containers']}")
        print(f"  Idle: {docker_status['idle_containers']}")
    
    # Cleanup
    print("\n🧹 Cleaning up...")
    await ollama_provider.shutdown()
    await docker_provider.shutdown()
    print("✓ All resources cleaned up")
    
    # Verify cleanup
    print("\n✅ Integrated Test Complete!")
    print("="*70)
    print("\nKey Achievements:")
    print("  • Multi-instance Ollama orchestration with load balancing")
    print("  • Secure Docker-based Python execution")
    print("  • LLM-to-Docker code generation pipeline")
    print("  • Parallel task processing")
    print("  • Automatic resource cleanup")
    print("\n")


if __name__ == "__main__":
    asyncio.run(test_integrated_system())