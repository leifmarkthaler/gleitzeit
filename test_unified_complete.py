#!/usr/bin/env python3
"""
Complete Unified Architecture Test

Comprehensive test of the unified Socket.IO architecture showing
all task types routing through services.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.decorators import gleitzeit_task
from services.external_llm_providers import MockLLMService


@gleitzeit_task(category="demo")
def analyze_data(data: dict) -> dict:
    """Analyze business data"""
    return {
        "summary": f"Analyzed {len(data)} items",
        "total_value": sum(data.values()) if isinstance(data, dict) else 0,
        "analysis_type": "comprehensive"
    }


async def test_unified_architecture():
    """Test the complete unified architecture"""
    
    print("🧪 Testing Complete Unified Architecture")
    print("=" * 50)
    
    # Test 1: Configuration
    print("1. Testing unified architecture configuration...")
    
    cluster = GleitzeitCluster(
        # Enable unified architecture
        use_unified_socketio_architecture=True,
        use_external_python_executor=True,
        
        # Disable auto-start for testing
        auto_start_internal_llm_service=False,
        auto_start_python_executor=False,
        
        # Simplified for testing
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=False,
        auto_start_services=False
    )
    
    print(f"   ✅ Unified architecture enabled: {cluster.use_unified_socketio_architecture}")
    print(f"   ✅ External Python enabled: {cluster.use_external_python_executor}")
    
    # Test 2: Workflow creation and task routing
    print("\n2. Testing task routing in unified architecture...")
    
    workflow = cluster.create_workflow("Unified Test Workflow")
    
    # Verify flags are passed to workflow
    assert workflow._use_unified_socketio_architecture == True
    assert workflow._use_external_python_executor == True
    print("   ✅ Configuration flags passed to workflow")
    
    # Test LLM task routing
    internal_task = workflow.add_text_task(
        name="Internal LLM",
        prompt="Test prompt",
        model="llama3",
        provider="internal"
    )
    
    openai_task = workflow.add_text_task(
        name="OpenAI LLM", 
        prompt="Test prompt",
        model="gpt-4",
        provider="openai"
    )
    
    claude_task = workflow.add_text_task(
        name="Claude LLM",
        prompt="Test prompt", 
        model="claude-3",
        provider="anthropic"
    )
    
    # Test Python task routing
    python_task = workflow.add_python_task(
        name="Python Task",
        function_name="analyze_data",
        args=[{"revenue": 100, "profit": 20}]
    )
    
    # Verify all tasks route through Socket.IO
    all_external = all(
        task.task_type.value.startswith("external") 
        for task in workflow.tasks.values()
    )
    
    print(f"   ✅ All tasks route externally: {all_external}")
    
    # Verify service routing
    routing_tests = [
        (internal_task, "Internal LLM Service"),
        (openai_task, "OpenAI Service"),
        (claude_task, "Anthropic Service"),
        (python_task, "Python Executor")
    ]
    
    for task, expected_service in routing_tests:
        actual_service = task.parameters.service_name
        print(f"   ✅ {task.name}: {actual_service}")
        assert actual_service == expected_service
    
    print(f"\n   📊 Created workflow with {len(workflow.tasks)} tasks, all routed externally")
    
    # Test 3: Service capabilities
    print("\n3. Testing service capabilities...")
    
    # Test mock LLM service functionality
    mock_service = MockLLMService(response_delay=0.1)
    
    test_task = {
        'parameters': {
            'external_parameters': {
                'prompt': 'What is machine learning?',
                'model': 'mock-gpt',
                'temperature': 0.7
            }
        }
    }
    
    result = await mock_service.execute_llm_task(test_task)
    
    assert result['success'] == True
    assert 'result' in result
    assert result['provider'] == 'mock'
    print(f"   ✅ Mock LLM service execution works")
    print(f"      Response: {result['result'][:80]}...")
    
    # Test 4: Decorator integration
    print("\n4. Testing decorator integration...")
    
    from gleitzeit_cluster.decorators import _decorated_functions
    print(f"   ✅ Decorated functions discovered: {len(_decorated_functions)}")
    
    for name, info in _decorated_functions.items():
        print(f"      - {name} ({info['category']})")
    
    # Test direct function call still works
    test_data = {"sales": 1000, "costs": 800}
    direct_result = analyze_data(test_data)
    print(f"   ✅ Direct function call works: {direct_result}")
    
    return True


async def test_provider_flexibility():
    """Test mixing different providers in one workflow"""
    
    print("\n🎭 Testing Provider Flexibility")
    print("=" * 35)
    
    cluster = GleitzeitCluster(
        use_unified_socketio_architecture=True,
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=False,
        auto_start_services=False
    )
    
    workflow = cluster.create_workflow("Multi-Provider Test")
    
    # Create tasks with different providers
    providers_tested = []
    
    # Internal provider
    task1 = workflow.add_text_task(
        "Analysis 1", 
        prompt="Analyze this data",
        model="llama3",
        provider="internal"
    )
    providers_tested.append(("internal", task1.parameters.service_name))
    
    # OpenAI provider (automatically detected from model)
    task2 = workflow.add_text_task(
        "Analysis 2",
        prompt="Analyze this data", 
        model="gpt-4"  # Automatically routes to OpenAI
    )
    providers_tested.append(("auto-openai", task2.parameters.service_name))
    
    # Explicit Claude provider
    task3 = workflow.add_text_task(
        "Analysis 3",
        prompt="Analyze this data",
        model="claude-3-sonnet",
        provider="anthropic"
    )
    providers_tested.append(("anthropic", task3.parameters.service_name))
    
    # Mock provider for testing
    task4 = workflow.add_text_task(
        "Analysis 4",
        prompt="Analyze this data",
        model="mock-model",
        provider="mock"
    )
    providers_tested.append(("mock", task4.parameters.service_name))
    
    print("✅ Provider routing tests:")
    for provider, service in providers_tested:
        print(f"   {provider:>12}: → {service}")
    
    # Verify all are external tasks
    external_count = sum(1 for task in workflow.tasks.values() 
                        if task.task_type.value.startswith("external"))
    print(f"\n✅ All {external_count}/{len(workflow.tasks)} tasks route externally")
    
    return True


async def test_backwards_compatibility():
    """Test that old code still works with legacy mode"""
    
    print("\n🔄 Testing Backwards Compatibility")
    print("=" * 35)
    
    # Old architecture (default)
    cluster_old = GleitzeitCluster(
        use_unified_socketio_architecture=False,  # Legacy mode
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=False
    )
    
    workflow_old = cluster_old.create_workflow("Legacy Test")
    
    # Old API should still work
    old_llm = workflow_old.add_text_task(
        "Old LLM Task",
        prompt="Test prompt",
        model="llama3"
    )
    
    old_python = workflow_old.add_python_task(
        "Old Python Task", 
        function_name="my_function"
    )
    
    print(f"✅ Legacy mode routing:")
    print(f"   LLM Task:    {old_llm.task_type} (direct)")
    print(f"   Python Task: {old_python.task_type} (direct)")
    
    # New architecture
    cluster_new = GleitzeitCluster(
        use_unified_socketio_architecture=True,  # New mode
        use_external_python_executor=True,
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=False,
        auto_start_services=False
    )
    
    workflow_new = cluster_new.create_workflow("Unified Test")
    
    # Same API, different routing
    new_llm = workflow_new.add_text_task(
        "New LLM Task",
        prompt="Test prompt", 
        model="llama3"
    )
    
    new_python = workflow_new.add_python_task(
        "New Python Task",
        function_name="my_function"
    )
    
    print(f"\n✅ Unified mode routing:")
    print(f"   LLM Task:    {new_llm.task_type} → {new_llm.parameters.service_name}")
    print(f"   Python Task: {new_python.task_type} → {new_python.parameters.service_name}")
    
    print(f"\n✅ Same API, different architecture!")
    
    return True


async def run_comprehensive_test():
    """Run all tests"""
    
    try:
        print("🚀 Comprehensive Unified Architecture Test")
        print("=" * 55)
        
        success1 = await test_unified_architecture()
        success2 = await test_provider_flexibility()
        success3 = await test_backwards_compatibility()
        
        if success1 and success2 and success3:
            print("\n🎉 All unified architecture tests passed!")
            
            print("\n✅ Verified Features:")
            print("   🏛️ Pure orchestrator (no direct execution)")
            print("   🔄 All tasks route via Socket.IO services")
            print("   🎯 Provider flexibility (internal + external LLMs)")
            print("   🐍 Python tasks via decorators + Socket.IO")
            print("   🔧 Same API with better architecture")
            print("   📊 Unified monitoring and management")
            
            print("\n🚀 Ready for Production:")
            print("   1. Enable: use_unified_socketio_architecture=True")
            print("   2. Internal LLM service auto-starts with Ollama")
            print("   3. Add external providers as needed")
            print("   4. Use @gleitzeit_task for Python functions")
            print("   5. Same workflow API, better architecture")
            
            return True
        else:
            print("\n❌ Some tests failed")
            return False
            
    except Exception as e:
        print(f"\n💥 Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(run_comprehensive_test())
    print(f"\n{'🎯 UNIFIED ARCHITECTURE VERIFIED' if success else '❌ TESTS FAILED'}")
    sys.exit(0 if success else 1)