"""
Test lightweight orchestrator that uses existing EventDrivenWorkflowManager
"""

import asyncio
import json
from datetime import datetime
from collections import deque

from gleitzeit.core.models import Task, Workflow, WorkflowStatus, TaskStatus, TaskResult
from gleitzeit.orchestration.task_scheduler_only import LightweightOrchestrator, TaskSchedulerOnly
from gleitzeit.orchestration.provider_pull import ProviderPullAdapter
from gleitzeit.persistence.base import InMemoryBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType
from gleitzeit.core.event_driven_workflow_manager import EventDrivenWorkflowManager


class EnhancedInMemoryBackend(InMemoryBackend):
    """InMemoryBackend with queue support for testing"""
    
    def __init__(self):
        super().__init__()
        self.queues = {}
        self.redis = self  # Mock redis
        
    async def lpush(self, key: str, value: str):
        """Add to queue"""
        if key not in self.queues:
            self.queues[key] = deque()
        self.queues[key].appendleft(value)
        
    async def brpop(self, key: str, timeout: int = 1):
        """Pop from queue"""
        if key in self.queues and self.queues[key]:
            return (key, self.queues[key].pop())
        return None
    
    async def llen(self, key: str) -> int:
        """Get queue length"""
        return len(self.queues.get(key, []))
    
    async def save_workflow(self, workflow: Workflow):
        """Override to ensure all tasks are saved too"""
        await super().save_workflow(workflow)
        # Also save tasks
        for task in workflow.tasks:
            await self.save_task(task)
    
    async def get_task_result(self, task_id: str) -> TaskResult:
        """Override to handle None properly"""
        return self.task_results.get(task_id)
    
    async def update_workflow_status(self, workflow_id: str, status: WorkflowStatus):
        """Add this method for compatibility"""
        if workflow_id in self.workflows:
            self.workflows[workflow_id].status = status


class SimpleProvider:
    """Simple provider for testing"""
    
    def __init__(self, protocol_name="test"):
        self.protocol_name = protocol_name
        self.executed = []
        
    async def execute(self, method: str, params: dict):
        """Execute task"""
        print(f"  [Provider] Executing {method}")
        self.executed.append({
            "method": method,
            "params": params,
            "timestamp": datetime.utcnow()
        })
        await asyncio.sleep(0.01)
        return {"status": "success", "method": method}


class SimpleAdapter:
    """Simple adapter that works with the backend"""
    
    def __init__(self, provider, backend, event_bus, protocol):
        self.provider = provider
        self.backend = backend
        self.event_bus = event_bus
        self.protocol = protocol
        self.running = False
        
    async def start(self):
        """Start processing"""
        self.running = True
        queue_key = f"provider:queue:{self.protocol}"
        
        while self.running:
            result = await self.backend.brpop(queue_key, timeout=1)
            if result:
                _, task_json = result
                await self._execute_task(task_json)
            else:
                await asyncio.sleep(0.01)
    
    async def _execute_task(self, task_json: str):
        """Execute task"""
        task_data = json.loads(task_json)
        task_id = task_data["task_id"]
        workflow_id = task_data["workflow_id"]
        
        # Update task status to EXECUTING
        if task_id in self.backend.tasks:
            self.backend.tasks[task_id].status = TaskStatus.EXECUTING
        
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
            # Execute
            result = await self.provider.execute(
                task_data["method"],
                task_data["params"]
            )
            
            # Save result
            task_result = TaskResult(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                result=result,
                completed_at=datetime.utcnow()
            )
            await self.backend.save_task_result(task_result)
            
            # Emit completed
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
            # Save failure
            task_result = TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                completed_at=datetime.utcnow()
            )
            await self.backend.save_task_result(task_result)
            
            # Emit failed
            await self.event_bus.emit(GleitzeitEvent(
                event_type=EventType.TASK_FAILED,
                data={
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "error": str(e),
                    "is_permanent": True,
                    "timestamp": datetime.utcnow().isoformat()
                }
            ))
    
    async def stop(self):
        """Stop adapter"""
        self.running = False


async def test_with_existing_workflow_manager():
    """Test using existing EventDrivenWorkflowManager with new scheduler"""
    print("\n=== Testing with EventDrivenWorkflowManager ===")
    
    # Setup
    backend = EnhancedInMemoryBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    # Create orchestrator (includes EventDrivenWorkflowManager)
    orchestrator = LightweightOrchestrator(
        persistence=backend,
        event_bus=event_bus
    )
    
    # Create provider and adapter
    provider = SimpleProvider(protocol_name="test")
    adapter = SimpleAdapter(provider, backend, event_bus, "test")
    
    # Start adapter
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
            id="test-workflow",
            name="Test Workflow",
            tasks=[task1, task2, task3]
        )
        
        print("Submitting workflow with 3 dependent tasks")
        
        # Submit workflow
        workflow_id = await orchestrator.submit_workflow(workflow)
        
        # Wait for completion
        max_wait = 3.0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            wf = await backend.get_workflow(workflow_id)
            if wf and wf.status == WorkflowStatus.COMPLETED:
                break
            await asyncio.sleep(0.1)
        
        # Check results
        final_workflow = await backend.get_workflow(workflow_id)
        status = await orchestrator.get_workflow_status(workflow_id)
        
        print(f"Workflow status: {final_workflow.status}")
        print(f"Completed tasks: {status['completed_tasks']}/{status['total_tasks']}")
        print(f"Execution order: {[e['method'] for e in provider.executed]}")
        
        # Verify
        if (final_workflow.status == WorkflowStatus.COMPLETED and
            len(provider.executed) == 3 and
            [e["method"] for e in provider.executed] == ["first_method", "second_method", "third_method"]):
            print("✅ Test PASSED - EventDrivenWorkflowManager tracked state correctly")
            return True
        else:
            print("❌ Test FAILED")
            return False
            
    finally:
        await adapter.stop()
        adapter_task.cancel()
        try:
            await adapter_task
        except asyncio.CancelledError:
            pass
        await backend.shutdown()


async def test_just_scheduler():
    """Test just the TaskSchedulerOnly component"""
    print("\n=== Testing TaskSchedulerOnly Component ===")
    
    # Setup
    backend = EnhancedInMemoryBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    # Create just the scheduler (not the full orchestrator)
    scheduler = TaskSchedulerOnly(
        persistence=backend,
        event_bus=event_bus
    )
    
    # Also need workflow manager for state tracking
    workflow_manager = EventDrivenWorkflowManager(backend, event_bus)
    
    # Create provider and adapter
    provider = SimpleProvider(protocol_name="test")
    adapter = SimpleAdapter(provider, backend, event_bus, "test")
    
    adapter_task = asyncio.create_task(adapter.start())
    
    try:
        # Create simple workflow
        task = Task(
            id="simple-task",
            name="Simple Task",
            protocol="test",
            method="test_method",
            params={"message": "Hello"}
        )
        
        workflow = Workflow(
            id="simple-workflow",
            name="Simple Workflow",
            tasks=[task]
        )
        
        print("Testing simple workflow with scheduler")
        
        # Save workflow
        await backend.save_workflow(workflow)
        
        # Emit WORKFLOW_SUBMITTED
        await event_bus.emit(GleitzeitEvent(
            event_type=EventType.WORKFLOW_SUBMITTED,
            data={
                "workflow_id": workflow.id,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        # Wait for completion
        max_wait = 2.0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            wf = await backend.get_workflow(workflow.id)
            if wf and wf.status == WorkflowStatus.COMPLETED:
                break
            await asyncio.sleep(0.1)
        
        # Check results
        final_workflow = await backend.get_workflow(workflow.id)
        
        print(f"Workflow status: {final_workflow.status}")
        print(f"Tasks executed: {len(provider.executed)}")
        
        if final_workflow.status == WorkflowStatus.COMPLETED and len(provider.executed) == 1:
            print("✅ Scheduler test PASSED")
            return True
        else:
            print("❌ Scheduler test FAILED")
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
    """Run tests"""
    print("=" * 60)
    print("TESTING LIGHTWEIGHT ORCHESTRATOR WITH EXISTING COMPONENTS")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(await test_just_scheduler())
    results.append(await test_with_existing_workflow_manager())
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✅ ALL TESTS PASSED ({passed}/{total})")
        print("\nThe lightweight approach works! It:")
        print("- Uses existing EventDrivenWorkflowManager for state tracking")
        print("- Adds only task scheduling and dependency resolution")
        print("- Works with existing persistence backends")
        print("- Maintains event bus compatibility")
    else:
        print(f"❌ SOME TESTS FAILED ({passed}/{total} passed)")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)