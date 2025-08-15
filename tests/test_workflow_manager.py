#!/usr/bin/env python3
"""
Test Workflow Management
"""

import asyncio
import sys
import os
from unittest.mock import AsyncMock
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from gleitzeit.core.workflow_manager import WorkflowManager, WorkflowTemplate, WorkflowExecution, WorkflowExecutionPolicy
from gleitzeit.core.models import Workflow, Task, Priority, WorkflowStatus

async def test_workflow_creation():
    """Test workflow creation and basic functionality"""
    # Test basic workflow and task creation
    workflow = Workflow(
        name="Test Workflow",
        description="Test workflow for unit tests",
        tasks=[
            Task(
                name="First Task",
                protocol="python/v1",
                method="python/execute",
                params={"code": "result = 1"}
            ),
            Task(
                name="Second Task",
                protocol="python/v1",
                method="python/execute",
                params={"code": "result = 2"}
            )
        ]
    )
    
    # Test workflow properties
    assert workflow.name == "Test Workflow"
    assert len(workflow.tasks) == 2
    assert workflow.tasks[0].name == "First Task"
    assert workflow.tasks[1].name == "Second Task"
    
    # Test workflow validation
    validation_errors = workflow.validate_dependencies()
    assert isinstance(validation_errors, list)
    
    print("✅ Workflow creation test passed")

async def test_workflow_template():
    """Test workflow template functionality"""
    # Create a workflow template
    template = WorkflowTemplate(
        id="test-template",
        name="Test Template",
        description="Test workflow template",
        version="1.0",
        tasks=[
            {
                "name": "Template Task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"code": "result = {{value}}"}
            }
        ],
        parameters={"value": "42"}
    )
    
    # Test template properties
    assert template.id == "test-template"
    assert template.name == "Test Template"
    assert template.version == "1.0"
    assert len(template.tasks) == 1
    assert template.parameters["value"] == "42"
    
    print("✅ Workflow template test passed")

async def test_workflow_execution_policies():
    """Test workflow execution policies"""
    workflow = Workflow(
        name="Policy Workflow",
        description="Test workflow with execution policies",
        tasks=[
            Task(
                name="High Priority Task",
                protocol="python/v1",
                method="python/execute",
                params={"code": "result = 'high'"},
                priority=Priority.HIGH
            ),
            Task(
                name="Low Priority Task",
                protocol="python/v1",
                method="python/execute",
                params={"code": "result = 'low'"},
                priority=Priority.LOW
            )
        ]
    )
    
    # Test workflow execution instances
    execution1 = WorkflowExecution(
        execution_id="exec-1",
        workflow=workflow,
        status=WorkflowStatus.RUNNING,
        policy=WorkflowExecutionPolicy.FAIL_FAST
    )
    
    execution2 = WorkflowExecution(
        execution_id="exec-2",
        workflow=workflow,
        status=WorkflowStatus.RUNNING,
        policy=WorkflowExecutionPolicy.CONTINUE_ON_ERROR
    )
    
    # Check executions have correct properties
    assert execution1.policy == WorkflowExecutionPolicy.FAIL_FAST
    assert execution2.policy == WorkflowExecutionPolicy.CONTINUE_ON_ERROR
    assert execution1.workflow.name == "Policy Workflow"
    assert execution2.workflow.name == "Policy Workflow"
    print("✅ Workflow execution policies test passed")

async def test_workflow_status_tracking():
    """Test workflow status tracking"""
    workflow = Workflow(
        name="Status Test",
        description="Test workflow status tracking",
        tasks=[
            Task(
                name="Test Task",
                protocol="python/v1",
                method="python/execute",
                params={"code": "result = 'done'"}
            )
        ]
    )
    
    # Test workflow status methods
    assert not workflow.is_complete()
    assert not workflow.is_successful()
    assert workflow.get_completion_percentage() == 0.0
    
    # Simulate task completion
    task = workflow.tasks[0]
    workflow.mark_task_completed(task.id, {"result": "success"})
    
    assert workflow.is_complete()
    assert workflow.is_successful()
    assert workflow.get_completion_percentage() == 100.0
    assert task.id in workflow.completed_tasks
    assert len(workflow.failed_tasks) == 0
    
    print("✅ Workflow status tracking test passed")

async def main():
    """Run all tests"""
    print("🧪 Testing Workflow Management")
    print("=" * 50)
    
    try:
        await test_workflow_creation()
        await test_workflow_template()
        await test_workflow_execution_policies()
        await test_workflow_status_tracking()
        
        print("\n✅ All workflow management tests PASSED")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))