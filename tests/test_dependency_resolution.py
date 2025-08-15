#!/usr/bin/env python3
"""
Test Dependency Resolution
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.core.dependency_tracker import DependencyTracker, ResolutionAttempt
from gleitzeit.core.models import Task, TaskStatus, Workflow

async def test_task_submission_tracking():
    """Test task submission tracking"""
    tracker = DependencyTracker()
    
    # Test task submission
    submitted = await tracker.mark_task_submitted("task1", "workflow1")
    assert submitted  # First submission should return True
    
    # Test duplicate submission
    submitted_again = await tracker.mark_task_submitted("task1", "workflow1")
    assert not submitted_again  # Duplicate should return False
    
    # Test task status check
    is_submitted = await tracker.is_task_submitted("task1")
    assert is_submitted
    
    # Test non-submitted task
    is_not_submitted = await tracker.is_task_submitted("task2")
    assert not is_not_submitted
    
    print("✅ Task submission tracking test passed")

async def test_workflow_resolution_tracking():
    """Test workflow resolution tracking"""
    tracker = DependencyTracker(max_attempts=3)
    
    # Test initial resolution check
    should_resolve = await tracker.should_resolve_workflow("workflow1")
    assert should_resolve  # First attempt should be allowed
    
    # Complete resolution successfully
    await tracker.complete_resolution("workflow1", success=True)
    
    # Check workflow status
    status = await tracker.get_workflow_status("workflow1")
    assert status is not None
    
    # Test reset workflow
    await tracker.reset_workflow("workflow1")
    
    # Should allow resolution again after reset
    should_resolve_after = await tracker.should_resolve_workflow("workflow1")
    assert should_resolve_after
    
    print("✅ Workflow resolution tracking test passed")

async def test_resolution_attempts():
    """Test resolution attempt tracking"""
    tracker = DependencyTracker(max_attempts=3)
    
    # Test resolution attempt creation
    attempt = ResolutionAttempt(workflow_id="test-workflow")
    assert attempt.workflow_id == "test-workflow"
    assert attempt.attempt_count == 0
    assert len(attempt.submitted_tasks) == 0
    
    # Test basic workflow operations
    should_resolve = await tracker.should_resolve_workflow("test-workflow")
    assert should_resolve
    
    # Complete resolution successfully
    await tracker.complete_resolution("test-workflow", success=True)
    
    # Check workflow status
    status = await tracker.get_workflow_status("test-workflow")
    assert status is not None
    
    print("✅ Resolution attempts test passed")

async def test_submission_history():
    """Test submission history tracking"""
    tracker = DependencyTracker()
    
    # Submit some tasks
    await tracker.mark_task_submitted("task1", "workflow1")
    await tracker.mark_task_submitted("task2", "workflow1")
    await tracker.mark_task_submitted("task3", "workflow2")
    
    # Check history
    history = tracker.submission_history
    assert len(history) == 3
    
    # Verify history entries
    assert history[0]["task_id"] == "task1"
    assert history[0]["workflow_id"] == "workflow1"
    assert history[0]["action"] == "submitted"
    
    assert history[1]["task_id"] == "task2"
    assert history[2]["task_id"] == "task3"
    
    print("✅ Submission history test passed")

def test_workflow_dependency_validation():
    """Test workflow dependency validation using Workflow model"""
    # Create tasks with dependencies
    task1 = Task(
        name="Task 1",
        protocol="python/v1",
        method="python/execute",
        params={}
    )
    
    task2 = Task(
        name="Task 2",
        protocol="python/v1",
        method="python/execute",
        params={},
        dependencies=[task1.id]  # task2 depends on task1
    )
    
    # Create workflow
    workflow = Workflow(
        name="Test Workflow",
        tasks=[task1, task2]
    )
    
    # Test dependency validation
    validation_errors = workflow.validate_dependencies()
    assert isinstance(validation_errors, list)
    assert len(validation_errors) == 0  # Should be valid
    
    # Test ready tasks
    ready_tasks = workflow.get_ready_tasks()
    assert len(ready_tasks) == 1
    assert ready_tasks[0].id == task1.id
    
    print("✅ Workflow dependency validation test passed")

def test_workflow_task_completion():
    """Test workflow task completion tracking"""
    # Create workflow with dependencies
    task1 = Task(
        name="Task 1",
        protocol="python/v1",
        method="python/execute",
        params={}
    )
    
    task2 = Task(
        name="Task 2",
        protocol="python/v1",
        method="python/execute",
        params={},
        dependencies=[task1.id]
    )
    
    workflow = Workflow(
        name="Completion Test",
        tasks=[task1, task2]
    )
    
    # Initially no tasks completed
    assert len(workflow.completed_tasks) == 0
    assert not workflow.is_complete()
    
    # Complete task1
    workflow.mark_task_completed(task1.id, {"result": "success"})
    
    # Check task1 is completed
    assert task1.id in workflow.completed_tasks
    assert task1.id in workflow.task_results
    
    # task2 should now be ready
    ready_tasks = workflow.get_ready_tasks()
    assert len(ready_tasks) == 1
    assert ready_tasks[0].id == task2.id
    
    # Complete task2
    workflow.mark_task_completed(task2.id, {"result": "success"})
    
    # Workflow should be complete
    assert workflow.is_complete()
    assert workflow.is_successful()
    
    print("✅ Workflow task completion test passed")

async def main():
    """Run all tests"""
    print("🧪 Testing Dependency Resolution")
    print("=" * 50)
    
    try:
        await test_task_submission_tracking()
        await test_workflow_resolution_tracking()
        await test_resolution_attempts()
        await test_submission_history()
        test_workflow_dependency_validation()
        test_workflow_task_completion()
        
        print("\n✅ All dependency resolution tests PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))