#!/usr/bin/env python3
"""
Simple test of the Easy Syntax without complex chaining
"""

from gleitzeit.easy import t, w

def test_basic_task():
    """Test creating a basic task."""
    print("=== Testing Basic Task Creation ===")
    
    # Create a simple task
    task = t("calculate", "python/v1:execute").with_(file="examples/scripts/simple_math.py")
    
    print(f"Task: {task}")
    print(f"Task dict: {task.to_dict()}")
    print()

def test_basic_workflow():
    """Test creating a basic workflow without complex chaining."""
    print("=== Testing Basic Workflow Creation ===")
    
    # Create tasks first
    task1 = t("calculate", "python/v1:execute").with_(file="examples/scripts/simple_math.py").retry(2)
    task2 = t("transform", "python/v1:execute").needs("calculate").with_(file="examples/scripts/simple_math.py")
    
    # Create workflow
    workflow = w(task1, task2).name("simple_workflow").version("1.0.0")
    
    print(f"Workflow: {workflow}")
    print(f"Tasks: {workflow.get_task_count()}")
    print(f"Event Handlers: {workflow.get_event_handler_count()}")
    print(f"Task IDs: {workflow.get_task_ids()}")
    
    # Validate
    errors = workflow.validate()
    if errors:
        print(f"❌ Validation errors: {errors}")
    else:
        print("✅ Validation passed")
        
    return workflow

def test_event_handlers():
    """Test creating tasks with event handlers."""
    print("=== Testing Event Handlers ===")
    
    # Create a task with event handlers
    task = (t("risky_calc", "python/v1:execute")
            .with_(file="examples/scripts/simple_math.py")
            .retry(2)
            .timeout(30))
    
    # Add event handlers
    task.on_success().run("log_success", "python/v1:execute").with_(message="Success!")
    task.on_error("TIMEOUT").run("log_timeout", "python/v1:execute").with_(message="Timeout!")
    
    print(f"Task with handlers: {task}")
    print(f"Event handlers: {len(task.get_event_handlers())}")
    
    # Create workflow
    workflow = w(task).name("event_workflow")
    print(f"Workflow: {workflow}")
    print(f"Event Handlers: {workflow.get_event_handler_count()}")
    
    return workflow

def main():
    """Test the easy syntax step by step."""
    test_basic_task()
    test_basic_workflow()
    
    workflow = test_event_handlers()
    
    # Show final structure
    print("\n=== Generated Workflow Structure ===")
    import json
    workflow_dict = workflow.to_dict()
    print(json.dumps(workflow_dict, indent=2))

if __name__ == "__main__":
    main()