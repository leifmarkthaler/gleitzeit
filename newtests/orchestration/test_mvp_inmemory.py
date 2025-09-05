"""
Simplified MVP test using in-memory queues instead of Redis
"""

import asyncio
from datetime import datetime
from collections import deque
from typing import Dict, Any, Optional

from gleitzeit.core.models import Task, Workflow, WorkflowStatus
from gleitzeit.orchestration.coordinator_mvp import WorkflowCoordinatorMVP
from gleitzeit.persistence.base import InMemoryBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType


class InMemoryQueueBackend(InMemoryBackend):
    """Extended InMemoryBackend with queue support for testing"""
    
    def __init__(self):
        super().__init__()
        self.queues: Dict[str, deque] = {}
        self.redis = self  # Mock redis client
    
    async def lpush(self, key: str, value: str):
        """Add to left of queue"""
        if key not in self.queues:
            self.queues[key] = deque()
        self.queues[key].appendleft(value)
    
    async def brpop(self, key: str, timeout: int = 1):
        """Blocking pop from right (simulated)"""
        # Non-blocking simulation for testing
        if key in self.queues and self.queues[key]:
            value = self.queues[key].pop()
            return (key, value)
        return None
    
    async def llen(self, key: str) -> int:
        """Get queue length"""
        return len(self.queues.get(key, []))


class SimpleMockProvider:
    """Simple mock provider"""
    
    def __init__(self, protocol_name="mock"):
        self.protocol_name = protocol_name
        self.executed = []
        
    async def execute(self, method: str, params: dict):
        """Execute mock task"""
        print(f"  [{self.protocol_name}] Executing {method}")
        self.executed.append({
            "method": method,
            "params": params,
            "timestamp": datetime.utcnow()
        })
        await asyncio.sleep(0.01)  # Simulate work
        return {"status": "success", "method": method}


class SimpleProviderAdapter:
    """Simplified provider adapter that works with in-memory queues"""
    
    def __init__(self, provider, backend, event_bus, protocol):
        self.provider = provider
        self.backend = backend
        self.event_bus = event_bus
        self.protocol = protocol
        self.queue_key = f"provider:queue:{protocol}"
        self.running = False
    
    async def start(self):
        """Start processing tasks"""
        self.running = True
        while self.running:
            # Try to get task from queue
            result = await self.backend.brpop(self.queue_key, timeout=1)
            if result:
                _, task_json = result
                await self._execute_task(task_json)
            else:
                await asyncio.sleep(0.01)
    
    async def _execute_task(self, task_json: str):
        """Execute task from queue"""
        import json
        task_data = json.loads(task_json)
        
        task_id = task_data["task_id"]
        workflow_id = task_data["workflow_id"]
        method = task_data["method"]
        params = task_data["params"]
        
        # Emit task started
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            data={
                "task_id": task_id,
                "workflow_id": workflow_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        try:
            # Execute via provider
            result = await self.provider.execute(method, params)
            
            # Emit task completed
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_COMPLETED,
                data={
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "result": result,
                    "timestamp": datetime.utcnow().isoformat()
                }
            ))
            
        except Exception as e:
            # Emit task failed
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_FAILED,
                data={
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat()
                }
            ))
    
    async def stop(self):
        """Stop adapter"""
        self.running = False


async def test_simple_workflow():
    """Test simple workflow execution"""
    print("\n=== Testing Simple Workflow ===")
    
    # Create backend and event bus
    backend = InMemoryQueueBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    # Create coordinator
    coordinator = WorkflowCoordinatorMVP(
        persistence=backend,
        event_bus=event_bus,
        node_id="test-node"
    )
    
    # Create provider and adapter
    provider = SimpleMockProvider(protocol_name="test")
    adapter = SimpleProviderAdapter(provider, backend, event_bus, "test")
    
    # Start adapter in background
    adapter_task = asyncio.create_task(adapter.start())
    
    try:
        # Create simple workflow
        task = Task(
            id="simple-task",
            name="Simple Task",
            protocol="test",
            method="test_method",
            params={"message": "Hello from MVP"}
        )
        
        workflow = Workflow(
            id="simple-workflow",
            name="Simple Test Workflow",
            tasks=[task]
        )
        
        print(f"Submitting workflow: {workflow.id}")
        
        # Submit workflow
        workflow_id = await coordinator.submit_workflow(workflow)
        
        # Wait for completion
        max_wait = 2.0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            state = coordinator.workflow_states.get(workflow_id)
            if state and state.status == WorkflowStatus.COMPLETED:
                break
            await asyncio.sleep(0.05)
        
        # Check results
        state = coordinator.workflow_states[workflow_id]
        status = coordinator.get_workflow_status(workflow_id)
        
        print(f"Workflow status: {state.status}")
        print(f"Completed tasks: {len(state.completed_tasks)}")
        print(f"Provider executed: {len(provider.executed)} tasks")
        
        if state.status == WorkflowStatus.COMPLETED:
            print("✅ Simple workflow test PASSED")
            return True
        else:
            print("❌ Simple workflow test FAILED")
            return False
            
    finally:
        # Cleanup
        await adapter.stop()
        adapter_task.cancel()
        try:
            await adapter_task
        except asyncio.CancelledError:
            pass
        await backend.shutdown()


async def test_workflow_with_dependencies():
    """Test workflow with task dependencies"""
    print("\n=== Testing Workflow with Dependencies ===")
    
    # Setup
    backend = InMemoryQueueBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    coordinator = WorkflowCoordinatorMVP(
        persistence=backend,
        event_bus=event_bus
    )
    
    provider = SimpleMockProvider(protocol_name="test")
    adapter = SimpleProviderAdapter(provider, backend, event_bus, "test")
    
    adapter_task = asyncio.create_task(adapter.start())
    
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
        
        print(f"Submitting workflow with 3 dependent tasks")
        
        # Submit workflow
        workflow_id = await coordinator.submit_workflow(workflow)
        
        # Wait for completion
        max_wait = 3.0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            state = coordinator.workflow_states.get(workflow_id)
            if state and state.status == WorkflowStatus.COMPLETED:
                break
            await asyncio.sleep(0.05)
        
        # Check results
        state = coordinator.workflow_states[workflow_id]
        
        print(f"Workflow status: {state.status}")
        print(f"Completed tasks: {len(state.completed_tasks)}")
        print(f"Execution order: {[e['method'] for e in provider.executed]}")
        
        # Verify execution order
        if (state.status == WorkflowStatus.COMPLETED and
            len(provider.executed) == 3 and
            [e["method"] for e in provider.executed] == ["first_method", "second_method", "third_method"]):
            print("✅ Dependency workflow test PASSED")
            return True
        else:
            print("❌ Dependency workflow test FAILED")
            return False
            
    finally:
        await adapter.stop()
        adapter_task.cancel()
        try:
            await adapter_task
        except asyncio.CancelledError:
            pass
        await backend.shutdown()


async def test_parallel_tasks():
    """Test parallel task execution"""
    print("\n=== Testing Parallel Tasks ===")
    
    # Setup
    backend = InMemoryQueueBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    coordinator = WorkflowCoordinatorMVP(
        persistence=backend,
        event_bus=event_bus
    )
    
    provider = SimpleMockProvider(protocol_name="test")
    adapter = SimpleProviderAdapter(provider, backend, event_bus, "test")
    
    adapter_task = asyncio.create_task(adapter.start())
    
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
        
        print(f"Submitting workflow with 3 parallel tasks")
        
        # Submit workflow
        workflow_id = await coordinator.submit_workflow(workflow)
        
        # Wait for completion
        max_wait = 2.0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            state = coordinator.workflow_states.get(workflow_id)
            if state and state.status == WorkflowStatus.COMPLETED:
                break
            await asyncio.sleep(0.05)
        
        # Check results
        state = coordinator.workflow_states[workflow_id]
        
        print(f"Workflow status: {state.status}")
        print(f"Completed tasks: {len(state.completed_tasks)}")
        print(f"Tasks executed: {[e['method'] for e in provider.executed]}")
        
        # Verify all tasks executed
        executed_methods = {e["method"] for e in provider.executed}
        expected_methods = {f"parallel_method_{i}" for i in range(3)}
        
        if (state.status == WorkflowStatus.COMPLETED and
            executed_methods == expected_methods):
            print("✅ Parallel tasks test PASSED")
            return True
        else:
            print("❌ Parallel tasks test FAILED")
            return False
            
    finally:
        await adapter.stop()
        adapter_task.cancel()
        try:
            await adapter_task
        except asyncio.CancelledError:
            pass
        await backend.shutdown()


async def main():
    """Run all tests"""
    print("=" * 50)
    print("ORCHESTRATION MVP IN-MEMORY TESTS")
    print("=" * 50)
    
    results = []
    
    # Run tests
    results.append(await test_simple_workflow())
    results.append(await test_workflow_with_dependencies())
    results.append(await test_parallel_tasks())
    
    # Summary
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✅ ALL TESTS PASSED ({passed}/{total})")
    else:
        print(f"❌ SOME TESTS FAILED ({passed}/{total} passed)")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)