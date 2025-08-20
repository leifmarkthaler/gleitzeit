"""
How to Register and Use Custom Template Provider with Gleitzeit

This example shows the actual integration of a custom template provider
with the Gleitzeit system.
"""

import asyncio
from typing import Dict, Any
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.persistence import PersistenceFactory
from gleitzeit.task_queue import TaskQueue, QueueManager, DependencyResolver
from gleitzeit.protocols import TEMPLATE_PROTOCOL_V1

# Import our custom template provider
from custom_template_provider import CustomTemplateProvider


async def setup_custom_gleitzeit():
    """Set up Gleitzeit with custom template provider"""
    
    # Initialize core components
    persistence = await PersistenceFactory.create()
    task_queue = TaskQueue()
    queue_manager = QueueManager(task_queue)
    dependency_resolver = DependencyResolver()
    
    # Create execution engine
    execution_engine = ExecutionEngine(
        queue_manager=queue_manager,
        dependency_resolver=dependency_resolver,
        persistence_adapter=persistence
    )
    
    # Create provider registry
    registry = ProtocolProviderRegistry()
    
    # Register the template protocol
    registry.register_protocol(TEMPLATE_PROTOCOL_V1)
    
    # Create and register CUSTOM template provider instead of default
    custom_provider = CustomTemplateProvider(
        provider_id="custom-template-provider",
        execution_engine=execution_engine
    )
    await custom_provider.initialize()
    
    # Register the custom provider
    registry.register_provider(
        provider_id="custom-template-provider",
        protocol_id="template/v1",
        provider=custom_provider
    )
    
    # Also register standard providers if needed
    from gleitzeit.providers.ollama_provider import OllamaProvider
    from gleitzeit.providers.python_provider import PythonProvider
    from gleitzeit.protocols import LLM_PROTOCOL_V1, PYTHON_PROTOCOL_V1
    
    # Register LLM protocol and provider
    registry.register_protocol(LLM_PROTOCOL_V1)
    ollama_provider = OllamaProvider(
        provider_id="ollama-provider",
        endpoint="http://localhost:11434"
    )
    await ollama_provider.initialize()
    registry.register_provider("ollama-provider", "llm/v1", ollama_provider)
    
    # Register Python protocol and provider
    registry.register_protocol(PYTHON_PROTOCOL_V1)
    python_provider = PythonProvider(provider_id="python-provider")
    await python_provider.initialize()
    registry.register_provider("python-provider", "python/v1", python_provider)
    
    # Set providers in execution engine
    execution_engine.set_provider_registry(registry)
    
    return execution_engine, registry


async def use_custom_templates():
    """Demonstrate using custom template methods"""
    
    print("Setting up Gleitzeit with Custom Template Provider...")
    print("=" * 60)
    
    execution_engine, registry = await setup_custom_gleitzeit()
    
    # Get the custom template provider
    provider = registry.get_provider("template/v1", "template/data_pipeline")
    
    if not provider:
        print("Error: Could not find custom template provider!")
        return
    
    print(f"\nRegistered Template Provider: {provider.__class__.__name__}")
    print(f"Supported Methods: {provider.get_supported_methods()}")
    print("\n" + "-" * 60)
    
    # Example 1: Data Pipeline Template
    print("\n1. Executing Data Pipeline Template...")
    try:
        pipeline_result = await provider.handle_request(
            method="template/data_pipeline",
            parameters={
                "source": "api_endpoint",
                "transform_type": "aggregation"
            }
        )
        print(f"   Status: {pipeline_result.get('status')}")
        print(f"   Workflow ID: {pipeline_result.get('workflow_id')}")
        print(f"   Execution Time: {pipeline_result.get('execution_time'):.2f}s")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Example 2: API Builder Template
    print("\n2. Executing API Builder Template...")
    try:
        api_result = await provider.handle_request(
            method="template/api_builder",
            parameters={
                "specification": "User Management API",
                "framework": "FastAPI"
            }
        )
        print(f"   Status: {api_result.get('status')}")
        print(f"   Workflow ID: {api_result.get('workflow_id')}")
        if api_result.get('api_code'):
            print(f"   Generated API Code Length: {len(api_result['api_code'])} chars")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Example 3: Test Suite Template
    print("\n3. Executing Test Suite Template...")
    sample_code = """
def calculate_discount(price, discount_percent):
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("Invalid discount percentage")
    return price * (1 - discount_percent / 100)
"""
    
    try:
        test_result = await provider.handle_request(
            method="template/test_suite",
            parameters={
                "code": sample_code,
                "framework": "pytest"
            }
        )
        print(f"   Status: {test_result.get('status')}")
        print(f"   Workflow ID: {test_result.get('workflow_id')}")
        if test_result.get('tests'):
            print(f"   Generated Tests Length: {len(test_result['tests'])} chars")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Example 4: Deployment Template
    print("\n4. Executing Deployment Template...")
    try:
        deploy_result = await provider.handle_request(
            method="template/deployment",
            parameters={
                "app_type": "REST API",
                "platform": "docker-compose"
            }
        )
        print(f"   Status: {deploy_result.get('status')}")
        print(f"   Workflow ID: {deploy_result.get('workflow_id')}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Also test that standard templates still work
    print("\n5. Testing Standard Template (Research)...")
    try:
        research_result = await provider.handle_request(
            method="template/research",
            parameters={
                "topic": "quantum computing basics",
                "depth": "shallow",
                "max_steps": 3
            }
        )
        print(f"   Status: {research_result.get('status')}")
        print(f"   Workflow ID: {research_result.get('workflow_id')}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n" + "=" * 60)
    print("Custom template demonstration complete!")
    
    # Cleanup
    await execution_engine.shutdown()


async def use_in_workflow_yaml():
    """Show how custom templates can be used in YAML workflows"""
    
    yaml_example = """
# custom_workflow.yaml
name: "Custom Template Workflow"
description: "Using custom template methods"
tasks:
  - id: "pipeline_task"
    protocol: "template/v1"
    method: "template/data_pipeline"
    params:
      source: "csv_file"
      transform_type: "normalization"
    priority: "high"
  
  - id: "api_task"
    protocol: "template/v1"
    method: "template/api_builder"
    params:
      specification: "Data Processing API"
      framework: "Flask"
    dependencies: ["pipeline_task"]
  
  - id: "test_task"
    protocol: "template/v1"
    method: "template/test_suite"
    params:
      code: "${api_task.api_code}"
      framework: "unittest"
    dependencies: ["api_task"]
  
  - id: "deploy_task"
    protocol: "template/v1"
    method: "template/deployment"
    params:
      app_type: "data processing service"
      platform: "aws-lambda"
    dependencies: ["test_task"]
"""
    
    print("\nYAML Workflow Example Using Custom Templates:")
    print("=" * 60)
    print(yaml_example)
    print("=" * 60)
    print("\nThis YAML can be executed with: gleitzeit run custom_workflow.yaml")
    print("(After registering the custom template provider)")


# Alternative: Monkey-patching approach (simpler but less clean)
def monkey_patch_templates():
    """
    Alternative approach: Monkey-patch the existing TemplateProvider
    This is simpler but less maintainable
    """
    from gleitzeit.providers.template_provider import TemplateProvider
    
    # Save original methods
    original_get_methods = TemplateProvider.get_supported_methods
    original_handle = TemplateProvider.handle_request
    
    # Define new methods
    def get_supported_methods_patched(self):
        base = original_get_methods(self)
        return base + ["template/custom_method"]
    
    async def handle_request_patched(self, method, parameters):
        if method == "template/custom_method":
            # Handle custom method
            return {"status": "completed", "result": "Custom method executed"}
        return await original_handle(self, method, parameters)
    
    # Apply patches
    TemplateProvider.get_supported_methods = get_supported_methods_patched
    TemplateProvider.handle_request = handle_request_patched
    
    print("TemplateProvider has been patched with custom methods!")


if __name__ == "__main__":
    print("""
    Custom Template Provider Integration Examples
    ==============================================
    
    This script demonstrates how to:
    1. Create a custom template provider with new methods
    2. Register it with the Gleitzeit system
    3. Use the custom templates programmatically
    4. Use custom templates in YAML workflows
    
    Choose an option:
    1. Run custom template examples
    2. Show YAML workflow example
    3. Show monkey-patching approach
    """)
    
    choice = input("Enter choice (1-3): ").strip()
    
    if choice == "1":
        asyncio.run(use_custom_templates())
    elif choice == "2":
        asyncio.run(use_in_workflow_yaml())
    elif choice == "3":
        monkey_patch_templates()
        print("\nNow you can use 'template/custom_method' in any Gleitzeit client!")
    else:
        print("Invalid choice")