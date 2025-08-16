#!/usr/bin/env python
"""
Simple test for the new features
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.providers.python_docker_provider import PythonDockerProvider


async def test_python_local_execution():
    """Test Python local execution"""
    print("\n=== Testing Python Local Execution ===\n")
    
    # Create provider
    provider = PythonDockerProvider(
        provider_id="python_test",
        default_mode="local"
    )
    
    # Initialize
    await provider.initialize()
    print("✓ Provider initialized")
    
    # Test simple execution
    result = await provider.execute(
        method="python/execute",
        params={
            "code": """
import math
result = {
    'pi': math.pi,
    'e': math.e,
    'calculation': 2 + 2
}
""",
            "execution_mode": "local"
        }
    )
    
    print(f"✓ Execution result: {result}")
    
    # Test validation
    validation = await provider.execute(
        method="python/validate",
        params={
            "code": "print('Hello, World!')"
        }
    )
    
    print(f"✓ Validation result: {validation}")
    
    # Test with syntax error
    validation_error = await provider.execute(
        method="python/validate",
        params={
            "code": "print('Missing closing quote)"
        }
    )
    
    print(f"✓ Validation error caught: {validation_error}")
    
    # Shutdown
    await provider.shutdown()
    print("\n✅ Test completed successfully!")


if __name__ == "__main__":
    asyncio.run(test_python_local_execution())