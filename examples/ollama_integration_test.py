#!/usr/bin/env python3
"""
Ollama Integration Test for Gleitzeit Cluster

This example demonstrates the real Ollama integration capabilities including:
- Text generation with various models
- Vision tasks with image analysis
- Mixed workflows combining different task types
- Python function execution
- Error handling and model management

Requirements:
- Ollama server running on localhost:11434
- At least one text model available (e.g., llama3)
- Optional: Vision model (e.g., llava) for vision tasks
"""

import asyncio
import sys
from pathlib import Path

# Add package to path for import
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.core.task import TaskType
from gleitzeit_cluster.core.workflow import WorkflowErrorStrategy


async def test_text_generation():
    """Test basic text generation with Ollama"""
    print("🧪 Test 1: Text Generation")
    print("=" * 50)
    
    cluster = GleitzeitCluster(enable_real_execution=True)
    
    try:
        await cluster.start()
        
        # Check available models
        models = await cluster.get_available_models()
        print(f"📋 Available models: {models}")
        
        if "available" in models and models["available"]:
            # Use first available model or default
            model = models["available"][0] if models["available"] else "llama3"
            print(f"🤖 Using model: {model}")
            
            # Simple text analysis
            result = await cluster.analyze_text(
                prompt="Explain quantum computing in simple terms (2-3 sentences)",
                model=model
            )
            
            print(f"✅ Result: {result}")
            
        else:
            print("❌ No models available. Please ensure Ollama is running with models installed.")
            return False
    
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    finally:
        await cluster.stop()
    
    print("✅ Text generation test completed\n")
    return True


async def test_mixed_workflow():
    """Test complex workflow with multiple task types"""
    print("🧪 Test 2: Mixed Workflow")
    print("=" * 50)
    
    cluster = GleitzeitCluster(enable_real_execution=True)
    
    try:
        await cluster.start()
        
        # Register Python functions
        async def process_data(numbers):
            """Example async function"""
            await asyncio.sleep(0.1)
            return {
                "sum": sum(numbers),
                "average": sum(numbers) / len(numbers) if numbers else 0,
                "count": len(numbers)
            }
        
        def format_results(data):
            """Example sync function"""
            return f"Processed {data['count']} numbers: sum={data['sum']}, avg={data['average']:.2f}"
        
        cluster.register_python_functions({
            "process_data": process_data,
            "format_results": format_results
        })
        
        # Create complex workflow
        workflow = cluster.create_workflow("mixed_analysis", "Complex workflow demo")
        
        # Task 1: Python data processing
        data_task = workflow.add_python_task(
            "process", 
            "process_data", 
            args=[[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]
        )
        
        # Task 2: Format results (depends on data processing)
        format_task = workflow.add_python_task(
            "format", 
            "format_results", 
            args=[],  # Will use result from previous task
            depends_on=[data_task.id]
        )
        
        # Task 3: LLM analysis (depends on formatted results)
        llm_task = workflow.add_text_task(
            "analyze",
            "Analyze this data summary and provide insights: {format_results}",
            model="llama3",
            depends_on=[format_task.id]
        )
        
        # Execute workflow
        result = await cluster.execute_workflow(workflow)
        
        print(f"📊 Workflow Status: {result.status}")
        print(f"📈 Results:")
        for task_id, task_result in result.results.items():
            task_name = workflow.tasks[task_id].name
            print(f"   - {task_name}: {task_result}")
        
        if result.errors:
            print(f"⚠️  Errors: {result.errors}")
    
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    finally:
        await cluster.stop()
    
    print("✅ Mixed workflow test completed\n")
    return True


async def test_model_management():
    """Test model management capabilities"""
    print("🧪 Test 3: Model Management")
    print("=" * 50)
    
    cluster = GleitzeitCluster(enable_real_execution=True)
    
    try:
        await cluster.start()
        
        # Get available models
        models = await cluster.get_available_models()
        print(f"📋 Model info: {models}")
        
        # Get cluster stats
        stats = cluster.get_cluster_stats()
        print(f"📊 Cluster stats: {stats}")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    finally:
        await cluster.stop()
    
    print("✅ Model management test completed\n")
    return True


async def test_error_handling():
    """Test error handling in workflows"""
    print("🧪 Test 4: Error Handling")
    print("=" * 50)
    
    cluster = GleitzeitCluster(enable_real_execution=True)
    
    try:
        await cluster.start()
        
        # Create workflow with intentional error
        workflow = cluster.create_workflow("error_test", "Test error handling")
        workflow.error_strategy = WorkflowErrorStrategy.CONTINUE_ON_ERROR  # Continue on errors
        
        # Task that will succeed
        success_task = workflow.add_text_task(
            "success",
            "Say hello in one word",
            model="llama3"
        )
        
        # Task that will fail (invalid model)
        fail_task = workflow.add_text_task(
            "fail",
            "This will fail",
            model="nonexistent_model_12345"
        )
        
        # Task that depends on successful task
        final_task = workflow.add_text_task(
            "final",
            "Say goodbye in one word",
            model="llama3",
            depends_on=[success_task.id]
        )
        
        # Execute workflow
        result = await cluster.execute_workflow(workflow)
        
        print(f"📊 Workflow Status: {result.status}")
        print(f"📈 Successful Results: {len([r for r in result.results.values() if r])}")
        print(f"⚠️  Errors: {len(result.errors)}")
        
        for task_id, error in result.errors.items():
            task_name = workflow.tasks[task_id].name
            print(f"   - {task_name}: {error}")
    
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    finally:
        await cluster.stop()
    
    print("✅ Error handling test completed\n")
    return True


async def test_fallback_to_mock():
    """Test fallback to mock execution when Ollama is unavailable"""
    print("🧪 Test 5: Mock Fallback")
    print("=" * 50)
    
    # Create cluster with real execution disabled
    cluster = GleitzeitCluster(enable_real_execution=False)
    
    try:
        await cluster.start()
        
        result = await cluster.analyze_text(
            prompt="This will use mock execution",
            model="any_model"
        )
        
        print(f"✅ Mock result: {result}")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    finally:
        await cluster.stop()
    
    print("✅ Mock fallback test completed\n")
    return True


async def main():
    """Run all tests"""
    print("🚀 Gleitzeit Cluster - Ollama Integration Tests")
    print("=" * 60)
    print()
    
    tests = [
        test_text_generation,
        test_mixed_workflow, 
        test_model_management,
        test_error_handling,
        test_fallback_to_mock
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if await test():
                passed += 1
        except Exception as e:
            print(f"❌ Test failed with exception: {e}\n")
    
    print("📊 Test Summary")
    print("=" * 30)
    print(f"✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")
    
    if passed == total:
        print("\n🎉 All tests passed! Ollama integration is working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} tests failed. Check Ollama setup and models.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)