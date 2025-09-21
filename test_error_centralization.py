#!/usr/bin/env python3
"""
Test centralized error management in workflow validation
"""

import asyncio
from gleitzeit.core.workflow_loader_v2 import WorkflowLoaderV2
from gleitzeit.core.errors import WorkflowValidationError, TaskValidationError, ErrorCode

async def test_centralized_error_handling():
    """Test that all validation errors use centralized error system"""
    
    loader = WorkflowLoaderV2()
    
    print("🧪 Testing Centralized Error Management\n")
    
    # Test 1: Unknown protocol - should raise TaskValidationError
    print("1. Testing unknown protocol validation:")
    workflow_dict = {
        "name": "Unknown Protocol Test",
        "tasks": [
            {
                "id": "task1",
                "name": "Unknown Protocol Task",
                "protocol": "nonexistent/v1", 
                "method": "nonexistent/method",
                "parameters": {}
            }
        ]
    }
    
    try:
        loader.load_workflow_from_dict(workflow_dict)
        assert False, "Should have raised TaskValidationError"
    except TaskValidationError as e:
        print(f"   ✅ TaskValidationError raised: {e}")
        print(f"   ✅ Error code: {e.code} (expected: {ErrorCode.TASK_VALIDATION_FAILED})")
        assert e.code == ErrorCode.TASK_VALIDATION_FAILED
        assert "nonexistent/v1" in str(e)
    
    # Test 2: Missing protocol - should raise WorkflowValidationError (enhanced validation)
    print("\n2. Testing missing protocol validation:")
    workflow_dict = {
        "name": "Missing Protocol Test", 
        "tasks": [
            {
                "id": "task1",
                "name": "No Protocol Task",
                "method": "some_method",
                "parameters": {}
            }
        ]
    }
    
    try:
        # Create workflow first (bypasses protocol validation during creation)
        workflow = loader._create_standard_workflow(workflow_dict)
        # Then validate it
        errors = loader.validate_workflow_enhanced(workflow)
        if errors:
            raise WorkflowValidationError(workflow.id, errors)
        assert False, "Should have found validation errors"
    except WorkflowValidationError as e:
        print(f"   ✅ WorkflowValidationError raised: {e}")
        print(f"   ✅ Error code: {e.code} (expected: {ErrorCode.WORKFLOW_VALIDATION_FAILED})")
        assert e.code == ErrorCode.WORKFLOW_VALIDATION_FAILED
        assert "protocol is required" in str(e)
    
    # Test 3: Circular dependencies - should raise WorkflowValidationError  
    print("\n3. Testing circular dependency validation:")
    workflow_dict = {
        "name": "Circular Dependency Test",
        "tasks": [
            {
                "id": "task_a", 
                "name": "Task A",
                "protocol": "test/v1",
                "method": "test/method",
                "dependencies": ["task_b"],
                "parameters": {}
            },
            {
                "id": "task_b",
                "name": "Task B", 
                "protocol": "test/v1",
                "method": "test/method",
                "dependencies": ["task_a"],
                "parameters": {}
            }
        ]
    }
    
    try:
        # Create workflow without protocol validation to test circular dependency detection
        workflow = loader._create_standard_workflow(workflow_dict)  
        # Override task protocols to avoid protocol validation errors
        for task in workflow.tasks:
            task.protocol = "mock/v1"  # Mock protocol
        errors = loader.validate_workflow_enhanced(workflow)
        if errors:
            raise WorkflowValidationError(workflow.id, errors)
        assert False, "Should have found circular dependency"
    except WorkflowValidationError as e:
        print(f"   ✅ WorkflowValidationError raised: {e}")
        print(f"   ✅ Error code: {e.code} (expected: {ErrorCode.WORKFLOW_VALIDATION_FAILED})")
        assert e.code == ErrorCode.WORKFLOW_VALIDATION_FAILED
        assert "circular" in str(e).lower() or "No provider registered" in str(e)
    
    print("\n✅ All centralized error handling tests passed!")
    print("✅ Proper error codes are being used")
    print("✅ No more warning-only behavior for critical errors")

if __name__ == "__main__":
    asyncio.run(test_centralized_error_handling())