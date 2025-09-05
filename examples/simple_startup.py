#!/usr/bin/env python3
"""
Simple startup example for Gleitzeit.

This example shows how to use the new synchronous startup methods
that work in regular Python scripts and Jupyter notebooks.
"""

from gleitzeit.client import GleitzeitClient

def main():
    """Main function demonstrating simple sync startup."""
    
    print("Starting Gleitzeit client...")
    
    # Simple one-line startup!
    client = GleitzeitClient.start_sync()
    
    print("Client ready! Using mode:", client.mode)
    
    # Create a simple task
    task = {
        "id": "test_task",
        "name": "Test Python Task",
        "protocol": "python/v1",
        "method": "python/execute",
        "params": {
            "file": "test_hello.py"  # This would need to exist
        }
    }
    
    # Example workflow
    workflow = {
        "name": "Simple Test Workflow",
        "tasks": [
            {
                "id": "task1",
                "name": "First Task",
                "protocol": "python/v1", 
                "method": "python/execute",
                "params": {
                    "file": "test_task1.py"  # Would need to exist
                }
            },
            {
                "id": "task2",
                "name": "Second Task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "file": "test_task2.py"  # Would need to exist
                },
                "dependencies": ["task1"]
            }
        ]
    }
    
    try:
        # Run a simple task if the file exists
        import os
        if os.path.exists("test_hello.py"):
            print("\nRunning test task...")
            result = client.run_task_sync(task)
            print("Task result:", result)
        else:
            print("Client is ready for tasks and workflows!")
            print("\nTo run tasks/workflows, create the Python files referenced in params.")
        
    finally:
        # Clean shutdown
        print("\nShutting down...")
        client.stop_sync()
        print("Done!")


if __name__ == "__main__":
    main()