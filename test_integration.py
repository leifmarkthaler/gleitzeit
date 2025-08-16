#!/usr/bin/env python
"""
Integration test for multi-instance and Docker features
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.providers.ollama_pool_provider import OllamaPoolProvider
from gleitzeit.providers.python_docker_provider import PythonDockerProvider
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.models import Task


async def test_provider_integration():
    """Test provider integration with execution engine"""
    print("\n=== Testing Provider Integration ===\n")
    
    # Create registry
    registry = ProtocolProviderRegistry()
    print("✓ Created registry")
    
    # Register OllamaPoolProvider (with single instance for testing)
    try:
        ollama_provider = OllamaPoolProvider(
            provider_id="ollama_pool",
            instances=[
                {
                    "id": "local",
                    "url": "http://localhost:11434",
                    "models": ["llama3.2"],
                    "max_concurrent": 5
                }
            ]
        )
        await registry.register_provider(
            ollama_provider.provider_id,
            ollama_provider.protocol_id,
            ollama_provider
        )
        print("✓ Registered OllamaPoolProvider")
    except Exception as e:
        print(f"⚠️  Could not register OllamaPoolProvider: {e}")
    
    # Register PythonDockerProvider
    try:
        python_provider = PythonDockerProvider(
            provider_id="python_docker",
            default_mode="local"  # Use local mode for testing without Docker
        )
        await registry.register_provider(
            python_provider.provider_id,
            python_provider.protocol_id,
            python_provider
        )
        print("✓ Registered PythonDockerProvider")
    except Exception as e:
        print(f"⚠️  Could not register PythonDockerProvider: {e}")
    
    # Create execution engine
    engine = ExecutionEngine(registry)
    print("✓ Created execution engine")
    
    # Test Python execution (local mode)
    print("\n--- Testing Python Execution (Local Mode) ---")
    python_task = Task(
        id="test_python",
        name="Test Python",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": """
import math
result = {
    'pi': math.pi,
    'calculated': math.sqrt(16),
    'message': 'Python execution successful!'
}
""",
            "execution_mode": "local"
        }
    )
    
    try:
        result = await engine.execute(python_task)
        print(f"✓ Python execution successful: {result.get('result', result)}")
    except Exception as e:
        print(f"✗ Python execution failed: {e}")
    
    # Test validation
    print("\n--- Testing Python Validation ---")
    validation_task = Task(
        id="test_validation",
        name="Test Validation",
        protocol="python/v1",
        method="python/validate",
        params={
            "code": "print('Valid Python code')"
        }
    )
    
    try:
        result = await engine.execute(validation_task)
        print(f"✓ Validation successful: {result}")
    except Exception as e:
        print(f"✗ Validation failed: {e}")
    
    # Cleanup
    await registry.shutdown()
    print("\n✓ Shutdown complete")


async def test_workflow_scenario():
    """Test a complete workflow scenario"""
    print("\n=== Testing Workflow Scenario ===\n")
    
    from gleitzeit.core.workflow_manager import WorkflowManager
    from gleitzeit.persistence.sqlite_backend import SQLiteBackend
    
    # Setup
    backend = SQLiteBackend(":memory:")
    await backend.initialize()
    
    registry = ProtocolProviderRegistry()
    
    # Register local Python provider
    python_provider = PythonDockerProvider(
        provider_id="python_docker",
        default_mode="local"
    )
    await registry.register_provider(python_provider)
    
    workflow_manager = WorkflowManager(registry, backend)
    await workflow_manager.initialize()
    
    print("✓ Setup complete")
    
    # Create workflow
    workflow_config = {
        "name": "Test Workflow",
        "tasks": [
            {
                "id": "calculate",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": "result = {'sum': 10 + 20, 'product': 10 * 20}",
                    "execution_mode": "local"
                }
            },
            {
                "id": "process",
                "protocol": "python/v1",
                "method": "python/execute",
                "dependencies": ["calculate"],
                "params": {
                    "code": """
data = ${calculate.result}
result = {
    'original': data,
    'total': data['sum'] + data['product']
}
""",
                    "execution_mode": "local"
                }
            }
        ]
    }
    
    # Submit workflow
    workflow_id = await workflow_manager.submit_workflow(workflow_config)
    print(f"✓ Submitted workflow: {workflow_id}")
    
    # Wait for completion
    await asyncio.sleep(2)
    
    # Get results
    workflow = await backend.get_workflow(workflow_id)
    if workflow:
        print(f"✓ Workflow status: {workflow.status}")
        
        for task in workflow.tasks:
            task_data = await backend.get_task(task.id)
            if task_data and task_data.result:
                print(f"  - Task {task.name}: {task_data.result.get('result', 'completed')}")
    
    # Cleanup
    await workflow_manager.shutdown()
    await backend.close()
    print("\n✓ Workflow test complete")


async def main():
    """Run all integration tests"""
    print("\n" + "="*60)
    print("Integration Tests for New Features")
    print("="*60)
    
    # Test provider integration
    await test_provider_integration()
    
    # Test workflow scenario
    await test_workflow_scenario()
    
    print("\n" + "="*60)
    print("Integration tests completed! 🎉")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())