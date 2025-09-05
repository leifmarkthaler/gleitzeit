"""
Integration test for Instructor Provider with Gleitzeit

This test verifies that the InstructorProvider actually integrates
with Gleitzeit's execution engine and registry.
"""

import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock
import sys

from gleitzeit.registry import ProtocolProviderRegistry
from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2 as ExecutionEngine
from gleitzeit.task_queue import QueueManager, DependencyResolver
from gleitzeit.core.models import Task, TaskStatus
from gleitzeit.experimental.instructor import InstructorProvider


async def test_provider_registration():
    """Test that InstructorProvider can be registered with Gleitzeit"""
    # Create registry
    registry = ProtocolProviderRegistry()
    
    # Create and register our provider
    provider = InstructorProvider()
    
    # Mock the instructor import since we don't have it installed
    provider.instructor = Mock()
    await provider.initialize()
    
    # Register with the registry
    registry.register_provider(provider)
    
    # Verify registration
    assert registry.get_provider("instructor") is not None
    registered_provider = registry.get_provider("instructor")
    assert registered_provider.provider_id == "instructor"
    assert registered_provider.protocol_id == "llm/structured"
    
    # Check that provider can handle the right methods
    assert registry.get_provider_for_method("llm/structured") == provider
    assert registry.get_provider_for_method("llm/extract") == provider
    assert registry.get_provider_for_method("llm/classify") == provider
    
    print("✓ Provider successfully registered with registry")


async def test_execution_engine_integration():
    """Test that ExecutionEngine can route tasks to InstructorProvider"""
    
    # Create components
    registry = ProtocolProviderRegistry()
    queue_manager = QueueManager()
    dependency_resolver = DependencyResolver()
    
    # Create and register InstructorProvider
    provider = InstructorProvider()
    provider.instructor = Mock()
    await provider.initialize()
    
    # Mock the structured generation to return a result
    async def mock_execute(method, params):
        return {
            "success": True,
            "data": {
                "name": "Test User",
                "age": 25,
                "email": "test@example.com"
            },
            "model": "gpt-3.5-turbo",
            "provider": "openai"
        }
    
    provider.execute = mock_execute
    registry.register_provider(provider)
    
    # Create event bus (required for modern architecture)
    from gleitzeit.events.base import EventBus
    event_bus = EventBus()
    
    # Update queue manager to use event bus
    queue_manager = QueueManager(event_bus=event_bus)
    await queue_manager.initialize()
    
    # Create execution engine with event bus
    engine = ExecutionEngine(
        registry=registry,
        queue_manager=queue_manager,
        dependency_resolver=dependency_resolver,
        event_bus=event_bus
    )
    
    # Create a task that uses our provider
    task = Task(
        id="test-structured-task",
        method="llm/structured",
        parameters={
            "schema": {
                "name": "User",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                    "email": {"type": "string"}
                }
            },
            "messages": [
                {"role": "user", "content": "Test User, 25 years old, test@example.com"}
            ]
        }
    )
    
    # Execute the task
    result = await engine.execute_task(task)
    
    # Verify execution
    assert result is not None
    assert result.status == TaskStatus.COMPLETED
    assert result.result["data"]["name"] == "Test User"
    assert result.result["data"]["age"] == 25
    
    print("✓ Task successfully executed through execution engine")


async def test_workflow_with_instructor():
    """Test a workflow that uses InstructorProvider"""
    from gleitzeit.core.models import Workflow
    from gleitzeit.core.workflow_manager import WorkflowManager
    
    # Create components
    registry = ProtocolProviderRegistry()
    queue_manager = QueueManager()
    dependency_resolver = DependencyResolver()
    
    # Register InstructorProvider
    provider = InstructorProvider()
    provider.instructor = Mock()
    await provider.initialize()
    
    # Mock execution
    call_count = 0
    async def mock_execute(method, params):
        nonlocal call_count
        call_count += 1
        
        if method == "llm/structured":
            return {
                "success": True,
                "data": {"title": "Test Story", "word_count": 500},
                "provider": "openai"
            }
        elif method == "llm/classify":
            return {
                "success": True,
                "data": {"category": "positive", "confidence": 0.95},
                "provider": "openai"
            }
        return {"success": False}
    
    provider.execute = mock_execute
    registry.register_provider(provider)
    
    # Create workflow
    workflow = Workflow(
        id="test-workflow",
        name="Instructor Test Workflow",
        tasks=[
            Task(
                id="generate",
                method="llm/structured",
                parameters={
                    "schema": {
                        "name": "Story",
                        "properties": {
                            "title": {"type": "string"},
                            "word_count": {"type": "integer"}
                        }
                    },
                    "messages": [{"role": "user", "content": "Generate a story"}]
                }
            ),
            Task(
                id="classify",
                method="llm/classify",
                parameters={
                    "text": "This is amazing!",
                    "categories": ["positive", "negative", "neutral"]
                },
                dependencies=["generate"]
            )
        ]
    )
    
    # Create event bus (required for modern architecture)
    from gleitzeit.events.base import EventBus
    event_bus = EventBus()
    
    # Update queue manager to use event bus
    queue_manager = QueueManager(event_bus=event_bus)
    await queue_manager.initialize()
    
    # Create execution engine with event bus
    engine = ExecutionEngine(
        registry=registry,
        queue_manager=queue_manager,
        dependency_resolver=dependency_resolver,
        event_bus=event_bus
    )
    
    # Execute workflow
    await engine.execute_workflow(workflow)
    
    # Verify both tasks were executed
    assert call_count == 2
    print("✓ Workflow with multiple Instructor tasks executed successfully")


async def test_provider_without_instructor_library():
    """Test that provider handles missing Instructor library gracefully"""
    provider = InstructorProvider()
    
    # Simulate missing instructor library
    with patch('builtins.__import__', side_effect=ImportError("No module named 'instructor'")):
        try:
            await provider.initialize()
            assert False, "Should have raised ProviderError"
        except Exception as e:
            assert "Instructor library not installed" in str(e)
            print("✓ Provider correctly handles missing Instructor library")


async def test_method_routing():
    """Test that methods are correctly routed to handler functions"""
    provider = InstructorProvider()
    provider.instructor = Mock()
    await provider.initialize()
    
    # Mock the internal methods
    provider._structured_generate = AsyncMock(return_value={"result": "structured"})
    provider._extract_data = AsyncMock(return_value={"result": "extract"})
    provider._classify_text = AsyncMock(return_value={"result": "classify"})
    
    # Test routing
    result1 = await provider.execute("llm/structured", {"schema": {}, "messages": []})
    assert result1["result"] == "structured"
    provider._structured_generate.assert_called_once()
    
    result2 = await provider.execute("llm/extract", {"text": "test", "schema": {}})
    assert result2["result"] == "extract"
    provider._extract_data.assert_called_once()
    
    result3 = await provider.execute("llm/classify", {"text": "test", "categories": []})
    assert result3["result"] == "classify"
    provider._classify_text.assert_called_once()
    
    print("✓ Methods correctly routed to appropriate handlers")


async def main():
    """Run all integration tests"""
    print("\n" + "="*60)
    print("Running Instructor Provider Integration Tests")
    print("="*60 + "\n")
    
    try:
        await test_provider_registration()
        await test_execution_engine_integration()
        await test_workflow_with_instructor()
        await test_provider_without_instructor_library()
        await test_method_routing()
        
        print("\n" + "="*60)
        print("✅ All integration tests passed!")
        print("="*60 + "\n")
        
        print("Next steps to fully integrate:")
        print("1. Install instructor: pip install instructor")
        print("2. Install provider SDKs: pip install openai anthropic")
        print("3. Set API keys: export OPENAI_API_KEY=...")
        print("4. Add to Gleitzeit's provider registry on startup")
        print("5. Test with real LLM calls")
        
    except Exception as e:
        print(f"\n❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)