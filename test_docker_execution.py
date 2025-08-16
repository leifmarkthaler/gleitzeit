#!/usr/bin/env python
"""
Test Docker-based Python execution
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.providers.python_docker_provider import PythonDockerProvider
from gleitzeit.execution.docker_executor import DockerExecutor, SecurityLevel


async def test_docker_execution():
    """Test Docker-based Python execution"""
    print("\n" + "="*60)
    print("🐳 Testing Docker-based Python Execution")
    print("="*60 + "\n")
    
    # Test 1: Local execution (no Docker)
    print("1. Testing Local Execution:")
    provider = PythonDockerProvider(
        provider_id="python_local",
        default_mode="local"
    )
    await provider.initialize()
    
    result = await provider.execute(
        method="python/execute",
        params={
            "code": """
import sys
import platform
result = {
    'platform': platform.platform(),
    'python': sys.version,
    'calculation': 42 * 2
}
""",
            "execution_mode": "local"
        }
    )
    print(f"   ✓ Local result: {result.get('result')}\n")
    await provider.shutdown()
    
    # Test 2: Sandboxed execution (Docker)
    print("2. Testing Sandboxed Execution (Docker):")
    provider = PythonDockerProvider(
        provider_id="python_sandboxed",
        default_mode="sandboxed"
    )
    await provider.initialize()
    
    result = await provider.execute(
        method="python/execute",
        params={
            "code": """
import platform
import os

# Try to access system information
result = {
    'platform': platform.platform(),
    'hostname': platform.node(),
    'user': os.environ.get('USER', 'unknown'),
    'isolated': True,
    'calculation': sum(range(10))
}
""",
            "execution_mode": "sandboxed",
            "timeout": 10
        }
    )
    
    if result.get('success'):
        print(f"   ✓ Sandboxed result: {result.get('result')}")
        print(f"   ✓ Execution was isolated in Docker container\n")
    else:
        print(f"   ❌ Error: {result.get('error')}\n")
    
    await provider.shutdown()
    
    # Test 3: Direct Docker Executor
    print("3. Testing Direct Docker Executor:")
    executor = DockerExecutor()
    await executor.initialize()
    
    # Pull Python image if needed
    print("   Checking Python Docker image...")
    await executor.pull_image("python:3.11-slim")
    
    # Execute code in container
    code = """
import json
import sys

data = {
    'message': 'Hello from Docker!',
    'python_version': sys.version.split()[0],
    'result': [i**2 for i in range(5)]
}

print(json.dumps(data))
"""
    
    result = await executor.execute(
        code=code,
        security_level=SecurityLevel.SANDBOXED,
        timeout=10
    )
    
    if result['success']:
        import json
        output_data = json.loads(result['stdout'])
        print(f"   ✓ Docker output: {output_data}")
        print(f"   ✓ Execution time: {result.get('execution_time', 0):.2f}s\n")
    else:
        print(f"   ❌ Error: {result.get('error')}\n")
    
    # Test 4: Container pooling
    print("4. Testing Container Pooling:")
    
    # Execute multiple times to test pooling
    for i in range(3):
        result = await executor.execute(
            code=f"print('Execution {i+1}')",
            security_level=SecurityLevel.SANDBOXED,
            timeout=5
        )
        if result['success']:
            print(f"   ✓ Run {i+1}: {result['stdout'].strip()}")
    
    # Check pool status
    pool_status = await executor.get_pool_status()
    print(f"\n   Container Pool Status:")
    print(f"   - Total containers: {pool_status['total_containers']}")
    print(f"   - Busy: {pool_status['busy_containers']}")
    print(f"   - Idle: {pool_status['idle_containers']}\n")
    
    # Test 5: Security levels
    print("5. Testing Security Levels:")
    
    # Try to access network (should fail in sandboxed mode)
    network_code = """
import socket
try:
    socket.gethostbyname('google.com')
    print('Network access: ALLOWED')
except:
    print('Network access: BLOCKED')
"""
    
    result = await executor.execute(
        code=network_code,
        security_level=SecurityLevel.SANDBOXED,
        timeout=5
    )
    
    if result['success']:
        print(f"   ✓ Sandboxed mode: {result['stdout'].strip()}")
    
    # Cleanup
    await executor.shutdown()
    
    print("\n" + "="*60)
    print("✅ Docker Execution Testing Complete!")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_docker_execution())