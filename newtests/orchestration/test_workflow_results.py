"""
Test workflow execution with result retrieval
"""

import asyncio
import json
from datetime import datetime

from gleitzeit.core.models import Task, Workflow, WorkflowStatus, TaskStatus, TaskResult
from gleitzeit.orchestration.task_scheduler_only import LightweightOrchestrator
from gleitzeit.persistence.base import InMemoryBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType


class ResultTrackingBackend(InMemoryBackend):
    """Backend that tracks results"""
    
    def __init__(self):
        super().__init__()
        self.redis = self
        self.queues = {}
        
    async def lpush(self, key: str, value: str):
        if key not in self.queues:
            self.queues[key] = []
        self.queues[key].insert(0, value)
        
    async def brpop(self, key: str, timeout: int = 1):
        if key in self.queues and self.queues[key]:
            return (key, self.queues[key].pop())
        return None
    
    async def save_workflow(self, workflow: Workflow):
        await super().save_workflow(workflow)
        for task in workflow.tasks:
            await self.save_task(task)


class ResultProvider:
    """Provider that returns meaningful results"""
    
    def __init__(self):
        self.execution_count = 0
        
    async def execute(self, method: str, params: dict):
        """Execute and return result with data"""
        self.execution_count += 1
        
        # Simulate some computation
        await asyncio.sleep(0.01)
        
        # Return meaningful result
        result = {
            "status": "success",
            "method": method,
            "execution_id": self.execution_count,
            "input_params": params,
            "computed_value": params.get("value", 0) * 2,  # Double the input
            "timestamp": datetime.utcnow().isoformat()
        }
        
        print(f"  Provider executed {method}: computed_value={result['computed_value']}")
        return result


class ResultAdapter:
    """Adapter that properly handles results"""
    
    def __init__(self, provider, backend, event_bus):
        self.provider = provider
        self.backend = backend
        self.event_bus = event_bus
        self.running = False
        
    async def start(self):
        self.running = True
        
        while self.running:
            result = await self.backend.brpop("provider:queue:test", timeout=1)
            if result:
                _, task_json = result
                await self._execute_task(task_json)
            else:
                await asyncio.sleep(0.01)
    
    async def _execute_task(self, task_json: str):
        task_data = json.loads(task_json)
        task_id = task_data["task_id"]
        workflow_id = task_data["workflow_id"]
        
        # Update status
        task = await self.backend.get_task(task_id)
        if task:
            task.status = TaskStatus.EXECUTING
            await self.backend.save_task(task)
        
        # Emit started
        await self.event_bus.emit(GleitzeitEvent(
            event_type=EventType.TASK_STARTED,
            data={
                "task_id": task_id,
                "workflow_id": workflow_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        try:
            # Execute and get result
            result = await self.provider.execute(
                task_data["method"],
                task_data["params"]
            )
            
            # Save task result
            task_result = TaskResult(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                result=result,
                completed_at=datetime.utcnow()
            )
            await self.backend.save_task_result(task_result)
            
            # Emit completed with result
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
            task_result = TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                completed_at=datetime.utcnow()
            )
            await self.backend.save_task_result(task_result)
            
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
        self.running = False


async def test_simple_workflow_results():
    """Test simple workflow with result retrieval"""
    print("\n=== Test Simple Workflow Results ===")
    
    # Setup
    backend = ResultTrackingBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    orchestrator = LightweightOrchestrator(
        persistence=backend,
        event_bus=event_bus
    )
    
    provider = ResultProvider()
    adapter = ResultAdapter(provider, backend, event_bus)
    
    adapter_task = asyncio.create_task(adapter.start())
    
    try:
        # Create simple workflow
        task1 = Task(
            id="task-1",
            name="Calculate",
            protocol="test",
            method="calculate",
            params={"value": 10, "operation": "double"}
        )
        
        workflow = Workflow(
            id="workflow-1",
            name="Calculation Workflow",
            tasks=[task1]
        )
        
        print("Submitting workflow...")
        workflow_id = await orchestrator.submit_workflow(workflow)
        
        # Wait for completion
        max_wait = 2.0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            wf = await backend.get_workflow(workflow_id)
            if wf and wf.status == WorkflowStatus.COMPLETED:
                break
            await asyncio.sleep(0.1)
        
        # Get results
        workflow = await backend.get_workflow(workflow_id)
        task_result = await backend.get_task_result("task-1")
        
        print(f"\nWorkflow status: {workflow.status}")
        print(f"Task result retrieved: {'✅' if task_result else '❌'}")
        
        if task_result:
            print(f"Result status: {task_result.status}")
            print(f"Result data: {json.dumps(task_result.result, indent=2)}")
            
            # Verify result
            expected_value = 20  # 10 * 2
            actual_value = task_result.result.get("computed_value")
            print(f"\nExpected computed value: {expected_value}")
            print(f"Actual computed value: {actual_value}")
            print(f"Result correct: {'✅' if actual_value == expected_value else '❌'}")
            
            return workflow.status == WorkflowStatus.COMPLETED and actual_value == expected_value
        
        return False
        
    finally:
        await adapter.stop()
        adapter_task.cancel()
        try:
            await adapter_task
        except asyncio.CancelledError:
            pass
        await backend.shutdown()


async def test_workflow_with_dependencies_and_results():
    """Test workflow with dependencies passing results"""
    print("\n=== Test Workflow with Dependencies and Result Passing ===")
    
    backend = ResultTrackingBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    orchestrator = LightweightOrchestrator(
        persistence=backend,
        event_bus=event_bus
    )
    
    provider = ResultProvider()
    adapter = ResultAdapter(provider, backend, event_bus)
    
    adapter_task = asyncio.create_task(adapter.start())
    
    try:
        # Create workflow with dependent tasks
        task1 = Task(
            id="task-1",
            name="First Calculation",
            protocol="test",
            method="step1",
            params={"value": 5}
        )
        
        task2 = Task(
            id="task-2",
            name="Second Calculation",
            protocol="test",
            method="step2",
            params={"value": 10},
            dependencies=["task-1"]
        )
        
        task3 = Task(
            id="task-3",
            name="Final Calculation",
            protocol="test",
            method="step3",
            params={"value": 15},
            dependencies=["task-2"]
        )
        
        workflow = Workflow(
            id="workflow-2",
            name="Multi-step Calculation",
            tasks=[task1, task2, task3]
        )
        
        print("Submitting workflow with 3 dependent tasks...")
        workflow_id = await orchestrator.submit_workflow(workflow)
        
        # Wait for completion
        max_wait = 3.0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            wf = await backend.get_workflow(workflow_id)
            if wf and wf.status == WorkflowStatus.COMPLETED:
                break
            await asyncio.sleep(0.1)
        
        # Get all results
        workflow = await backend.get_workflow(workflow_id)
        results = {}
        for task in workflow.tasks:
            result = await backend.get_task_result(task.id)
            results[task.id] = result
        
        print(f"\nWorkflow status: {workflow.status}")
        print(f"Tasks completed: {len([r for r in results.values() if r and r.status == TaskStatus.COMPLETED])}/3")
        
        # Check results
        all_successful = True
        for task_id, result in results.items():
            if result:
                print(f"\n{task_id}:")
                print(f"  Status: {result.status}")
                print(f"  Computed value: {result.result.get('computed_value')}")
            else:
                print(f"\n{task_id}: No result found ❌")
                all_successful = False
        
        # Verify execution order
        if all(results.values()):
            exec_ids = [r.result["execution_id"] for r in results.values()]
            print(f"\nExecution order (by ID): {exec_ids}")
            order_correct = exec_ids == sorted(exec_ids)
            print(f"Dependency order maintained: {'✅' if order_correct else '❌'}")
            
            return workflow.status == WorkflowStatus.COMPLETED and all_successful and order_correct
        
        return False
        
    finally:
        await adapter.stop()
        adapter_task.cancel()
        try:
            await adapter_task
        except asyncio.CancelledError:
            pass
        await backend.shutdown()


async def test_workflow_aggregated_results():
    """Test getting aggregated workflow results"""
    print("\n=== Test Aggregated Workflow Results ===")
    
    backend = ResultTrackingBackend()
    await backend.initialize()
    event_bus = EventBus()
    
    orchestrator = LightweightOrchestrator(
        persistence=backend,
        event_bus=event_bus
    )
    
    provider = ResultProvider()
    adapter = ResultAdapter(provider, backend, event_bus)
    
    adapter_task = asyncio.create_task(adapter.start())
    
    try:
        # Create workflow with multiple tasks
        tasks = []
        for i in range(5):
            task = Task(
                id=f"task-{i}",
                name=f"Task {i}",
                protocol="test",
                method=f"process_{i}",
                params={"value": i * 10}
            )
            tasks.append(task)
        
        workflow = Workflow(
            id="workflow-3",
            name="Aggregation Workflow",
            tasks=tasks
        )
        
        print(f"Submitting workflow with {len(tasks)} tasks...")
        workflow_id = await orchestrator.submit_workflow(workflow)
        
        # Wait for completion
        max_wait = 3.0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < max_wait:
            wf = await backend.get_workflow(workflow_id)
            if wf and wf.status == WorkflowStatus.COMPLETED:
                break
            await asyncio.sleep(0.1)
        
        # Get workflow and aggregate results
        workflow = await backend.get_workflow(workflow_id)
        
        # Collect all results
        workflow_results = {
            "workflow_id": workflow_id,
            "status": workflow.status,
            "task_results": []
        }
        
        total_computed = 0
        for task in workflow.tasks:
            result = await backend.get_task_result(task.id)
            if result and result.status == TaskStatus.COMPLETED:
                workflow_results["task_results"].append({
                    "task_id": task.id,
                    "computed_value": result.result.get("computed_value"),
                    "status": "completed"
                })
                total_computed += result.result.get("computed_value", 0)
        
        workflow_results["total_computed"] = total_computed
        workflow_results["average_computed"] = total_computed / len(tasks) if tasks else 0
        
        print(f"\n=== Aggregated Workflow Results ===")
        print(f"Workflow ID: {workflow_results['workflow_id']}")
        print(f"Status: {workflow_results['status']}")
        print(f"Tasks completed: {len(workflow_results['task_results'])}/{len(tasks)}")
        print(f"Total computed value: {workflow_results['total_computed']}")
        print(f"Average computed value: {workflow_results['average_computed']:.1f}")
        
        # Verify
        expected_total = sum(i * 10 * 2 for i in range(5))  # Each value doubled
        print(f"\nExpected total: {expected_total}")
        print(f"Actual total: {total_computed}")
        print(f"Results correct: {'✅' if total_computed == expected_total else '❌'}")
        
        return (
            workflow.status == WorkflowStatus.COMPLETED and
            len(workflow_results["task_results"]) == len(tasks) and
            total_computed == expected_total
        )
        
    finally:
        await adapter.stop()
        adapter_task.cancel()
        try:
            await adapter_task
        except asyncio.CancelledError:
            pass
        await backend.shutdown()


async def main():
    """Run all result tests"""
    print("=" * 60)
    print("WORKFLOW RESULT RETRIEVAL TESTS")
    print("=" * 60)
    
    results = []
    
    # Test 1: Simple workflow
    result1 = await test_simple_workflow_results()
    results.append(("Simple Workflow Results", result1))
    
    # Test 2: Dependencies with results
    result2 = await test_workflow_with_dependencies_and_results()
    results.append(("Dependencies with Results", result2))
    
    # Test 3: Aggregated results
    result3 = await test_workflow_aggregated_results()
    results.append(("Aggregated Results", result3))
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {test_name}: {status}")
    
    all_passed = all(r[1] for r in results)
    
    if all_passed:
        print("\n✅ ALL RESULT TESTS PASSED")
        print("Workflows correctly:")
        print("  • Execute tasks and store results")
        print("  • Return meaningful result data")
        print("  • Maintain result integrity through dependencies")
        print("  • Support result aggregation")
    else:
        print("\n❌ SOME RESULT TESTS FAILED")
    
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)