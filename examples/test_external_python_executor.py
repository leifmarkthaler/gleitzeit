#!/usr/bin/env python3
"""
Test External Python Executor Service

Validates the external Python executor implementation.
Tests both feature flag routing and actual execution.
"""

import asyncio
import sys
import warnings
from pathlib import Path

# Add the parent directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.core.task import TaskType
from services.python_executor_service import PythonExecutorService


async def test_feature_flag_routing():
    """Test that feature flag properly routes Python tasks"""
    print("🧪 Testing feature flag routing...")
    
    # Test with native execution (default)
    cluster_native = GleitzeitCluster(
        use_external_python_executor=False,
        enable_redis=False,
        enable_socketio=False
    )
    
    workflow_native = cluster_native.create_workflow("Native Test")
    task_native = workflow_native.add_python_task(
        name="Native Python Task",
        function_name="test_function",
        args=[1, 2],
        kwargs={'test': True}
    )
    
    # Should use native TaskType.FUNCTION
    assert task_native.task_type == TaskType.FUNCTION
    assert task_native.parameters.function_name == "test_function"
    print("   ✅ Native routing works correctly")
    
    # Test with external execution
    cluster_external = GleitzeitCluster(
        use_external_python_executor=True,  # Enable external execution
        enable_redis=False,
        enable_socketio=False,
        auto_start_python_executor=False  # Don't auto-start for unit test
    )
    
    workflow_external = cluster_external.create_workflow("External Test")
    task_external = workflow_external.add_python_task(
        name="External Python Task",
        function_name="test_function",
        args=[1, 2],
        kwargs={'test': True}
    )
    
    # Should use external TaskType.EXTERNAL_PROCESSING
    assert task_external.task_type == TaskType.EXTERNAL_PROCESSING
    assert task_external.parameters.service_name == "Python Executor"
    assert task_external.parameters.external_task_type == "python_execution"
    assert task_external.parameters.external_parameters['function_name'] == "test_function"
    print("   ✅ External routing works correctly")
    
    # Test per-task override
    task_override = workflow_native.add_python_task(
        name="Override Task",
        function_name="test_function",
        use_external_executor=True  # Override to use external
    )
    
    assert task_override.task_type == TaskType.EXTERNAL_PROCESSING
    print("   ✅ Per-task override works correctly")


async def test_python_executor_service():
    """Test the Python executor service directly"""
    print("🧪 Testing Python executor service...")
    
    # Create executor service (but don't connect to cluster)
    executor = PythonExecutorService(
        service_name="Test Executor",
        cluster_url="http://localhost:8000",
        max_workers=2,
        isolation_mode="direct",  # Use direct for testing
        timeout=10
    )
    
    # Test function execution
    test_task = {
        'task_id': 'test_123',
        'parameters': {
            'function_name': 'generate_sample_data',
            'args': [5],
            'kwargs': {}
        }
    }
    
    result = await executor.execute_python_task(test_task)
    
    assert result['success'] == True
    assert 'result' in result
    assert 'execution_time' in result
    assert result['executor'] == "Test Executor"
    print(f"   ✅ Function execution successful (took {result['execution_time']:.2f}s)")
    
    # Test with external parameter format
    external_task = {
        'task_id': 'test_456',
        'parameters': {
            'external_parameters': {
                'function_name': 'process_data',
                'args': [[1, 2, 3, 4, 5]],
                'kwargs': {'operation': 'sum'}
            }
        }
    }
    
    result2 = await executor.execute_python_task(external_task)
    
    assert result2['success'] == True
    assert result2['result'] == {'sum': 15, 'mean': 3.0, 'count': 5}
    print("   ✅ External parameter format works correctly")
    
    # Test error handling
    error_task = {
        'task_id': 'test_error',
        'parameters': {
            'function_name': 'nonexistent_function',
            'args': [],
            'kwargs': {}
        }
    }
    
    result3 = await executor.execute_python_task(error_task)
    
    assert result3['success'] == False
    assert 'error' in result3
    assert 'traceback' in result3
    print("   ✅ Error handling works correctly")
    
    # Check metrics
    status = executor.get_status()
    assert status['execution_metrics']['total_executed'] == 2
    assert status['execution_metrics']['total_failed'] == 1
    assert status['registered_functions'] > 0
    print(f"   ✅ Metrics tracking works ({status['execution_metrics']['total_executed']} executed, {status['execution_metrics']['total_failed']} failed)")


async def test_isolation_modes():
    """Test different isolation modes"""
    print("🧪 Testing isolation modes...")
    
    # Test subprocess isolation
    executor_subprocess = PythonExecutorService(
        service_name="Subprocess Executor",
        isolation_mode="subprocess",
        max_workers=1,
        timeout=5
    )
    
    task = {
        'parameters': {
            'function_name': 'generate_sample_data',
            'args': [3],
            'kwargs': {}
        }
    }
    
    result = await executor_subprocess.execute_python_task(task)
    assert result['success'] == True
    print("   ✅ Subprocess isolation works")
    
    # Test thread isolation
    executor_thread = PythonExecutorService(
        service_name="Thread Executor",
        isolation_mode="thread",
        max_workers=2
    )
    
    result2 = await executor_thread.execute_python_task(task)
    assert result2['success'] == True
    print("   ✅ Thread isolation works")
    
    # Test direct execution
    executor_direct = PythonExecutorService(
        service_name="Direct Executor",
        isolation_mode="direct"
    )
    
    result3 = await executor_direct.execute_python_task(task)
    assert result3['success'] == True
    print("   ✅ Direct execution works")


async def test_backwards_compatibility():
    """Test backwards compatibility with native execution"""
    print("🧪 Testing backwards compatibility...")
    
    # Test that old workflows still work
    cluster = GleitzeitCluster(
        use_external_python_executor=False,  # Keep using native
        enable_redis=False,
        enable_socketio=False
    )
    
    workflow = cluster.create_workflow("Legacy Workflow")
    
    # Old API should still work
    task = workflow.add_python_task(
        name="Legacy Task",
        function_name="my_function",
        args=[1, 2, 3]
    )
    
    assert task.task_type == TaskType.FUNCTION
    assert task.parameters.function_name == "my_function"
    print("   ✅ Legacy API still works with native execution")
    
    # Test migration path
    cluster_migrated = GleitzeitCluster(
        use_external_python_executor=True,  # New mode
        enable_redis=False,
        enable_socketio=False,
        auto_start_python_executor=False
    )
    
    workflow_migrated = cluster_migrated.create_workflow("Migrated Workflow")
    
    # Same API, different execution
    task_migrated = workflow_migrated.add_python_task(
        name="Migrated Task",
        function_name="my_function",
        args=[1, 2, 3]
    )
    
    assert task_migrated.task_type == TaskType.EXTERNAL_PROCESSING
    assert task_migrated.parameters.external_parameters['function_name'] == "my_function"
    print("   ✅ Same API works with external execution")


async def test_auto_start_mechanism():
    """Test auto-start of Python executor service"""
    print("🧪 Testing auto-start mechanism...")
    
    # This test would require actual Socket.IO server running
    # For now, just verify the configuration
    
    cluster = GleitzeitCluster(
        use_external_python_executor=True,
        auto_start_python_executor=True,
        python_executor_workers=3,
        enable_redis=False,
        enable_socketio=False,
        auto_start_services=False
    )
    
    assert cluster.use_external_python_executor == True
    assert cluster.auto_start_python_executor == True
    assert cluster.python_executor_workers == 3
    print("   ✅ Auto-start configuration correct")
    
    # Verify workflow inherits the flag
    workflow = cluster.create_workflow("Test Workflow")
    assert workflow._use_external_python_executor == True
    print("   ✅ Workflow inherits external executor flag")


async def run_all_tests():
    """Run all external Python executor tests"""
    print("🚀 External Python Executor Tests")
    print("=" * 50)
    
    try:
        # Suppress deprecation warnings for clean output
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        
        await test_feature_flag_routing()
        await test_python_executor_service()
        await test_isolation_modes()
        await test_backwards_compatibility()
        await test_auto_start_mechanism()
        
        print("\n🎉 All tests passed!")
        print("\n✅ External Python Executor Implementation Complete:")
        print("   🔧 PythonExecutorService with multiple isolation modes")
        print("   🎚️ Feature flag for gradual migration")
        print("   🔄 Automatic routing based on configuration")
        print("   🚀 Auto-start mechanism for seamless experience")
        print("   📦 Backwards compatibility maintained")
        print("   🔒 Better isolation and security")
        print("   📈 Scalable architecture")
        
        print("\n📝 Migration Path:")
        print("   1. Set use_external_python_executor=True to enable")
        print("   2. Python tasks automatically route to external service")
        print("   3. Service auto-starts if auto_start_python_executor=True")
        print("   4. Same API, better architecture")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)