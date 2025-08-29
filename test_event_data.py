#!/usr/bin/env python3
"""Check what data is stored in events."""

import asyncio
import sys
import os
import json
import aiohttp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def check_event_data():
    """Check what data is in persisted events."""
    
    print("\n" + "="*60)
    print("EVENT DATA ANALYSIS")
    print("="*60)
    
    # Check if server is running
    try:
        async with aiohttp.ClientSession() as session:
            # Get all events
            async with session.get("http://localhost:8000/events") as resp:
                events = await resp.json()
                print(f"Total events in system: {len(events)}")
                
                if not events:
                    print("No events found. Submitting a test workflow...")
                    
                    # Submit a workflow
                    workflow = {
                        "name": "Data Test Workflow",
                        "tasks": [
                            {
                                "id": "task1",
                                "name": "Task 1",
                                "protocol": "python/v1",
                                "method": "python/execute",
                                "params": {"code": "return {'result': 42}"}
                            }
                        ]
                    }
                    
                    async with session.post("http://localhost:8000/workflows", json=workflow) as resp:
                        result = await resp.json()
                        workflow_id = result.get("workflow_id")
                        print(f"Submitted workflow: {workflow_id}")
                    
                    await asyncio.sleep(2)
                    
                    # Get events again
                    async with session.get("http://localhost:8000/events") as resp:
                        events = await resp.json()
                
                # Analyze event data
                print("\n" + "="*60)
                print("EVENT DATA STRUCTURE")
                print("="*60)
                
                # Group events by type
                events_by_type = {}
                for event in events:
                    event_type = event.get('event_type', 'unknown')
                    if event_type not in events_by_type:
                        events_by_type[event_type] = []
                    events_by_type[event_type].append(event)
                
                # Check each event type
                for event_type, type_events in sorted(events_by_type.items()):
                    print(f"\n{event_type} ({len(type_events)} events)")
                    print("-" * 40)
                    
                    # Show first event of this type
                    if type_events:
                        sample = type_events[0]
                        
                        # Basic fields
                        print("Basic Fields:")
                        print(f"  event_id: {sample.get('event_id')}")
                        print(f"  timestamp: {sample.get('timestamp')}")
                        print(f"  workflow_id: {sample.get('workflow_id')}")
                        print(f"  task_id: {sample.get('task_id')}")
                        
                        # Data field
                        data = sample.get('data', {})
                        if data:
                            print("\nData Field Contents:")
                            for key, value in data.items():
                                if isinstance(value, dict):
                                    print(f"  {key}: <dict with {len(value)} keys>")
                                elif isinstance(value, list):
                                    print(f"  {key}: <list with {len(value)} items>")
                                elif isinstance(value, str) and len(value) > 50:
                                    print(f"  {key}: {value[:50]}...")
                                else:
                                    print(f"  {key}: {value}")
                            
                            # Check for workflow definition
                            if 'workflow' in data:
                                print("\n  ✓ Contains workflow definition!")
                                wf = data['workflow']
                                if isinstance(wf, dict):
                                    print(f"    - Workflow name: {wf.get('name')}")
                                    print(f"    - Task count: {len(wf.get('tasks', []))}")
                            
                            # Check for task definition
                            if 'task' in data:
                                print("\n  ✓ Contains task definition!")
                                task = data['task']
                                if isinstance(task, dict):
                                    print(f"    - Task name: {task.get('name')}")
                                    print(f"    - Protocol: {task.get('protocol')}")
                                    print(f"    - Method: {task.get('method')}")
                            
                            # Check for results
                            if 'result' in data:
                                print("\n  ✓ Contains execution result!")
                                print(f"    - Result type: {type(data['result']).__name__}")
                
                # Replay capability assessment
                print("\n" + "="*60)
                print("REPLAY CAPABILITY ASSESSMENT")
                print("="*60)
                
                has_workflow_defs = any('workflow' in e.get('data', {}) 
                                       for e in events)
                has_task_defs = any('task' in e.get('data', {}) 
                                   for e in events)
                has_results = any('result' in e.get('data', {}) 
                                 for e in events)
                
                print("\nData Available for Replay:")
                print(f"  Workflow definitions: {'✓' if has_workflow_defs else '✗'}")
                print(f"  Task definitions: {'✓' if has_task_defs else '✗'}")
                print(f"  Execution results: {'✓' if has_results else '✗'}")
                
                print("\nReplay Capabilities:")
                if has_workflow_defs and has_task_defs:
                    print("  ✅ FULL REPLAY POSSIBLE")
                    print("     - Can reconstruct complete workflow")
                    print("     - Can replay task submissions")
                    print("     - Can restore execution state")
                elif has_task_defs:
                    print("  ⚠️  PARTIAL REPLAY POSSIBLE")
                    print("     - Can replay individual tasks")
                    print("     - Missing workflow context")
                else:
                    print("  ❌ LIMITED REPLAY CAPABILITY")
                    print("     - Only event sequence available")
                    print("     - Need to enhance event data capture")
                
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure the API server is running with event persistence enabled:")
        print("  GLEITZEIT_PERSIST_EVENTS=true gleitzeit serve")


if __name__ == "__main__":
    asyncio.run(check_event_data())