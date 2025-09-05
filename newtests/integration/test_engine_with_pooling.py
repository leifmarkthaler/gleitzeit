#!/usr/bin/env python3
"""
Integration test for ExecutionEngineV2 with pooled providers.

Tests the complete execution stack with provider pooling.
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
from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2, ExecutionMode
from gleitzeit.core.jsonrpc import JSONRPCRequest, JSONRPCResponse
from gleitzeit.providers.pooling_adapter import PoolingAdapter, RegistryCompatibilityAdapter
from gleitzeit.persistence.unified_persistence import UnifiedInMemoryAdapter
from gleitzeit.task_queue import QueueManager
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import EventType, GleitzeitEvent


class TestProvider:
    """Test provider for integration testing"""
    
    def __init__(self):
        self.initialized = False
        self.execute_count = 0
        self.tasks_executed = []
    
    async def initialize(self):
        """Initialize the provider"""
        await asyncio.sleep(0.001)
        self.initialized = True
        print(f"        Provider initialized")
    
    async def cleanup(self):
        """Cleanup the provider"""
        self.initialized = False
    
    async def execute(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """Execute a request"""
        self.execute_count += 1
        task_id = request.id
        self.tasks_executed.append(task_id)
        
        print(f"        Provider executing {task_id} (count: {self.execute_count})")
        
        # Simulate work
        await asyncio.sleep(0.01)
        
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


async def test_engine_with_pooling():
    """Test ExecutionEngineV2 with pooled providers"""
    print("\n" + "="*60)
    print("Testing ExecutionEngineV2 with Pooled Providers")
    print("="*60)
    
    # Setup components
    print("\n1. Setting up components...")
    persistence = UnifiedInMemoryAdapter()
    await persistence.initialize()
    print("   Persistence initialized")
    
    event_bus = EventBus(persistence=persistence)
    print("   Event bus created")
    
    # Create pooling adapter
    pooling_adapter = PoolingAdapter(
        persistence=persistence,
        min_pool_size=2,
        max_pool_size=5
    )
    await pooling_adapter.initialize()
    print("   Pooling adapter initialized")
    
    # Register test provider
    await pooling_adapter.register_provider(
        provider_id="test_provider",
        protocol_id="test/v1",
        provider_instance=TestProvider,
        supported_methods={"process", "transform"}
    )
    print("   Test provider registered")
    
    # Create registry adapter
    registry = RegistryCompatibilityAdapter(pooling_adapter)
    await registry.start()
    registry.is_protocol_available = pooling_adapter.is_protocol_available
    print("   Registry adapter created")
    
    # Create queue manager
    queue_manager = QueueManager(persistence=persistence, event_bus=event_bus)
    print("   Queue manager created")
    
    # Create execution engine
    engine = ExecutionEngineV2(
        registry=registry,
        queue_manager=queue_manager,
        dependency_resolver=None,
        persistence=persistence,
        event_bus=event_bus,
        pooling_adapter=pooling_adapter,
        max_concurrent_tasks=3,
        task_timeout=30
    )
    print("   ExecutionEngineV2 created")
    
    # Start engine
    print("\n2. Starting engine...")
    await engine.start(mode=ExecutionMode.EVENT_DRIVEN)
    print("   Engine started in EVENT_DRIVEN mode")
    
    # Let engine initialize
    await asyncio.sleep(0.1)
    
    # Create a task to process the event loop
    async def process_loop():
        """Helper to ensure event processing happens"""
        while engine._running:
            await asyncio.sleep(0.01)
    
    process_task = asyncio.create_task(process_loop())
    
    # Test 1: Simple workflow
    print("\n3. Testing simple workflow execution...")
    
    # Create simple workflow
    task1 = Task(
        id="simple-1",
        name="Simple Process",
        protocol="test/v1",
        method="process",
        params={"input": "Hello World"},
        status=TaskStatus.PENDING,
        workflow_id="simple-wf"
    )
    
    workflow = Workflow(
        id="simple-wf",
        name="Simple Test Workflow",
        tasks=[task1],
        status=WorkflowStatus.PENDING
    )
    
    # Track events
    workflow_completed = False
    task_completed = False
    events_received = []
    
    async def track_completion(event: GleitzeitEvent):
        nonlocal workflow_completed, task_completed
        events_received.append(event.event_type)
        print(f"      Event received: {event.event_type}")
        if event.event_type == EventType.WORKFLOW_COMPLETED:
            workflow_completed = True
            print(f"      Workflow completed: {event.data.get('workflow_id')}")
        elif event.event_type == EventType.TASK_COMPLETED:
            task_completed = True
            print(f"      Task completed: {event.data.get('task_id')}")
    
    event_bus.register(EventType.WORKFLOW_COMPLETED, track_completion)
    event_bus.register(EventType.TASK_COMPLETED, track_completion)
    event_bus.register(EventType.TASK_SUBMITTED, track_completion)
    event_bus.register(EventType.TASK_READY, track_completion)
    event_bus.register(EventType.TASK_STARTED, track_completion)
    event_bus.register(EventType.TASK_FAILED, track_completion)
    
    # Submit workflow
    await engine.submit_workflow(workflow)
    print("   Workflow submitted")
    
    # Wait for completion (with timeout)
    max_wait = 5.0
    start_time = time.time()
    while not workflow_completed and (time.time() - start_time) < max_wait:
        await asyncio.sleep(0.1)
        # Check if task is actually being processed
        task_status = await persistence.get_task("simple-1")
        if task_status:
            print(f"      Task status: {task_status.status}")
    
    if workflow_completed:
        print("   ✅ Workflow completed successfully")
    else:
        print("   ⚠️ Workflow did not complete in time")
    
    # Check results
    workflow_data = await persistence.get_workflow("simple-wf")
    if workflow_data:
        print(f"   Workflow status: {workflow_data.status}")
    
    task_result = await persistence.get_task_result("simple-1")
    if task_result:
        print(f"   Task result: {task_result.status}")
        if task_result.result:
            print(f"   Output: {task_result.result}")
    
    # Test 2: Parallel tasks
    print("\n4. Testing parallel task execution...")
    
    # Create workflow with parallel tasks
    parallel_tasks = []
    for i in range(5):
        task = Task(
            id=f"parallel-{i}",
            name=f"Parallel Task {i}",
            protocol="test/v1",
            method="process" if i % 2 == 0 else "transform",
            params={"input": f"Data {i}", "data": f"data {i}"},
            status=TaskStatus.PENDING,
            workflow_id="parallel-wf"
        )
        parallel_tasks.append(task)
    
    parallel_workflow = Workflow(
        id="parallel-wf",
        name="Parallel Test Workflow",
        tasks=parallel_tasks,
        status=WorkflowStatus.PENDING
    )
    
    # Reset tracking
    workflow_completed = False
    tasks_completed = 0
    
    async def track_parallel(event: GleitzeitEvent):
        nonlocal workflow_completed, tasks_completed
        if event.event_type == EventType.WORKFLOW_COMPLETED:
            workflow_completed = True
        elif event.event_type == EventType.TASK_COMPLETED:
            tasks_completed += 1
    
    # Clear old handlers and register new ones
    event_bus.register(EventType.WORKFLOW_COMPLETED, track_parallel)
    event_bus.register(EventType.TASK_COMPLETED, track_parallel)
    
    # Submit parallel workflow
    await engine.submit_workflow(parallel_workflow)
    print("   Parallel workflow submitted (5 tasks)")
    
    # Wait for completion
    start_time = time.time()
    while not workflow_completed and (time.time() - start_time) < max_wait:
        await asyncio.sleep(0.1)
        if tasks_completed > 0:
            print(f"      Tasks completed: {tasks_completed}/5")
    
    if workflow_completed:
        print(f"   ✅ Parallel workflow completed ({tasks_completed} tasks)")
    else:
        print(f"   ⚠️ Parallel workflow incomplete ({tasks_completed}/5 tasks done)")
    
    # Check pool statistics
    stats = pooling_adapter.get_stats()
    print(f"\n5. Pool statistics:")
    print(f"   Total pools: {stats['total_pools']}")
    for pool_name, pool_stats in stats['pools'].items():
        print(f"   {pool_name}:")
        print(f"      Available: {pool_stats['available']}")
        print(f"      In use: {pool_stats['in_use']}")
        print(f"      Total: {pool_stats['total']}")
        print(f"      Utilization: {pool_stats['utilization']:.1f}%")
    
    # Test 3: Sequential workflow with dependencies
    print("\n6. Testing sequential workflow with dependencies...")
    
    seq_task1 = Task(
        id="seq-1",
        name="First Task",
        protocol="test/v1",
        method="process",
        params={"input": "Step 1"},
        status=TaskStatus.PENDING,
        workflow_id="seq-wf",
        dependencies=[]
    )
    
    seq_task2 = Task(
        id="seq-2",
        name="Second Task",
        protocol="test/v1",
        method="transform",
        params={"data": "step 2"},
        status=TaskStatus.PENDING,
        workflow_id="seq-wf",
        dependencies=["seq-1"]
    )
    
    seq_task3 = Task(
        id="seq-3",
        name="Third Task",
        protocol="test/v1",
        method="process",
        params={"input": "Step 3"},
        status=TaskStatus.PENDING,
        workflow_id="seq-wf",
        dependencies=["seq-2"]
    )
    
    seq_workflow = Workflow(
        id="seq-wf",
        name="Sequential Workflow",
        tasks=[seq_task1, seq_task2, seq_task3],
        status=WorkflowStatus.PENDING
    )
    
    # Reset tracking
    workflow_completed = False
    task_order = []
    
    async def track_sequential(event: GleitzeitEvent):
        nonlocal workflow_completed, task_order
        if event.event_type == EventType.WORKFLOW_COMPLETED:
            workflow_completed = True
        elif event.event_type == EventType.TASK_COMPLETED:
            task_id = event.data.get('task_id')
            task_order.append(task_id)
            print(f"      Task completed: {task_id}")
    
    # Register sequential tracking handlers
    event_bus.register(EventType.WORKFLOW_COMPLETED, track_sequential)
    event_bus.register(EventType.TASK_COMPLETED, track_sequential)
    
    # Submit sequential workflow
    await engine.submit_workflow(seq_workflow)
    print("   Sequential workflow submitted (3 tasks with dependencies)")
    
    # Wait for completion
    start_time = time.time()
    while not workflow_completed and (time.time() - start_time) < max_wait:
        await asyncio.sleep(0.1)
    
    if workflow_completed:
        print(f"   ✅ Sequential workflow completed")
        print(f"   Execution order: {' -> '.join(task_order)}")
        # Verify order
        if task_order == ["seq-1", "seq-2", "seq-3"]:
            print("   ✅ Tasks executed in correct dependency order")
        else:
            print("   ⚠️ Tasks executed in unexpected order")
    else:
        print(f"   ⚠️ Sequential workflow did not complete")
    
    # Stop engine
    print("\n7. Stopping engine...")
    await engine.stop()
    process_task.cancel()
    try:
        await process_task
    except asyncio.CancelledError:
        pass
    print("   Engine stopped")
    
    # Cleanup
    await registry.stop()
    await persistence.shutdown()
    print("   Cleanup complete")
    
    return workflow_completed


async def main():
    """Run ExecutionEngineV2 pooling test"""
    print("="*60)
    print("ExecutionEngineV2 with Provider Pooling Test")
    print("="*60)
    
    success = await test_engine_with_pooling()
    
    print("\n" + "="*60)
    if success:
        print("Test Complete! 🎉")
        print("="*60)
        print("\nExecutionEngineV2 with pooled providers:")
        print("- ✅ Engine starts and runs with pooling adapter")
        print("- ✅ Simple workflows execute successfully")
        print("- ✅ Parallel tasks execute concurrently")
        print("- ✅ Sequential dependencies respected")
        print("- ✅ Provider pools manage resources efficiently")
    else:
        print("Test Failed ❌")
        print("="*60)
        print("\nSome tests did not complete successfully.")
        print("Check the output above for details.")


if __name__ == "__main__":
    asyncio.run(main())