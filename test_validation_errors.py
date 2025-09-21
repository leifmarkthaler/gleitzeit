#!/usr/bin/env python3
"""
Test that validation errors use the centralized error system.
"""

import sys
sys.path.insert(0, 'src')

from gleitzeit.core.models import Task, Workflow
from gleitzeit.core.model_factory import TaskFactory, WorkflowFactory
from gleitzeit.core.errors import TaskValidationError, WorkflowValidationError


def test_direct_pydantic_error():
    """Show that direct Task creation raises Pydantic error."""
    print("\n=== Direct Task Creation (Pydantic Error) ===")
    try:
        # Missing required fields: name, method
        task = Task(
            id="test_task",
            protocol="python",
            config={"code": "result = 42"}
        )
    except Exception as e:
        print(f"Error type: {type(e).__name__}")
        print(f"Error: {e}")
        print("❌ This is a Pydantic error, not using centralized system!")


def test_factory_centralized_error():
    """Show that factory wraps errors in centralized system."""
    print("\n=== Factory Task Creation (Centralized Error) ===")
    try:
        # Missing required fields: name, method
        task = TaskFactory.create(
            id="test_task",
            protocol="python",
            config={"code": "result = 42"}
        )
    except TaskValidationError as e:
        print(f"Error type: {type(e).__name__}")
        print(f"Error code: {e.code}")
        print(f"Error: {e}")
        print("✅ This uses the centralized error system!")
    except Exception as e:
        print(f"Unexpected error: {type(e).__name__}: {e}")


def test_factory_with_defaults():
    """Show that factory can apply sensible defaults."""
    print("\n=== Factory with Defaults ===")
    try:
        # Create task with defaults
        task = TaskFactory.create_with_defaults(
            id="test_task",
            protocol="python",
            config={"code": "result = 42"}
        )
        print(f"✅ Task created successfully!")
        print(f"   ID: {task.id}")
        print(f"   Name: {task.name} (defaulted from ID)")
        print(f"   Method: {task.method} (defaulted to 'execute')")
        print(f"   Protocol: {task.protocol}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")


def test_workflow_validation():
    """Test workflow validation errors."""
    print("\n=== Workflow Validation ===")
    
    # Create valid task first
    task = TaskFactory.create_with_defaults(
        id="task1",
        protocol="python",
        config={"code": "result = 42"}
    )
    
    # Try to create workflow without name
    print("\n1. Direct Workflow creation (Pydantic):")
    try:
        workflow = Workflow(
            id="test_workflow",
            # Missing: name
            tasks=[task]
        )
    except Exception as e:
        print(f"   Error: {type(e).__name__}")
    
    print("\n2. Factory Workflow creation (Centralized):")
    try:
        workflow = WorkflowFactory.create(
            id="test_workflow",
            # Missing: name
            tasks=[task]
        )
    except WorkflowValidationError as e:
        print(f"   Error type: {type(e).__name__}")
        print(f"   Error code: {e.code}")
        print(f"   ✅ Uses centralized error system!")
    
    print("\n3. Factory with defaults:")
    workflow = WorkflowFactory.create_with_defaults(
        id="test_workflow",
        tasks=[task]
    )
    print(f"   ✅ Workflow created: {workflow.name} (defaulted from ID)")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("VALIDATION ERROR SYSTEM TEST")
    print("="*60)
    
    test_direct_pydantic_error()
    test_factory_centralized_error()
    test_factory_with_defaults()
    test_workflow_validation()
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print("\nProblem: Pydantic ValidationError doesn't use centralized errors")
    print("Solution: Use TaskFactory/WorkflowFactory to wrap validation")
    print("\nRecommendations:")
    print("1. Always use factories for creating models in the codebase")
    print("2. Factories provide sensible defaults (name from ID, method='execute')")
    print("3. Factories wrap Pydantic errors in centralized error system")
    print("4. This ensures consistent error handling throughout Gleitzeit")


if __name__ == "__main__":
    main()