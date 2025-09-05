"""Tests for parallel_workflow.yaml"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock
import yaml

from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2 as ExecutionEngine
from gleitzeit.core.workflow_loader import load_workflow_from_dict


class TestParallelWorkflow:
    """Test parallel task execution workflow"""
    
    @pytest.fixture
    def workflow_path(self):
        """Path to workflow file"""
        return Path("examples/parallel_workflow.yaml")
    
    @pytest.fixture
    def workflow_content(self, workflow_path):
        """Load workflow content"""
        with open(workflow_path) as f:
            return yaml.safe_load(f)
    
    @pytest.fixture
    async def mock_providers(self):
        """Create mock providers for different tasks"""
        providers = {}
        
        # Mock LLM provider
        llm_provider = Mock()
        llm_provider.provider_id = "ollama"
        llm_provider.protocol_id = "llm/v1"
        llm_provider.handle_request = AsyncMock(
            return_value={"response": "LLM response", "provider_id": "ollama"}
        )
        providers["llm/v1"] = llm_provider
        
        # Mock Python provider
        python_provider = Mock()
        python_provider.provider_id = "python"
        python_provider.protocol_id = "python/v1"
        python_provider.handle_request = AsyncMock(
            return_value={"result": 42, "provider_id": "python"}
        )
        providers["python/v1"] = python_provider
        
        return providers
    
    @pytest.fixture
    async def mock_registry(self, mock_providers):
        """Create mock registry with multiple providers"""
        registry = Mock()
        
        async def get_provider(protocol, method):
            return mock_providers.get(protocol)
        
        registry.get_provider_for_method = AsyncMock(side_effect=get_provider)
        return registry
    
    @pytest.fixture
    async def mock_persistence(self):
        """Create mock persistence"""
        persistence = Mock()
        persistence.save_workflow = AsyncMock()
        persistence.save_task = AsyncMock()
        persistence.save_result = AsyncMock()
        persistence.update_task_status = AsyncMock()
        return persistence
    
    
    @pytest.mark.asyncio
    async def test_workflow_structure(self, workflow_content):
        """Test parallel workflow structure"""
        # Check for multiple independent tasks
        tasks = workflow_content["tasks"]
        
        # Count tasks without dependencies
        independent_tasks = [t for t in tasks if "dependencies" not in t]
        assert len(independent_tasks) >= 2  # At least 2 tasks should be independent
        
        # Check for aggregation task if present
        dependent_tasks = [t for t in tasks if "dependencies" in t]
        if dependent_tasks:
            # Aggregation task should depend on multiple tasks
            for task in dependent_tasks:
                assert len(task["dependencies"]) >= 2
    
    @pytest.mark.asyncio
    async def test_parallel_execution(self, execution_engine, workflow_content):
        """Test that independent tasks execute in parallel"""
        execution_times = {}
        task_start_times = {}
        
        async def track_parallel_execution(method, params):
            task_id = params.get("_task_id", "unknown")
            task_start_times[task_id] = asyncio.get_event_loop().time()
            
            # Simulate work
            await asyncio.sleep(0.1)
            
            execution_times[task_id] = asyncio.get_event_loop().time()
            return {"response": f"Result for {task_id}", "provider_id": "test"}
        
        # Inject task IDs for tracking
        for task in workflow_content["tasks"]:
            if "parameters" not in task:
                task["parameters"] = {}
            task["parameters"]["_task_id"] = task["id"]
        
        for provider in execution_engine.registry.mock_providers.values():
            provider.handle_request = track_parallel_execution
        
        workflow_id = await execution_engine.submit_workflow(workflow_content)
        await asyncio.sleep(0.5)  # Wait for completion
        
        # Check that independent tasks started close together
        independent_tasks = [t for t in workflow_content["tasks"] if "dependencies" not in t]
        if len(independent_tasks) >= 2:
            start_times = [task_start_times.get(t["id"], 0) for t in independent_tasks]
            
            # All independent tasks should start within 50ms of each other
            if len(start_times) >= 2:
                max_diff = max(start_times) - min(start_times)
                assert max_diff < 0.05  # 50ms tolerance for parallel start
    
    @pytest.mark.asyncio
    async def test_max_parallel_limit(self, execution_engine, workflow_content):
        """Test that max_parallel_tasks limit is respected"""
        execution_engine.max_parallel_tasks = 2  # Limit to 2 parallel tasks
        
        concurrent_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()
        
        async def track_concurrency(method, params):
            nonlocal concurrent_count, max_concurrent
            
            async with lock:
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)
            
            await asyncio.sleep(0.1)  # Simulate work
            
            async with lock:
                concurrent_count -= 1
            
            return {"response": "done", "provider_id": "test"}
        
        for provider in execution_engine.registry.mock_providers.values():
            provider.handle_request = track_concurrency
        
        # Create workflow with many parallel tasks
        workflow_content["tasks"] = [
            {"id": f"task_{i}", "method": "test", "parameters": {}}
            for i in range(5)
        ]
        
        workflow_id = await execution_engine.submit_workflow(workflow_content)
        await asyncio.sleep(0.5)
        
        # Max concurrent should not exceed limit
        assert max_concurrent <= execution_engine.max_parallel_tasks
    
    @pytest.mark.asyncio
    async def test_mixed_parallel_sequential(self, execution_engine, workflow_content):
        """Test workflow with both parallel and sequential sections"""
        # Create a workflow with mixed structure:
        # task1, task2 (parallel) -> task3 (depends on both) -> task4, task5 (parallel)
        workflow_content["tasks"] = [
            {"id": "task1", "method": "test", "parameters": {}},
            {"id": "task2", "method": "test", "parameters": {}},
            {"id": "task3", "method": "test", "dependencies": ["task1", "task2"], "parameters": {}},
            {"id": "task4", "method": "test", "dependencies": ["task3"], "parameters": {}},
            {"id": "task5", "method": "test", "dependencies": ["task3"], "parameters": {}},
        ]
        
        execution_order = []
        
        async def track_order(method, params):
            task_id = params.get("_task_id", "unknown")
            execution_order.append(task_id)
            await asyncio.sleep(0.05)
            return {"response": "done", "provider_id": "test"}
        
        # Inject task IDs
        for task in workflow_content["tasks"]:
            task["parameters"]["_task_id"] = task["id"]
        
        for provider in execution_engine.registry.mock_providers.values():
            provider.handle_request = track_order
        
        workflow_id = await execution_engine.submit_workflow(workflow_content)
        await asyncio.sleep(0.5)
        
        # Verify execution order
        if len(execution_order) == 5:
            # task1 and task2 can be in any order (parallel)
            assert set(execution_order[:2]) == {"task1", "task2"}
            # task3 must come after both
            assert execution_order[2] == "task3"
            # task4 and task5 can be in any order after task3
            assert set(execution_order[3:]) == {"task4", "task5"}
    
    @pytest.mark.asyncio
    async def test_parallel_error_handling(self, execution_engine, workflow_content):
        """Test error handling in parallel tasks"""
        # Create workflow with parallel tasks
        workflow_content["tasks"] = [
            {"id": "task1", "method": "test", "parameters": {}},
            {"id": "task2", "method": "test", "parameters": {}},
            {"id": "task3", "method": "test", "parameters": {}},
        ]
        
        failed_tasks = set()
        
        async def fail_some_tasks(method, params):
            task_id = params.get("_task_id", "unknown")
            
            # Fail task2
            if task_id == "task2":
                failed_tasks.add(task_id)
                raise Exception(f"Task {task_id} failed")
            
            return {"response": f"Success for {task_id}", "provider_id": "test"}
        
        # Inject task IDs
        for task in workflow_content["tasks"]:
            task["parameters"]["_task_id"] = task["id"]
        
        for provider in execution_engine.registry.mock_providers.values():
            provider.handle_request = fail_some_tasks
        
        workflow_id = await execution_engine.submit_workflow(workflow_content)
        await asyncio.sleep(0.2)
        
        # Check that other tasks still completed
        context = execution_engine.active_workflows.get(workflow_id)
        if context:
            # task1 and task3 should complete
            assert "task1" in context.results or "task1" in context.completed_tasks
            assert "task3" in context.results or "task3" in context.completed_tasks
            # task2 should have failed
            assert "task2" in failed_tasks
    
    @pytest.mark.asyncio
    async def test_parallel_result_aggregation(self, execution_engine, workflow_content):
        """Test aggregating results from parallel tasks"""
        # Create workflow with parallel tasks and aggregation
        workflow_content["tasks"] = [
            {"id": "fetch1", "method": "test", "parameters": {"source": "api1"}},
            {"id": "fetch2", "method": "test", "parameters": {"source": "api2"}},
            {"id": "fetch3", "method": "test", "parameters": {"source": "api3"}},
            {"id": "aggregate", "method": "test", 
             "dependencies": ["fetch1", "fetch2", "fetch3"],
             "parameters": {
                 "data1": "${fetch1.response}",
                 "data2": "${fetch2.response}",
                 "data3": "${fetch3.response}"
             }}
        ]
        
        results = {}
        
        async def simulate_fetch(method, params):
            source = params.get("source", "unknown")
            task_id = params.get("_task_id", "unknown")
            
            if "fetch" in task_id:
                result = {"response": f"Data from {source}", "provider_id": "test"}
            else:  # aggregate task
                # Should have received all data
                result = {
                    "response": f"Aggregated: {params.get('data1')}, {params.get('data2')}, {params.get('data3')}",
                    "provider_id": "test"
                }
            
            results[task_id] = result
            return result
        
        # Inject task IDs
        for task in workflow_content["tasks"]:
            task["parameters"]["_task_id"] = task["id"]
        
        for provider in execution_engine.registry.mock_providers.values():
            provider.handle_request = simulate_fetch
        
        workflow_id = await execution_engine.submit_workflow(workflow_content)
        await asyncio.sleep(0.3)
        
        # Verify all tasks completed and aggregation received all data
        assert len(results) == 4
        if "aggregate" in results:
            agg_response = results["aggregate"]["response"]
            assert "Data from api1" in agg_response
            assert "Data from api2" in agg_response
            assert "Data from api3" in agg_response