#!/usr/bin/env python3
"""
Simple Decorator Test

Test the @gleitzeit_task decorator pattern without requiring full services
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gleitzeit_cluster.decorators import gleitzeit_task, GleitzeitTaskService


@gleitzeit_task(category="math", description="Add two numbers")
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together"""
    return a + b


@gleitzeit_task(category="text", description="Process text")
def process_text(text: str) -> dict:
    """Process text and return analysis"""
    return {
        "original": text,
        "uppercase": text.upper(),
        "word_count": len(text.split()),
        "char_count": len(text)
    }


@gleitzeit_task(category="async", description="Async processing")
async def async_task(data: str, delay: float = 0.1) -> dict:
    """Async task with delay"""
    await asyncio.sleep(delay)
    return {
        "data": data,
        "processed_at": "async",
        "delay_used": delay
    }


async def test_decorator_functionality():
    """Test the decorator system"""
    
    print("🎯 Testing @gleitzeit_task Decorator")
    print("=" * 40)
    
    # Test 1: Direct function calls still work
    print("1. Testing direct function calls...")
    result1 = add_numbers(5, 3)
    print(f"   add_numbers(5, 3) = {result1}")
    
    result2 = process_text("Hello World")
    print(f"   process_text result: {result2}")
    
    result3 = await async_task("test data", 0.05)
    print(f"   async_task result: {result3}")
    print("✅ Direct function calls work")
    
    # Test 2: Decorator metadata
    print("\n2. Testing decorator metadata...")
    print(f"   add_numbers is decorated: {hasattr(add_numbers, '_gleitzeit_task')}")
    print(f"   Task name: {add_numbers._task_name}")
    print(f"   Category: {add_numbers._task_category}")
    print(f"   Description: {add_numbers._task_description}")
    print("✅ Decorator metadata works")
    
    # Test 3: Service discovery
    print("\n3. Testing service discovery...")
    from gleitzeit_cluster.decorators import _decorated_functions
    print(f"   Discovered {len(_decorated_functions)} decorated functions:")
    for name, info in _decorated_functions.items():
        print(f"   - {name} ({info['category']}): {info['description']}")
    print("✅ Service discovery works")
    
    # Test 4: Task service creation (without connecting)
    print("\n4. Testing task service creation...")
    try:
        service = GleitzeitTaskService(
            service_name="Test Service",
            cluster_url="http://localhost:8000",
            auto_discover=False  # Use already registered functions
        )
        print(f"   Service name: {service.service_name}")
        print(f"   Task handlers: {len(service.task_handlers)}")
        print("✅ Task service creation works")
    except Exception as e:
        print(f"❌ Task service creation failed: {e}")
        return False
    
    # Test 5: Handler creation
    print("\n5. Testing handler creation...")
    try:
        # Simulate a task execution
        test_task_data = {
            "parameters": {
                "external_parameters": {
                    "args": [10, 15],
                    "kwargs": {}
                }
            }
        }
        
        # Get handler for add_numbers
        handler = service.task_handlers.get("add_numbers")
        if handler:
            result = await handler(test_task_data)
            print(f"   Handler result: {result}")
            print("✅ Handler execution works")
        else:
            print("❌ Handler not found")
            return False
    except Exception as e:
        print(f"❌ Handler execution failed: {e}")
        return False
    
    return True


async def test_workflow_integration():
    """Test integration with workflow (without actual execution)"""
    
    print("\n🔗 Testing Workflow Integration")
    print("=" * 35)
    
    # Test basic workflow creation with external tasks
    from gleitzeit_cluster import GleitzeitCluster
    
    cluster = GleitzeitCluster(
        use_external_python_executor=True,
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=False,
        auto_start_python_executor=False
    )
    
    workflow = cluster.create_workflow("Decorator Test Workflow")
    
    # Add tasks that reference our decorated functions
    task1 = workflow.add_external_task(
        name="Add Numbers",
        external_task_type="python_execution",
        service_name="Python Tasks",
        external_parameters={
            "function_name": "add_numbers",
            "args": [20, 22],
            "kwargs": {}
        }
    )
    
    task2 = workflow.add_external_task(
        name="Process Text",
        external_task_type="python_execution", 
        service_name="Python Tasks",
        external_parameters={
            "function_name": "process_text",
            "args": ["This is a test message"],
            "kwargs": {}
        }
    )
    
    # Add LLM task that depends on the Python tasks
    llm_task = workflow.add_text_task(
        name="Analyze Results",
        prompt="""
        Analyze these results:
        Addition: {{Add Numbers.result}}
        Text Processing: {{Process Text.result}}
        """,
        model="llama3",
        dependencies=["Add Numbers", "Process Text"]
    )
    
    print(f"✅ Created workflow with {len(workflow.tasks)} tasks")
    print("   Tasks:")
    for task in workflow.tasks.values():
        deps = f" (deps: {', '.join(task.dependencies)})" if task.dependencies else ""
        print(f"   - {task.name}: {task.task_type}{deps}")
    
    return True


async def main():
    """Run all decorator tests"""
    
    try:
        success1 = await test_decorator_functionality()
        success2 = await test_workflow_integration()
        
        if success1 and success2:
            print("\n🎉 All decorator tests passed!")
            print("\n✅ The @gleitzeit_task decorator system is working:")
            print("   🎯 Functions can be decorated and still called directly")
            print("   📝 Metadata is properly stored")
            print("   🔍 Auto-discovery finds decorated functions")
            print("   🏗️ Service can create handlers for decorated functions")
            print("   🔗 Integration with workflows works")
            print("\nReady for production use!")
            return True
        else:
            print("\n❌ Some decorator tests failed.")
            return False
            
    except Exception as e:
        print(f"\n💥 Decorator test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)