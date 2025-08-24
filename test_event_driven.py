#!/usr/bin/env python
"""Test the event-driven workflow completion system."""

import asyncio
import logging
from gleitzeit import GleitzeitClient

# Setup detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Enable debug logging for event bus and queue manager
logging.getLogger('gleitzeit.events.base').setLevel(logging.DEBUG)
logging.getLogger('gleitzeit.task_queue.task_queue').setLevel(logging.DEBUG)

async def test_workflow():
    """Test workflow with event-driven completion."""
    print("\n=== Testing Event-Driven Workflow Completion ===\n")
    
    # Create client with native execution
    client = GleitzeitClient(
        mode="native",
        native_config={
            "persistence": {"type": "sql", "database_url": "sqlite:///test_events.db"}
        }
    )
    await client.initialize()
    
    try:
        # Run a simple workflow
        print("Running simple workflow...")
        try:
            result = await client.run_workflow("examples/simple_python_workflow.yaml")
            
            print(f"\nWorkflow completed!")
            print(f"Status: {result.get('status', 'unknown')}")
            print(f"Results: {result.get('task_results', {})}")
        except Exception as e:
            print(f"Error running simple workflow: {e}")
            import traceback
            traceback.print_exc()
        
        # Run a parallel workflow
        print("\n\nRunning parallel workflow...")
        result = await client.run_workflow("examples/parallel_workflow.yaml")
        
        print(f"\nWorkflow completed!")
        print(f"Status: {result.get('status', 'unknown')}")
        print(f"Completed tasks: {result.get('completed_tasks', [])}")
        print(f"Failed tasks: {result.get('failed_tasks', [])}")
        print(f"Duration: {result.get('duration', 0):.2f} seconds")
        
    finally:
        # Client doesn't have a close method yet
        pass
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(test_workflow())