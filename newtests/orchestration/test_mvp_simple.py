"""
Simple test to verify orchestration MVP works
"""

import pytest
import asyncio
from datetime import datetime

from gleitzeit.core.models import Task, Workflow
from gleitzeit.orchestration.client_adapter import OrchestrationClient
from gleitzeit.persistence.base import InMemoryBackend
from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter


class SimpleMockProvider:
    """Simple mock provider for testing"""
    
    def __init__(self, protocol_name="mock"):
        self.protocol_name = protocol_name
        self.executed = []
        
    async def execute(self, method: str, params: dict):
        """Execute mock task"""
        print(f"[{self.protocol_name}] Executing {method} with {params}")
        self.executed.append({
            "method": method,
            "params": params,
            "timestamp": datetime.utcnow()
        })
        await asyncio.sleep(0.01)  # Simulate work
        return {"status": "success", "method": method}


@pytest.fixture
async def redis_backend():
    """Create Redis backend for testing"""
    backend = UnifiedRedisAdapter()
    await backend.initialize()
    
    # Clear test data
    await backend.redis.flushdb()
    
    yield backend
    
    # Cleanup
    await backend.redis.flushdb()
    await backend.cleanup()


@pytest.fixture
async def memory_backend():
    """Create in-memory backend for testing"""
    backend = InMemoryBackend()
    await backend.initialize()
    yield backend
    await backend.cleanup()


class TestOrchestrationMVP:
    """Basic tests for orchestration MVP"""
    
    @pytest.mark.asyncio
    async def test_simple_workflow_with_memory_backend(self, memory_backend):
        """Test simple workflow execution with in-memory backend"""
        # Create provider
        provider = SimpleMockProvider(protocol_name="test")
        
        # Create client
        client = OrchestrationClient(
            persistence_backend=memory_backend,
            providers={"test": provider}
        )
        
        # Start client
        await client.start()
        
        try:
            # Create simple workflow
            task = Task(
                id="simple-task",
                name="Simple Task",
                protocol="test",
                method="test_method",
                params={"message": "Hello from orchestration"}
            )
            
            workflow = Workflow(
                id="simple-workflow",
                name="Simple Test Workflow",
                tasks=[task]
            )
            
            # Execute workflow
            workflow_id = await client.execute_workflow(workflow)
            print(f"Submitted workflow: {workflow_id}")
            
            # Wait for completion
            status = await client.wait_for_workflow(workflow_id, timeout=5.0)
            print(f"Workflow completed with status: {status}")
            
            # Verify execution
            assert len(provider.executed) == 1
            assert provider.executed[0]["method"] == "test_method"
            
            # Check final status
            workflow_status = client.get_workflow_status(workflow_id)
            assert workflow_status is not None
            assert workflow_status["completed_tasks"] == 1
            
        finally:
            await client.stop()
    
    @pytest.mark.asyncio
    async def test_workflow_with_dependencies(self, memory_backend):
        """Test workflow with task dependencies"""
        # Create provider
        provider = SimpleMockProvider(protocol_name="test")
        
        # Create client
        client = OrchestrationClient(
            persistence_backend=memory_backend,
            providers={"test": provider}
        )
        
        await client.start()
        
        try:
            # Create workflow with dependencies
            task1 = Task(
                id="task-1",
                name="First Task",
                protocol="test",
                method="first_method",
                params={"step": 1}
            )
            
            task2 = Task(
                id="task-2",
                name="Second Task",
                protocol="test",
                method="second_method",
                params={"step": 2},
                dependencies=["task-1"]
            )
            
            task3 = Task(
                id="task-3",
                name="Third Task",
                protocol="test",
                method="third_method",
                params={"step": 3},
                dependencies=["task-2"]
            )
            
            workflow = Workflow(
                id="dependency-workflow",
                name="Workflow with Dependencies",
                tasks=[task1, task2, task3]
            )
            
            # Execute workflow
            workflow_id = await client.execute_workflow(workflow)
            print(f"Submitted workflow with dependencies: {workflow_id}")
            
            # Wait for completion
            status = await client.wait_for_workflow(workflow_id, timeout=5.0)
            print(f"Workflow completed with status: {status}")
            
            # Verify all tasks executed in order
            assert len(provider.executed) == 3
            methods = [e["method"] for e in provider.executed]
            assert methods == ["first_method", "second_method", "third_method"]
            
            # Verify execution order by checking steps
            steps = [e["params"]["step"] for e in provider.executed]
            assert steps == [1, 2, 3]
            
        finally:
            await client.stop()
    
    @pytest.mark.asyncio
    async def test_parallel_tasks(self, memory_backend):
        """Test parallel task execution"""
        # Create provider
        provider = SimpleMockProvider(protocol_name="test")
        
        # Create client  
        client = OrchestrationClient(
            persistence_backend=memory_backend,
            providers={"test": provider}
        )
        
        await client.start()
        
        try:
            # Create workflow with parallel tasks
            tasks = []
            for i in range(3):
                task = Task(
                    id=f"parallel-{i}",
                    name=f"Parallel Task {i}",
                    protocol="test",
                    method=f"parallel_method_{i}",
                    params={"index": i}
                )
                tasks.append(task)
            
            workflow = Workflow(
                id="parallel-workflow",
                name="Parallel Tasks Workflow",
                tasks=tasks
            )
            
            # Execute workflow
            workflow_id = await client.execute_workflow(workflow)
            print(f"Submitted parallel workflow: {workflow_id}")
            
            # Wait for completion
            status = await client.wait_for_workflow(workflow_id, timeout=5.0)
            print(f"Workflow completed with status: {status}")
            
            # Verify all tasks executed
            assert len(provider.executed) == 3
            
            # Check all methods were called
            executed_methods = {e["method"] for e in provider.executed}
            expected_methods = {f"parallel_method_{i}" for i in range(3)}
            assert executed_methods == expected_methods
            
        finally:
            await client.stop()


@pytest.mark.asyncio
async def test_with_redis_backend(redis_backend):
    """Test orchestration with Redis backend"""
    # Create provider
    provider = SimpleMockProvider(protocol_name="redis_test")
    
    # Create client with Redis backend
    client = OrchestrationClient(
        persistence_backend=redis_backend,
        providers={"redis_test": provider}
    )
    
    await client.start()
    
    try:
        # Create simple workflow
        task = Task(
            id="redis-task",
            name="Redis Task",
            protocol="redis_test",
            method="redis_method",
            params={"backend": "redis"}
        )
        
        workflow = Workflow(
            id="redis-workflow",
            name="Redis Test Workflow",
            tasks=[task]
        )
        
        # Execute workflow
        workflow_id = await client.execute_workflow(workflow)
        print(f"Submitted workflow with Redis: {workflow_id}")
        
        # Wait for completion
        status = await client.wait_for_workflow(workflow_id, timeout=5.0)
        print(f"Workflow completed with status: {status}")
        
        # Verify execution
        assert len(provider.executed) == 1
        assert provider.executed[0]["method"] == "redis_method"
        
        # Verify task was queued in Redis
        # The queue should be empty after processing
        queue_length = await redis_backend.redis.llen("provider:queue:redis_test")
        assert queue_length == 0
        
    finally:
        await client.stop()


if __name__ == "__main__":
    """Allow running tests directly"""
    import sys
    
    async def run_tests():
        """Run tests manually"""
        print("Running orchestration MVP tests...")
        
        # Test with in-memory backend
        print("\n1. Testing with in-memory backend...")
        memory_backend = InMemoryBackend()
        await memory_backend.initialize()
        
        test = TestOrchestrationMVP()
        try:
            await test.test_simple_workflow_with_memory_backend(memory_backend)
            print("✓ Simple workflow test passed")
            
            await test.test_workflow_with_dependencies(memory_backend)
            print("✓ Dependency workflow test passed")
            
            await test.test_parallel_tasks(memory_backend)
            print("✓ Parallel tasks test passed")
            
        finally:
            await memory_backend.cleanup()
        
        # Test with Redis backend
        print("\n2. Testing with Redis backend...")
        try:
            redis_backend = UnifiedRedisAdapter()
            await redis_backend.initialize()
            await redis_backend.redis.flushdb()
            
            await test_with_redis_backend(redis_backend)
            print("✓ Redis backend test passed")
            
            await redis_backend.redis.flushdb()
            await redis_backend.cleanup()
            
        except Exception as e:
            print(f"✗ Redis test failed (Redis may not be running): {e}")
        
        print("\n✅ All tests completed!")
    
    # Run tests
    asyncio.run(run_tests())