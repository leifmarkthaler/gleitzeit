"""
Tests for UnifiedDependencyManager service
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from datetime import datetime, timedelta

from gleitzeit.core.dependency_manager import (
    UnifiedDependencyManager, 
    CircularDependencyError,
    DependencyNode
)
from gleitzeit.core.models import Task, Workflow, TaskStatus, WorkflowStatus


class TestUnifiedDependencyManager:
    """Test suite for UnifiedDependencyManager"""
    
    @pytest.fixture
    def mock_persistence(self):
        """Create mock persistence backend"""
        persistence = Mock()
        persistence.get_workflow = AsyncMock()
        persistence.get_task_result = AsyncMock()
        return persistence
        
    @pytest.fixture
    def manager(self, mock_persistence):
        """Create UnifiedDependencyManager instance"""
        return UnifiedDependencyManager(mock_persistence)
        
    @pytest.fixture
    def simple_workflow(self):
        """Create simple workflow for testing"""
        tasks = [
            Task(id="task-1", name="setup", protocol="python", method="setup", params={}),
            Task(id="task-2", name="process", protocol="python", method="process", 
                 params={}, dependencies=["task-1"]),
            Task(id="task-3", name="cleanup", protocol="python", method="cleanup",
                 params={}, dependencies=["task-2"])
        ]
        return Workflow(id="wf-1", name="test-workflow", tasks=tasks)
        
    @pytest.fixture
    def parallel_workflow(self):
        """Create workflow with parallel tasks"""
        tasks = [
            Task(id="task-1", name="setup", protocol="python", method="setup", params={}),
            Task(id="task-2a", name="process-a", protocol="python", method="process",
                 params={}, dependencies=["task-1"]),
            Task(id="task-2b", name="process-b", protocol="python", method="process",
                 params={}, dependencies=["task-1"]),
            Task(id="task-3", name="merge", protocol="python", method="merge",
                 params={}, dependencies=["task-2a", "task-2b"])
        ]
        return Workflow(id="wf-2", name="parallel-workflow", tasks=tasks)
        
    @pytest.fixture
    def circular_workflow(self):
        """Create workflow with circular dependencies"""
        tasks = [
            Task(id="task-1", name="first", protocol="python", method="run",
                 params={}, dependencies=["task-3"]),
            Task(id="task-2", name="second", protocol="python", method="run",
                 params={}, dependencies=["task-1"]),
            Task(id="task-3", name="third", protocol="python", method="run",
                 params={}, dependencies=["task-2"])
        ]
        return Workflow(id="wf-3", name="circular-workflow", tasks=tasks)
        
    @pytest.mark.asyncio
    async def test_validate_simple_workflow(self, manager, simple_workflow):
        """Test validation of simple linear workflow"""
        result = await manager.validate_workflow(simple_workflow)
        
        assert result is True
        assert simple_workflow.id in manager._workflow_cache
        assert simple_workflow.id in manager._dependency_graphs
        
        # Check graph structure
        graph = manager._dependency_graphs[simple_workflow.id]
        assert len(graph) == 3
        assert graph["task-1"].dependencies == set()
        assert graph["task-2"].dependencies == {"task-1"}
        assert graph["task-3"].dependencies == {"task-2"}
        
    @pytest.mark.asyncio
    async def test_detect_circular_dependencies(self, manager, circular_workflow):
        """Test detection of circular dependencies"""
        with pytest.raises(CircularDependencyError) as exc_info:
            await manager.validate_workflow(circular_workflow)
            
        assert "Circular dependency detected" in str(exc_info.value)
        
    @pytest.mark.asyncio
    async def test_validate_missing_dependency(self, manager):
        """Test validation fails for missing dependencies"""
        tasks = [
            Task(id="task-1", name="first", protocol="python", method="run",
                 params={}, dependencies=["task-missing"])
        ]
        workflow = Workflow(id="wf-bad", name="bad-workflow", tasks=tasks)
        
        with pytest.raises(ValueError) as exc_info:
            await manager.validate_workflow(workflow)
            
        assert "non-existent task" in str(exc_info.value)
        
    @pytest.mark.asyncio
    async def test_get_ready_tasks(self, manager, parallel_workflow):
        """Test getting tasks ready for execution"""
        await manager.validate_workflow(parallel_workflow)
        
        # Initially only task-1 is ready
        ready = await manager.get_ready_tasks(parallel_workflow.id)
        assert len(ready) == 1
        assert ready[0].id == "task-1"
        
        # After task-1 completes, both task-2a and task-2b are ready
        ready = await manager.get_ready_tasks(
            parallel_workflow.id, 
            completed_tasks={"task-1"}
        )
        assert len(ready) == 2
        assert {t.id for t in ready} == {"task-2a", "task-2b"}
        
        # After task-2a and task-2b complete, task-3 is ready
        ready = await manager.get_ready_tasks(
            parallel_workflow.id,
            completed_tasks={"task-1", "task-2a", "task-2b"}
        )
        assert len(ready) == 1
        assert ready[0].id == "task-3"
        
    @pytest.mark.asyncio
    async def test_track_submission_idempotency(self, manager):
        """Test idempotent task submission tracking"""
        # First submission should succeed
        result = await manager.track_submission("task-1", "wf-1")
        assert result is True
        
        # Duplicate submission should be rejected
        result = await manager.track_submission("task-1", "wf-1")
        assert result is False
        
        # Different task should succeed
        result = await manager.track_submission("task-2", "wf-1")
        assert result is True
        
    @pytest.mark.asyncio
    async def test_resolution_attempt_tracking(self, manager):
        """Test workflow resolution attempt tracking"""
        # First resolution should succeed
        result = await manager.start_resolution("wf-1")
        assert result is True
        assert "wf-1" in manager._pending_resolutions
        
        # Complete the resolution
        await manager.complete_resolution("wf-1", success=True)
        assert "wf-1" not in manager._pending_resolutions
        
        # Next resolution should succeed
        result = await manager.start_resolution("wf-1")
        assert result is True
        
    @pytest.mark.asyncio
    async def test_max_resolution_attempts(self, manager):
        """Test maximum resolution attempt limiting"""
        workflow_id = "wf-test"
        
        # Exhaust max attempts
        for i in range(manager.max_attempts):
            result = await manager.start_resolution(workflow_id)
            assert result is True
            await manager.complete_resolution(workflow_id, success=False)
            
        # Next attempt should be rejected (within timeout)
        result = await manager.start_resolution(workflow_id)
        assert result is False
        
    @pytest.mark.asyncio
    async def test_topological_ordering(self, manager, simple_workflow):
        """Test topological ordering of tasks"""
        await manager.validate_workflow(simple_workflow)
        
        order = manager.get_topological_order(simple_workflow.id)
        
        # Should be in dependency order
        assert order == ["task-1", "task-2", "task-3"]
        
    @pytest.mark.asyncio
    async def test_parallel_topological_ordering(self, manager, parallel_workflow):
        """Test topological ordering with parallel tasks"""
        await manager.validate_workflow(parallel_workflow)
        
        order = manager.get_topological_order(parallel_workflow.id)
        
        # task-1 must come first
        assert order[0] == "task-1"
        # task-2a and task-2b must come before task-3
        assert order.index("task-2a") < order.index("task-3")
        assert order.index("task-2b") < order.index("task-3")
        # task-3 must come last
        assert order[-1] == "task-3"
        
    @pytest.mark.asyncio
    async def test_dependency_depth_calculation(self, manager, parallel_workflow):
        """Test calculation of dependency depths"""
        await manager.validate_workflow(parallel_workflow)
        
        depths = manager.get_dependency_depth(parallel_workflow.id)
        
        assert depths["task-1"] == 0  # No dependencies
        assert depths["task-2a"] == 1  # Depends on task-1
        assert depths["task-2b"] == 1  # Depends on task-1
        assert depths["task-3"] == 2   # Depends on task-2a and task-2b
        
    @pytest.mark.asyncio
    async def test_clear_workflow_cache(self, manager, simple_workflow):
        """Test clearing workflow cache"""
        await manager.validate_workflow(simple_workflow)
        await manager.track_submission("task-1", simple_workflow.id)
        
        # Verify data is cached
        assert simple_workflow.id in manager._workflow_cache
        assert "task-1" in manager._submitted_tasks
        
        # Clear cache
        manager.clear_workflow_cache(simple_workflow.id)
        
        # Verify data is cleared
        assert simple_workflow.id not in manager._workflow_cache
        assert simple_workflow.id not in manager._dependency_graphs
        assert "task-1" not in manager._submitted_tasks
        
    @pytest.mark.asyncio
    async def test_resolve_dependencies(self, manager, simple_workflow):
        """Test resolving dependencies for a specific task"""
        await manager.validate_workflow(simple_workflow)
        
        # task-1 has no dependencies
        deps = await manager.resolve_dependencies(simple_workflow.tasks[0], simple_workflow.id)
        assert deps == []
        
        # task-2 depends on task-1
        deps = await manager.resolve_dependencies(simple_workflow.tasks[1], simple_workflow.id)
        assert deps == ["task-1"]
        
        # task-3 depends on task-2
        deps = await manager.resolve_dependencies(simple_workflow.tasks[2], simple_workflow.id)
        assert deps == ["task-2"]
        
    @pytest.mark.asyncio
    async def test_get_statistics(self, manager, simple_workflow):
        """Test getting manager statistics"""
        await manager.validate_workflow(simple_workflow)
        await manager.track_submission("task-1", simple_workflow.id)
        await manager.start_resolution(simple_workflow.id)
        
        stats = manager.get_statistics()
        
        assert stats["cached_workflows"] == 1
        assert stats["dependency_graphs"] == 1
        assert stats["submitted_tasks"] == 1
        assert stats["pending_resolutions"] == 1
        assert simple_workflow.id in stats["resolution_attempts"]
        
    @pytest.mark.asyncio
    async def test_concurrent_resolution_locking(self, manager):
        """Test that concurrent resolutions are properly locked"""
        workflow_id = "wf-concurrent"
        
        # Start first resolution
        result1 = await manager.start_resolution(workflow_id)
        assert result1 is True
        
        # Second resolution should be rejected (already pending)
        result2 = await manager.start_resolution(workflow_id)
        assert result2 is False
        
        # After completion, new resolution should succeed
        await manager.complete_resolution(workflow_id)
        result3 = await manager.start_resolution(workflow_id)
        assert result3 is True