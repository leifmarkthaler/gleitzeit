#!/usr/bin/env python3
"""Test event persistence with working examples from the examples directory."""

import asyncio
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit import GleitzeitClient


async def test_event_persistence():
    """Test that events are properly persisted during workflow execution."""
    
    print("\n" + "="*60)
    print("EVENT PERSISTENCE TEST")
    print("="*60)
    
    # Create client with event persistence enabled
    async with GleitzeitClient(
        persistence="memory",
        persist_events=True,
        mode="native"
    ) as client:
        print("✓ Client initialized with event persistence")
        
        # Create a simple MCP workflow (doesn't require Ollama)
        workflow = await client.create_workflow(
            name="Event Test Workflow",
            tasks=[
                {
                    "id": "task1_add",
                    "method": "mcp/tool.add",
                    "params": {"a": 10, "b": 20}
                },
                {
                    "id": "task2_multiply",
                    "dependencies": ["task1_add"],
                    "method": "mcp/tool.multiply",
                    "params": {
                        "a": "${task1_add.result}",
                        "b": 2
                    }
                },
                {
                    "id": "task3_concat",
                    "dependencies": ["task1_add", "task2_multiply"],
                    "method": "mcp/tool.concat",
                    "params": {
                        "strings": [
                            "Step 1: 10 + 20 = ${task1_add.result}",
                            "Step 2: Result × 2 = ${task2_multiply.result}"
                        ],
                        "separator": " | "
                    }
                }
            ]
        )
        
        print(f"✓ Created workflow: {workflow.id}")
        
        # Run the workflow
        print("\nRunning workflow...")
        results = await client.run_workflow(workflow)
        
        # Display task results
        print("\nTask Results:")
        for task_id, result in results.items():
            if hasattr(result, 'result'):
                if isinstance(result.result, dict):
                    value = result.result.get('result', result.result)
                else:
                    value = result.result
                print(f"  {task_id}: {value}")
        
        # Now check if events were persisted
        print("\n" + "="*60)
        print("CHECKING EVENT PERSISTENCE")
        print("="*60)
        
        # Get all events
        events = await client.get_events()
        print(f"\n✓ Total events captured: {len(events)}")
        
        if events:
            # Count events by type
            event_types = {}
            for event in events:
                event_type = str(event.get('event_type', 'unknown'))
                if event_type not in event_types:
                    event_types[event_type] = 0
                event_types[event_type] += 1
            
            print("\nEvent Type Summary:")
            for event_type, count in sorted(event_types.items()):
                print(f"  {event_type}: {count}")
            
            # Get workflow-specific events
            workflow_events = await client.get_events(workflow_id=workflow.id)
            print(f"\n✓ Workflow-specific events: {len(workflow_events)}")
            
            # Show sample events
            print("\nSample Events (first 5):")
            for i, event in enumerate(events[:5]):
                print(f"\n  Event {i+1}:")
                print(f"    Type: {event.get('event_type')}")
                print(f"    Source: {event.get('source')}")
                print(f"    Time: {event.get('timestamp')}")
                if event.get('workflow_id'):
                    print(f"    Workflow: {event.get('workflow_id')}")
                if event.get('task_id'):
                    print(f"    Task: {event.get('task_id')}")
            
            # Get task-specific events
            print("\n" + "-"*40)
            for task_id in ["task1_add", "task2_multiply", "task3_concat"]:
                task_events = await client.get_events(task_id=task_id)
                if task_events:
                    print(f"\nTask '{task_id}' events: {len(task_events)}")
                    for event in task_events[:2]:
                        print(f"  - {event.get('event_type')}")
            
            print("\n" + "="*60)
            print("✅ EVENT PERSISTENCE IS WORKING!")
            print("="*60)
            
        else:
            print("\n⚠️  No events were captured - persistence may not be working")
            return False
    
    return True


async def main():
    """Run the event persistence test."""
    print("="*60)
    print("GLEITZEIT EVENT PERSISTENCE TEST")
    print("="*60)
    
    try:
        success = await test_event_persistence()
        
        if success:
            print("\n✅ All tests passed!")
        else:
            print("\n❌ Some tests failed")
            
        return success
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)