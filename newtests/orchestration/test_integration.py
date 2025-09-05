"""
End-to-end integration tests for orchestration MVP
"""

import pytest
import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any

from gleitzeit.core.models import Task, Workflow, WorkflowStatus, TaskStatus
from gleitzeit.orchestration.coordinator_mvp import WorkflowCoordinatorMVP
from gleitzeit.orchestration.provider_pull import ProviderPullAdapter, ProviderPoolManager
from gleitzeit.persistence.unified_redis import UnifiedRedisBackend
from gleitzeit.events.base import EventBus
from gleitzeit.core.events import GleitzeitEvent, EventType


class TestProvider:
    """Test provider that tracks execution"""
    
    def __init__(self, protocol_name="test", delay=0.01, fail_rate=0.0):
        self.protocol_name = protocol_name
        self.delay = delay
        self.fail_rate = fail_rate
        self.executed_tasks = []
        self.execution_order = []
        
    async def execute(self, method: str, params: dict):
        """Execute method with configurable delay and failure"""
        import random
        
        # Record execution
        self.executed_tasks.append({
            "method": method,
            "params": params,
            "timestamp": datetime.utcnow()
        })
        self.execution_order.append(params.get("task_id", method))
        
        # Simulate work
        await asyncio.sleep(self.delay)
        
        # Randomly fail based on fail_rate
        if random.random() < self.fail_rate:
            raise Exception(f"Simulated failure for {method}")
        
        # Return result
        return {
            "status": "success",
            "method": method,
            "result": params.get("expected_result", f"Result of {method}")
        }


@pytest.fixture
async def redis_backend():
    """Create test Redis backend"""
    backend = UnifiedRedisBackend()
    await backend.initialize()
    
    # Clear test data
    await backend.redis.flushdb()
    
    yield backend
    
    # Cleanup
    await backend.redis.flushdb()
    await backend.cleanup()


@pytest.fixture
def event_bus(redis_backend):
    """Create test event bus"""
    return EventBus(persistence=redis_backend)


@pytest.fixture
async def test_environment(redis_backend, event_bus):
    """Create complete test environment"""
    # Create coordinator
    coordinator = WorkflowCoordinatorMVP(
        persistence=redis_backend,
        event_bus=event_bus,
        node_id="test-node"
    )
    
    # Create providers
    python_provider = TestProvider(protocol_name="python", delay=0.01)
    shell_provider = TestProvider(protocol_name="shell", delay=0.02)
    
    # Create adapters
    python_adapter = ProviderPullAdapter(
        provider=python_provider,
        event_bus=event_bus,
        redis_client=redis_backend.redis,
        poll_interval=0.01
    )
    
    shell_adapter = ProviderPullAdapter(
        provider=shell_provider,
        event_bus=event_bus,
        redis_client=redis_backend.redis,
        poll_interval=0.01
    )
    
    # Start adapters
    python_task = asyncio.create_task(python_adapter.start())
    shell_task = asyncio.create_task(shell_adapter.start())
    
    yield {
        "coordinator": coordinator,
        "providers": {
            "python": python_provider,
            "shell": shell_provider
        },
        "adapters": {
            "python": python_adapter,
            "shell": shell_adapter
        },
        "tasks": [python_task, shell_task]
    }
    
    # Cleanup
    await python_adapter.stop()
    await shell_adapter.stop()
    
    for task in [python_task, shell_task]:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestEndToEndWorkflow:
    """Test complete workflow execution"""
    
    @pytest.mark.asyncio
    async def test_simple_workflow_execution(self, test_environment, event_bus):
        """Test execution of simple single-task workflow"""
        coordinator = test_environment["coordinator"]
        python_provider = test_environment["providers"]["python"]
        
        # Track events
        events = []
        
        async def track_event(event):
            events.append(event)
        
        event_bus.register(EventType.WORKFLOW_COMPLETED, track_event)
        
        # Create simple workflow
        task = Task(
            id="simple-task",
            name="Simple Task",
            protocol="python",
            method="simple_method",
            params={"task_id": "simple-task", "message": "Hello"}
        )
        
        workflow = Workflow(
            id="simple-workflow",
            name="Simple Workflow",
            tasks=[task]
        )
        
        # Submit workflow
        workflow_id = await coordinator.submit_workflow(workflow)
        
        # Wait for completion
        await self._wait_for_workflow_completion(coordinator, workflow_id, timeout=2.0)
        
        # Verify workflow completed
        state = coordinator.workflow_states[workflow_id]
        assert state.status == WorkflowStatus.COMPLETED
        assert len(state.completed_tasks) == 1
        
        # Verify provider executed task
        assert len(python_provider.executed_tasks) == 1
        assert python_provider.executed_tasks[0]["method"] == "simple_method"
        
        # Verify completion event
        completion_events = [e for e in events if e.event_type == EventType.WORKFLOW_COMPLETED]
        assert len(completion_events) == 1
    
    @pytest.mark.asyncio
    async def test_sequential_workflow_execution(self, test_environment):
        """Test execution of workflow with sequential dependencies"""
        coordinator = test_environment["coordinator"]
        python_provider = test_environment["providers"]["python"]
        
        # Create sequential workflow: t1 -> t2 -> t3
        task1 = Task(
            id="seq-1",
            name="First",
            protocol="python",
            method="method_1",
            params={"task_id": "seq-1"}
        )
        
        task2 = Task(
            id="seq-2",
            name="Second",
            protocol="python",
            method="method_2",
            params={"task_id": "seq-2"},
            dependencies=["seq-1"]
        )
        
        task3 = Task(
            id="seq-3",
            name="Third",
            protocol="python",
            method="method_3",
            params={"task_id": "seq-3"},
            dependencies=["seq-2"]
        )
        
        workflow = Workflow(
            id="sequential-workflow",
            name="Sequential Workflow",
            tasks=[task1, task2, task3]
        )
        
        # Submit workflow
        workflow_id = await coordinator.submit_workflow(workflow)
        
        # Wait for completion
        await self._wait_for_workflow_completion(coordinator, workflow_id, timeout=3.0)
        
        # Verify completion
        state = coordinator.workflow_states[workflow_id]
        assert state.status == WorkflowStatus.COMPLETED
        assert len(state.completed_tasks) == 3
        
        # Verify execution order
        assert python_provider.execution_order == ["seq-1", "seq-2", "seq-3"]
    
    @pytest.mark.asyncio
    async def test_parallel_workflow_execution(self, test_environment):
        """Test execution of workflow with parallel tasks"""
        coordinator = test_environment["coordinator"]
        python_provider = test_environment["providers"]["python"]
        
        # Create parallel workflow
        task1 = Task(
            id="par-1",
            name="Parallel 1",
            protocol="python",
            method="parallel_1",
            params={"task_id": "par-1"}
        )
        
        task2 = Task(
            id="par-2",
            name="Parallel 2",
            protocol="python",
            method="parallel_2",
            params={"task_id": "par-2"}
        )
        
        task3 = Task(
            id="par-3",
            name="Parallel 3",
            protocol="python",
            method="parallel_3",
            params={"task_id": "par-3"}
        )
        
        workflow = Workflow(
            id="parallel-workflow",
            name="Parallel Workflow",
            tasks=[task1, task2, task3]
        )
        
        # Submit workflow
        workflow_id = await coordinator.submit_workflow(workflow)
        
        # Wait for completion
        await self._wait_for_workflow_completion(coordinator, workflow_id, timeout=2.0)
        
        # Verify completion
        state = coordinator.workflow_states[workflow_id]
        assert state.status == WorkflowStatus.COMPLETED
        assert len(state.completed_tasks) == 3
        
        # All tasks should have been executed
        assert len(python_provider.executed_tasks) == 3
        executed_ids = {t["params"]["task_id"] for t in python_provider.executed_tasks}
        assert executed_ids == {"par-1", "par-2", "par-3"}
    
    @pytest.mark.asyncio
    async def test_diamond_dependency_workflow(self, test_environment):
        """Test diamond dependency pattern execution"""
        coordinator = test_environment["coordinator"]
        python_provider = test_environment["providers"]["python"]
        
        # Create diamond pattern: t1 -> (t2, t3) -> t4
        task1 = Task(
            id="diamond-1",
            name="Start",
            protocol="python",
            method="start",
            params={"task_id": "diamond-1"}
        )
        
        task2 = Task(
            id="diamond-2",
            name="Branch A",
            protocol="python",
            method="branch_a",
            params={"task_id": "diamond-2"},
            dependencies=["diamond-1"]
        )
        
        task3 = Task(
            id="diamond-3",
            name="Branch B",
            protocol="python",
            method="branch_b",
            params={"task_id": "diamond-3"},
            dependencies=["diamond-1"]
        )
        
        task4 = Task(
            id="diamond-4",
            name="Join",
            protocol="python",
            method="join",
            params={"task_id": "diamond-4"},
            dependencies=["diamond-2", "diamond-3"]
        )
        
        workflow = Workflow(
            id="diamond-workflow",
            name="Diamond Workflow",
            tasks=[task1, task2, task3, task4]
        )
        
        # Submit workflow
        workflow_id = await coordinator.submit_workflow(workflow)
        
        # Wait for completion
        await self._wait_for_workflow_completion(coordinator, workflow_id, timeout=3.0)
        
        # Verify completion
        state = coordinator.workflow_states[workflow_id]
        assert state.status == WorkflowStatus.COMPLETED
        assert len(state.completed_tasks) == 4
        
        # Verify execution order constraints
        execution_order = python_provider.execution_order
        
        # t1 must be first
        assert execution_order[0] == "diamond-1"
        
        # t4 must be last
        assert execution_order[-1] == "diamond-4"
        
        # t2 and t3 must be between t1 and t4
        t1_idx = execution_order.index("diamond-1")
        t2_idx = execution_order.index("diamond-2")
        t3_idx = execution_order.index("diamond-3")
        t4_idx = execution_order.index("diamond-4")
        
        assert t1_idx < t2_idx < t4_idx
        assert t1_idx < t3_idx < t4_idx
    
    @pytest.mark.asyncio
    async def test_mixed_protocol_workflow(self, test_environment):
        """Test workflow with tasks using different protocols"""
        coordinator = test_environment["coordinator"]
        python_provider = test_environment["providers"]["python"]
        shell_provider = test_environment["providers"]["shell"]
        
        # Create workflow with mixed protocols
        task1 = Task(
            id="mixed-1",
            name="Python Task",
            protocol="python",
            method="python_method",
            params={"task_id": "mixed-1"}
        )
        
        task2 = Task(
            id="mixed-2",
            name="Shell Task",
            protocol="shell",
            method="shell_command",
            params={"task_id": "mixed-2"},
            dependencies=["mixed-1"]
        )
        
        task3 = Task(
            id="mixed-3",
            name="Another Python",
            protocol="python",
            method="python_method_2",
            params={"task_id": "mixed-3"},
            dependencies=["mixed-2"]
        )
        
        workflow = Workflow(
            id="mixed-workflow",
            name="Mixed Protocol Workflow",
            tasks=[task1, task2, task3]
        )
        
        # Submit workflow
        workflow_id = await coordinator.submit_workflow(workflow)
        
        # Wait for completion
        await self._wait_for_workflow_completion(coordinator, workflow_id, timeout=3.0)
        
        # Verify completion
        state = coordinator.workflow_states[workflow_id]
        assert state.status == WorkflowStatus.COMPLETED
        assert len(state.completed_tasks) == 3
        
        # Verify each provider executed its tasks
        assert len(python_provider.executed_tasks) == 2
        assert len(shell_provider.executed_tasks) == 1
        
        python_methods = {t["method"] for t in python_provider.executed_tasks}
        assert python_methods == {"python_method", "python_method_2"}
        
        assert shell_provider.executed_tasks[0]["method"] == "shell_command"
    
    @pytest.mark.asyncio
    async def test_workflow_with_failure(self, redis_backend, event_bus):
        """Test workflow handling with task failure"""
        # Create coordinator
        coordinator = WorkflowCoordinatorMVP(
            persistence=redis_backend,
            event_bus=event_bus
        )
        
        # Create provider that fails
        failing_provider = TestProvider(protocol_name="failing", fail_rate=1.0)
        
        adapter = ProviderPullAdapter(
            provider=failing_provider,
            event_bus=event_bus,
            redis_client=redis_backend.redis,
            poll_interval=0.01
        )
        
        # Start adapter
        adapter_task = asyncio.create_task(adapter.start())
        
        try:
            # Create workflow
            task = Task(
                id="fail-task",
                name="Failing Task",
                protocol="failing",
                method="will_fail",
                params={"task_id": "fail-task"}
            )
            
            workflow = Workflow(
                id="failing-workflow",
                name="Failing Workflow",
                tasks=[task]
            )
            
            # Submit workflow
            workflow_id = await coordinator.submit_workflow(workflow)
            
            # Wait for failure
            await self._wait_for_workflow_completion(
                coordinator, 
                workflow_id, 
                timeout=2.0,
                expected_status=WorkflowStatus.FAILED
            )
            
            # Verify workflow failed
            state = coordinator.workflow_states[workflow_id]
            assert state.status == WorkflowStatus.FAILED
            assert len(state.failed_tasks) == 1
            assert "fail-task" in state.failed_tasks
            
        finally:
            # Cleanup
            await adapter.stop()
            adapter_task.cancel()
            try:
                await adapter_task
            except asyncio.CancelledError:
                pass
    
    async def _wait_for_workflow_completion(
        self, 
        coordinator: WorkflowCoordinatorMVP,
        workflow_id: str,
        timeout: float = 5.0,
        expected_status: WorkflowStatus = WorkflowStatus.COMPLETED
    ):
        """Helper to wait for workflow completion"""
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            state = coordinator.workflow_states.get(workflow_id)
            if state and state.status == expected_status:
                return
            await asyncio.sleep(0.05)
        
        # Timeout - print debug info
        if workflow_id in coordinator.workflow_states:
            state = coordinator.workflow_states[workflow_id]
            pytest.fail(
                f"Workflow {workflow_id} did not reach {expected_status} within {timeout}s. "
                f"Current status: {state.status}, "
                f"Completed tasks: {state.completed_tasks}, "
                f"Failed tasks: {state.failed_tasks}"
            )
        else:
            pytest.fail(f"Workflow {workflow_id} not found in coordinator")


class TestScalability:
    """Test scalability aspects of the MVP"""
    
    @pytest.mark.asyncio
    async def test_multiple_concurrent_workflows(self, test_environment):
        """Test running multiple workflows concurrently"""
        coordinator = test_environment["coordinator"]
        python_provider = test_environment["providers"]["python"]
        
        # Create multiple workflows
        workflows = []
        for i in range(5):
            task = Task(
                id=f"concurrent-task-{i}",
                name=f"Task {i}",
                protocol="python",
                method=f"method_{i}",
                params={"task_id": f"concurrent-task-{i}", "workflow": i}
            )
            
            workflow = Workflow(
                id=f"concurrent-workflow-{i}",
                name=f"Workflow {i}",
                tasks=[task]
            )
            workflows.append(workflow)
        
        # Submit all workflows
        workflow_ids = []
        for workflow in workflows:
            wf_id = await coordinator.submit_workflow(workflow)
            workflow_ids.append(wf_id)
        
        # Wait for all to complete
        for wf_id in workflow_ids:
            await self._wait_for_completion(coordinator, wf_id, timeout=3.0)
        
        # Verify all completed
        for wf_id in workflow_ids:
            state = coordinator.workflow_states[wf_id]
            assert state.status == WorkflowStatus.COMPLETED
        
        # Verify all tasks executed
        assert len(python_provider.executed_tasks) == 5
    
    @pytest.mark.asyncio
    async def test_provider_pool_load_distribution(self, redis_backend, event_bus):
        """Test load distribution across multiple provider instances"""
        coordinator = WorkflowCoordinatorMVP(
            persistence=redis_backend,
            event_bus=event_bus
        )
        
        # Create pool manager
        pool_manager = ProviderPoolManager(event_bus, redis_backend.redis)
        
        # Add multiple instances of same provider
        provider = TestProvider(protocol_name="pooled", delay=0.01)
        await pool_manager.add_provider(provider, instances=3)
        
        # Start pool
        pool_task = asyncio.create_task(pool_manager.start())
        
        try:
            # Create workflow with many tasks
            tasks = []
            for i in range(10):
                task = Task(
                    id=f"pool-task-{i}",
                    name=f"Task {i}",
                    protocol="pooled",
                    method=f"method_{i}",
                    params={"task_id": f"pool-task-{i}"}
                )
                tasks.append(task)
            
            workflow = Workflow(
                id="pool-workflow",
                name="Pool Test Workflow",
                tasks=tasks
            )
            
            # Submit workflow
            workflow_id = await coordinator.submit_workflow(workflow)
            
            # Wait for completion
            await self._wait_for_completion(coordinator, workflow_id, timeout=5.0)
            
            # Verify all tasks completed
            state = coordinator.workflow_states[workflow_id]
            assert state.status == WorkflowStatus.COMPLETED
            assert len(state.completed_tasks) == 10
            
            # Get pool stats
            stats = pool_manager.get_stats()
            assert "pooled" in stats
            
            # Check that work was distributed (all adapters processed something)
            total_processed = sum(
                adapter.get_stats()["tasks_processed"] 
                for adapter in pool_manager.adapters["pooled"]
            )
            assert total_processed == 10
            
        finally:
            # Cleanup
            await pool_manager.stop()
            pool_task.cancel()
            try:
                await pool_task
            except asyncio.CancelledError:
                pass
    
    async def _wait_for_completion(
        self, 
        coordinator: WorkflowCoordinatorMVP,
        workflow_id: str,
        timeout: float = 5.0
    ):
        """Helper to wait for workflow completion"""
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            state = coordinator.workflow_states.get(workflow_id)
            if state and state.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
                return
            await asyncio.sleep(0.05)
        
        pytest.fail(f"Workflow {workflow_id} did not complete within {timeout}s")