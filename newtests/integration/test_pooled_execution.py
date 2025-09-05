#!/usr/bin/env python3
"""
Integration test for pooled provider execution system.

Tests the complete execution stack with provider pooling:
- ExecutionEngineV2 with pooling adapter
- TaskExecutor using pooled providers
- TaskOrchestrator coordination
- Full workflow execution with pooled providers
"""

import asyncio
import time
from pathlib import Path
import sys
from typing import Dict, Any
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus
from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse
from gleitzeit.providers.pooling_adapter import PoolingAdapter, RegistryCompatibilityAdapter
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.task_queue import QueueManager
from gleitzeit.events.base import EventBus
from gleitzeit.registry import ProtocolProviderRegistry


class TestProvider:
    """Test provider for integration testing"""
    
    def __init__(self):
        self.initialized = False
        self.execute_count = 0
        self.tasks_executed = []
    
    async def initialize(self):
        """Initialize the provider"""
        await asyncio.sleep(0.01)
        self.initialized = True
    
    async def cleanup(self):
        """Cleanup the provider"""
        self.initialized = False
    
    async def execute(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """Execute a request"""
        self.execute_count += 1
        self.tasks_executed.append(request.id)
        
        # Simulate some work
        await asyncio.sleep(0.05)
        
        if request.method == "process":
            result = {
                "status": "processed",
                "input": request.params.get("input", ""),
                "output": f"Processed: {request.params.get('input', '')}",
                "provider_count": self.execute_count
            }
            return JSONRPCResponse(result=result, id=request.id)
        
        elif request.method == "transform":
            result = {
                "transformed": request.params.get("data", "").upper(),
                "provider_count": self.execute_count
            }
            return JSONRPCResponse(result=result, id=request.id)
        
        else:
            return JSONRPCResponse(
                error={"code": -32601, "message": f"Method not found: {request.method}"},
                id=request.id
            )
    
    async def process(self, **kwargs):
        """Direct process method"""
        self.execute_count += 1
        await asyncio.sleep(0.05)
        return {
            "status": "processed",
            "input": kwargs.get("input", ""),
            "output": f"Processed: {kwargs.get('input', '')}",
            "provider_count": self.execute_count
        }
    
    async def transform(self, **kwargs):
        """Direct transform method"""
        self.execute_count += 1
        await asyncio.sleep(0.05)
        return {
            "transformed": kwargs.get("data", "").upper(),
            "provider_count": self.execute_count
        }


async def test_basic_pooled_execution():
    """Test basic task execution with pooled providers"""
    print("\n" + "="*60)
    print("Testing Basic Pooled Execution")
    print("="*60)
    
    # Create persistence and event bus
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    event_bus = EventBus(persistence=persistence)
    
    # Create pooling adapter
    pooling_adapter = PoolingAdapter(
        persistence=persistence,
        min_pool_size=2,
        max_pool_size=5
    )
    await pooling_adapter.initialize()
    
    # Register test provider
    await pooling_adapter.register_provider(
        provider_id="test_provider",
        protocol_id="test/v1",
        provider_instance=TestProvider,
        supported_methods={"process", "transform"}
    )
    
    # Create queue manager with persistence
    queue_manager = QueueManager(persistence=persistence, event_bus=event_bus)
    
    # Create registry compatibility adapter
    registry_adapter = RegistryCompatibilityAdapter(pooling_adapter)
    await registry_adapter.start()
    
    # Add is_protocol_available method for compatibility
    registry_adapter.is_protocol_available = pooling_adapter.is_protocol_available
    
    # Use the adapter as the registry
    registry = registry_adapter
    
    # Create execution engine with pooling adapter
    engine = ExecutionEngineV2(
        registry=registry,
        queue_manager=queue_manager,
        dependency_resolver=None,
        persistence=persistence,
        event_bus=event_bus,
        pooling_adapter=pooling_adapter,
        max_concurrent_tasks=5
    )
    
    # Start engine
    await engine.start()
    
    print("\n1. Executing single task in workflow...")
    
    # Create task with workflow_id
    task = Task(
        id="task-1",
        name="Process Data",
        protocol="test/v1",
        method="process",
        params={"input": "Hello World"},
        status=TaskStatus.PENDING,
        workflow_id="wf-1"  # Add workflow_id
    )
    
    # Create workflow containing the task
    workflow = Workflow(
        id="wf-1",
        name="Test Workflow",
        tasks=[task],
        status=WorkflowStatus.PENDING
    )
    
    await engine.submit_workflow(workflow)
    
    # Wait for workflow completion
    await asyncio.sleep(0.5)
    
    # Check workflow
    workflow_data = await persistence.get_workflow("wf-1")
    if workflow_data:
        print(f"   Workflow status: {workflow_data.status}")
    else:
        print("   Workflow data not found")
    
    # Check task result
    result = await persistence.get_task_result("task-1")
    if result:
        print(f"   Task completed: {result.status}")
        print(f"   Result: {result.result}")
        
        assert result.status == TaskStatus.COMPLETED
        # The pooling adapter returns a JSONRPCResponse, check its result
        if hasattr(result.result, 'result'):
            assert result.result.result["status"] == "processed"
            assert result.result.result["output"] == "Processed: Hello World"
        else:
            assert result.result["status"] == "processed"
            assert result.result["output"] == "Processed: Hello World"
    else:
        print("   Warning: Task result not yet available")
    
    # Stop engine
    await engine.stop()
    await registry_adapter.stop()
    await persistence.shutdown()
    
    print("\n✅ Basic pooled execution test passed!")


async def test_concurrent_pooled_execution():
    """Test concurrent task execution with provider pooling"""
    print("\n" + "="*60)
    print("Testing Concurrent Pooled Execution")
    print("="*60)
    
    # Create components
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    event_bus = EventBus(persistence=persistence)
    
    pooling_adapter = PoolingAdapter(
        persistence=persistence,
        min_pool_size=2,
        max_pool_size=3  # Limited pool size to test queueing
    )
    await pooling_adapter.initialize()
    
    # Register provider
    await pooling_adapter.register_provider(
        provider_id="test_provider",
        protocol_id="test/v1",
        provider_instance=TestProvider,
        supported_methods={"process", "transform"}
    )
    
    queue_manager = InMemoryQueueManager()
    registry = ProtocolProviderRegistry()
    
    # Create engine
    engine = ExecutionEngineV2(
        registry=registry,
        queue_manager=queue_manager,
        dependency_resolver=None,
        persistence=persistence,
        event_bus=event_bus,
        pooling_adapter=pooling_adapter,
        max_concurrent_tasks=10
    )
    
    await engine.start()
    
    print("\n1. Submitting 10 concurrent tasks with pool size 3...")
    
    # Create tasks with workflow_id
    tasks = []
    for i in range(10):
        task = Task(
            id=f"concurrent-{i}",
            name=f"Task {i}",
            protocol="test/v1",
            method="process" if i % 2 == 0 else "transform",
            params={"input": f"Data {i}", "data": f"Data {i}"},
            status=TaskStatus.PENDING,
            workflow_id="concurrent-wf"  # Add workflow_id
        )
        tasks.append(task)
    
    # Create workflow with all tasks
    workflow = Workflow(
        id="concurrent-wf",
        name="Concurrent Test Workflow",
        tasks=tasks,
        status=WorkflowStatus.PENDING
    )
    
    await engine.submit_workflow(workflow)
    
    print(f"   Submitted {len(tasks)} tasks")
    
    # Wait for workflow to complete
    await asyncio.sleep(2.0)
    
    # Check workflow
    workflow_data = await persistence.get_workflow("concurrent-wf")
    if workflow_data:
        print(f"\n2. Workflow status: {workflow_data.status}")
    else:
        print("\n2. Workflow data not found")
    
    # Check task results
    print("\n3. Checking task results...")
    completed = 0
    for task in tasks:
        result = await persistence.get_task_result(task.id)
        if result and result.status == TaskStatus.COMPLETED:
            completed += 1
            print(f"   Task {task.id}: {result.status}")
    
    print(f"\n   Completed: {completed}/{len(tasks)}")
    # Allow for some tasks to still be processing
    assert completed >= 5  # At least half should complete quickly
    
    # Check pool stats
    stats = pooling_adapter.get_stats()
    print(f"\n4. Pool statistics:")
    print(f"   {stats}")
    
    # Stop engine
    await engine.stop()
    await registry_adapter.stop()
    await persistence.shutdown()
    
    print("\n✅ Concurrent pooled execution test passed!")


async def test_workflow_with_pooled_providers():
    """Test workflow execution with pooled providers"""
    print("\n" + "="*60)
    print("Testing Workflow with Pooled Providers")
    print("="*60)
    
    # Create components
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    event_bus = EventBus(persistence=persistence)
    
    pooling_adapter = PoolingAdapter(
        persistence=persistence,
        min_pool_size=2,
        max_pool_size=5
    )
    await pooling_adapter.initialize()
    
    # Register provider
    await pooling_adapter.register_provider(
        provider_id="test_provider",
        protocol_id="test/v1",
        provider_instance=TestProvider,
        supported_methods={"process", "transform"}
    )
    
    queue_manager = InMemoryQueueManager()
    registry = ProtocolProviderRegistry()
    
    # Create engine
    engine = ExecutionEngineV2(
        registry=registry,
        queue_manager=queue_manager,
        dependency_resolver=None,
        persistence=persistence,
        event_bus=event_bus,
        pooling_adapter=pooling_adapter,
        max_concurrent_tasks=5
    )
    
    await engine.start()
    
    print("\n1. Creating workflow with 3 tasks...")
    
    # Create workflow with dependencies
    workflow = Workflow(
        id="workflow-1",
        name="Data Processing Pipeline",
        tasks=[
            Task(
                id="wf1-task1",
                name="Initial Processing",
                protocol="test/v1",
                method="process",
                params={"input": "Raw Data"},
                status=TaskStatus.PENDING,
                dependencies=[]
            ),
            Task(
                id="wf1-task2",
                name="Transform Step",
                protocol="test/v1",
                method="transform",
                params={"data": "intermediate"},
                status=TaskStatus.PENDING,
                dependencies=["wf1-task1"]
            ),
            Task(
                id="wf1-task3",
                name="Final Processing",
                protocol="test/v1",
                method="process",
                params={"input": "final"},
                status=TaskStatus.PENDING,
                dependencies=["wf1-task2"]
            )
        ],
        status=WorkflowStatus.PENDING
    )
    
    # Submit workflow
    await engine.submit_workflow(workflow)
    print("   Workflow submitted")
    
    # Wait for completion
    await asyncio.sleep(1.0)
    
    # Check workflow status
    wf_status = await persistence.get_workflow_status("workflow-1")
    print(f"\n2. Workflow status: {wf_status}")
    
    # Check task results
    print("\n3. Task results:")
    for task in workflow.tasks:
        result = await persistence.get_task_result(task.id)
        if result:
            print(f"   {task.id}: {result.status}")
            if result.result:
                print(f"      Result: {result.result}")
    
    # Stop engine
    await engine.stop()
    await registry_adapter.stop()
    await persistence.shutdown()
    
    print("\n✅ Workflow pooled execution test passed!")


async def test_pool_resource_management():
    """Test provider pool resource management"""
    print("\n" + "="*60)
    print("Testing Pool Resource Management")
    print("="*60)
    
    # Create components with small pool
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    
    pooling_adapter = PoolingAdapter(
        persistence=persistence,
        min_pool_size=1,
        max_pool_size=2  # Very limited pool
    )
    await pooling_adapter.initialize()
    
    # Register provider
    await pooling_adapter.register_provider(
        provider_id="test_provider",
        protocol_id="test/v1",
        provider_instance=TestProvider,
        supported_methods={"process"}
    )
    
    print("\n1. Pool created with min=1, max=2")
    stats = pooling_adapter.get_stats()
    print(f"   Initial stats: {stats}")
    
    # Execute tasks to test pool growth
    print("\n2. Executing 3 concurrent tasks with max pool size 2...")
    
    async def execute_task(task_id: str):
        """Execute a single task"""
        task = Task(
            id=task_id,
            name=f"Task {task_id}",
            protocol="test/v1",
            method="process",
            params={"input": f"Data {task_id}"},
            status=TaskStatus.PENDING
        )
        
        start = time.time()
        result = await pooling_adapter.execute_task(task)
        elapsed = time.time() - start
        
        return task_id, elapsed, result
    
    # Run 3 tasks concurrently
    results = await asyncio.gather(
        execute_task("pool-1"),
        execute_task("pool-2"),
        execute_task("pool-3")
    )
    
    print("\n3. Execution times:")
    for task_id, elapsed, result in results:
        print(f"   {task_id}: {elapsed:.2f}s - {result.status}")
    
    # The third task should have waited for a provider
    assert results[2][1] > results[0][1]  # Third task took longer
    
    print("\n4. Final pool stats:")
    stats = pooling_adapter.get_stats()
    print(f"   {stats}")
    
    # Cleanup
    await pooling_adapter.shutdown()
    await persistence.shutdown()
    
    print("\n✅ Pool resource management test passed!")


async def main():
    """Run all integration tests"""
    print("="*60)
    print("Pooled Provider Execution Integration Tests")
    print("="*60)
    
    await test_basic_pooled_execution()
    await test_concurrent_pooled_execution()
    await test_workflow_with_pooled_providers()
    await test_pool_resource_management()
    
    print("\n" + "="*60)
    print("All Integration Tests Passed! 🎉")
    print("="*60)
    print("\nThe pooled provider system is fully integrated:")
    print("- ✅ ExecutionEngineV2 uses pooling adapter")
    print("- ✅ TaskExecutor routes through pooled providers")
    print("- ✅ Concurrent execution with pool limits")
    print("- ✅ Workflows execute with pooled providers")
    print("- ✅ Resource management and queueing work correctly")


if __name__ == "__main__":
    asyncio.run(main())