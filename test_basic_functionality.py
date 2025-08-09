#!/usr/bin/env python3
"""
Basic Functionality Test

Test core Gleitzeit functionality without external services
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.decorators import gleitzeit_task


@gleitzeit_task(category="test")
def simple_math(a: int, b: int) -> int:
    """Simple addition function"""
    return a + b


@gleitzeit_task(category="test")
async def async_processing(data: str) -> dict:
    """Async processing function"""
    await asyncio.sleep(0.1)
    return {
        "processed": data.upper(),
        "length": len(data),
        "type": "async_result"
    }


async def test_basic_workflow():
    """Test basic workflow creation and task routing"""
    
    print("🧪 Testing Basic Gleitzeit Functionality")
    print("=" * 50)
    
    # Test 1: Basic cluster creation
    print("1. Testing cluster creation...")
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=False,
        auto_start_services=False
    )
    print("✅ Cluster created successfully")
    
    # Test 2: Workflow creation
    print("\n2. Testing workflow creation...")
    workflow = cluster.create_workflow("Test Workflow", "Basic functionality test")
    print(f"✅ Workflow created: {workflow.name} (ID: {workflow.id[:8]}...)")
    
    # Test 3: Native Python task (legacy)
    print("\n3. Testing native Python task creation...")
    native_task = workflow.add_python_task(
        name="Native Math",
        function_name="add_numbers",
        args=[10, 20],
        use_external_executor=False  # Force native
    )
    print(f"✅ Native task: {native_task.task_type}")
    
    # Test 4: External Python task (new way)
    print("\n4. Testing external Python task routing...")
    cluster_external = GleitzeitCluster(
        use_external_python_executor=True,
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=False,
        auto_start_python_executor=False
    )
    
    workflow_external = cluster_external.create_workflow("External Test")
    external_task = workflow_external.add_python_task(
        name="External Math",
        function_name="simple_math", 
        args=[5, 7]
    )
    print(f"✅ External task: {external_task.task_type}")
    print(f"   Service: {external_task.parameters.service_name}")
    print(f"   Function: {external_task.parameters.external_parameters['function_name']}")
    
    # Test 5: LLM task creation
    print("\n5. Testing LLM task creation...")
    llm_task = workflow.add_text_task(
        name="Simple LLM Task",
        prompt="What is 2 + 2?",
        model="llama3",
        temperature=0.1
    )
    print(f"✅ LLM task: {llm_task.task_type}")
    print(f"   Model: {llm_task.parameters.model_name}")
    
    # Test 6: Task dependencies
    print("\n6. Testing task dependencies...")
    dependent_task = workflow.add_text_task(
        name="Dependent Task",
        prompt="Analyze this result: {{Simple LLM Task.result}}",
        model="llama3",
        dependencies=["Simple LLM Task"]
    )
    print(f"✅ Dependent task created with {len(dependent_task.dependencies)} dependencies")
    
    # Test 7: Workflow structure
    print("\n7. Testing workflow structure...")
    print(f"✅ Workflow has {len(workflow.tasks)} tasks:")
    for task_id, task in workflow.tasks.items():
        deps = f" (deps: {', '.join(task.dependencies)})" if task.dependencies else ""
        print(f"   - {task.name}{deps}")
    
    # Test 8: Decorator functionality
    print("\n8. Testing decorator functionality...")
    result = simple_math(3, 4)
    print(f"✅ Decorated sync function: {result}")
    
    async_result = await async_processing("hello world")
    print(f"✅ Decorated async function: {async_result}")
    
    # Test 9: Task types
    print("\n9. Testing task type system...")
    from gleitzeit_cluster.core.task import TaskType
    external_types = [
        TaskType.EXTERNAL_API,
        TaskType.EXTERNAL_ML,
        TaskType.EXTERNAL_DATABASE,
        TaskType.EXTERNAL_PROCESSING,
        TaskType.EXTERNAL_WEBHOOK,
        TaskType.EXTERNAL_CUSTOM
    ]
    print(f"✅ {len(external_types)} external task types available")
    
    print("\n🎉 All basic functionality tests passed!")
    
    return True


async def test_error_handling():
    """Test error handling and edge cases"""
    
    print("\n🔍 Testing Error Handling")
    print("=" * 30)
    
    try:
        # Test invalid task creation
        cluster = GleitzeitCluster(enable_redis=False, enable_socketio=False, enable_real_execution=False)
        workflow = cluster.create_workflow("Error Test")
        
        # This should work fine
        task = workflow.add_python_task("Valid Task", "some_function")
        print("✅ Valid task creation works")
        
        # Test workflow with mixed task types
        workflow.add_text_task("LLM Task", "Test prompt")
        workflow.add_external_ml_task("ML Task", "ML Service", "train", {})
        
        print(f"✅ Mixed workflow with {len(workflow.tasks)} different task types")
        
        return True
        
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        return False


async def main():
    """Run all tests"""
    
    try:
        success1 = await test_basic_workflow()
        success2 = await test_error_handling()
        
        if success1 and success2:
            print("\n✅ All tests passed! Gleitzeit core functionality is working.")
            print("\nNext steps:")
            print("1. Start Redis and Socket.IO services for full functionality")
            print("2. Run examples with: python examples/llm_orchestration_examples.py")
            print("3. Set up Ollama endpoints for LLM orchestration")
            return True
        else:
            print("\n❌ Some tests failed.")
            return False
            
    except Exception as e:
        print(f"\n💥 Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)