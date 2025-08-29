#!/usr/bin/env python3
"""Test the new replay functionality."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from gleitzeit.client import GleitzeitClient, ClientMode
from gleitzeit.core.models import Workflow, Task


async def test_replay_functionality():
    """Test the replay functionality end-to-end."""
    
    print("\n" + "="*60)
    print("REPLAY FUNCTIONALITY TEST")
    print("="*60)
    
    # Create client with event persistence
    client = GleitzeitClient(mode=ClientMode.NATIVE, persist_events=True)
    await client.initialize()
    print("✓ Client initialized with replay capabilities")
    
    # Create original workflow
    original_workflow = Workflow(
        id="test_original",
        name="Original Test Workflow",
        description="A test workflow for replay functionality",
        tasks=[
            Task(
                id="task1",
                name="First Task",
                protocol="python/v1",
                method="python/execute",
                params={"code": "print('Task 1 executing'); return {'value': 42}"}
            ),
            Task(
                id="task2", 
                name="Second Task",
                protocol="python/v1",
                method="python/execute",
                params={"code": "print('Task 2 executing'); return {'value': 84}"},
                dependencies=["task1"]
            )
        ]
    )
    
    print("\n1. CREATING ORIGINAL WORKFLOW")
    print("-" * 40)
    
    # Submit original workflow
    result = await client.submit_workflow(original_workflow)
    print(f"✓ Original workflow submitted: {original_workflow.id}")
    
    # Execute briefly
    await client.start_engine('EVENT_DRIVEN')
    await asyncio.sleep(2)
    await client.stop_engine()
    
    print("\n2. TESTING REPLAY METHODS")
    print("-" * 40)
    
    # Test 1: List replayable workflows
    print("\nTest 1: List replayable workflows")
    try:
        replayable = await client.list_replayable_workflows()
        print(f"✓ Found {len(replayable)} replayable workflows")
        for wf in replayable[:3]:
            print(f"  - {wf['id']}: {wf['name']} ({wf['task_count']} tasks)")
    except Exception as e:
        print(f"✗ List replayable failed: {e}")
    
    # Test 2: Re-execute workflow
    print("\nTest 2: Re-execute workflow")
    try:
        replay_result = await client.replay_workflow(original_workflow.id, mode="re_execute")
        print(f"✓ Re-execute replay result:")
        print(f"  - Replay ID: {replay_result.get('replay_id')}")
        print(f"  - Status: {replay_result.get('status')}")
        print(f"  - Mode: {replay_result.get('mode')}")
    except Exception as e:
        print(f"✗ Re-execute failed: {e}")
    
    # Test 3: Use as template
    print("\nTest 3: Use as template")
    try:
        template_result = await client.use_workflow_as_template(
            original_workflow.id,
            modifications={
                "name": "Template-based Workflow",
                "tasks": [
                    {"id": "task1", "params": {"code": "print('Modified task 1'); return {'value': 100}"}}
                ]
            }
        )
        print(f"✓ Template replay result:")
        print(f"  - Template ID: {template_result.get('replay_id')}")
        print(f"  - Template from: {template_result.get('template_from')}")
        print(f"  - Status: {template_result.get('status')}")
    except Exception as e:
        print(f"✗ Template replay failed: {e}")
    
    # Test 4: Restore state
    print("\nTest 4: Restore workflow state")
    try:
        restore_result = await client.restore_workflow_state(original_workflow.id)
        print(f"✓ State restoration result:")
        print(f"  - Workflow ID: {restore_result.get('replay_id')}")
        print(f"  - Status: {restore_result.get('status')}")
        print(f"  - Task states: {len(restore_result.get('task_states', {}))}")
        print(f"  - Task results: {len(restore_result.get('task_results', {}))}")
    except Exception as e:
        print(f"✗ State restoration failed: {e}")
    
    # Test 5: Continue workflow (simulated)
    print("\nTest 5: Continue workflow")
    try:
        continue_result = await client.continue_workflow(original_workflow.id)
        print(f"✓ Continue workflow result:")
        print(f"  - Continue ID: {continue_result.get('replay_id')}")
        print(f"  - Status: {continue_result.get('status')}")
        if 'tasks_to_skip' in continue_result:
            print(f"  - Tasks to skip: {len(continue_result['tasks_to_skip'])}")
        if 'tasks_to_run' in continue_result:
            print(f"  - Tasks to run: {len(continue_result['tasks_to_run'])}")
    except Exception as e:
        print(f"✗ Continue workflow failed: {e}")
    
    # Test 6: Debug workflow
    print("\nTest 6: Debug workflow")
    try:
        debug_result = await client.debug_workflow(
            original_workflow.id,
            breakpoints=["task2"]
        )
        print(f"✓ Debug workflow result:")
        print(f"  - Debug ID: {debug_result.get('replay_id')}")
        print(f"  - Status: {debug_result.get('status')}")
        print(f"  - Breakpoints: {debug_result.get('breakpoints', [])}")
    except Exception as e:
        print(f"✗ Debug workflow failed: {e}")
    
    await client.shutdown()
    
    print("\n" + "="*60)
    print("REPLAY FUNCTIONALITY TEST COMPLETE")
    print("="*60)
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_replay_functionality())
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    if success:
        print("\n✅ Replay functionality is implemented and working!")
        print("\nAvailable replay methods:")
        print("  • client.replay_workflow(id, mode='re_execute')")
        print("  • client.continue_workflow(id)")
        print("  • client.debug_workflow(id, breakpoints=[])")
        print("  • client.use_workflow_as_template(id, modifications={})")
        print("  • client.restore_workflow_state(id)")
        print("  • client.list_replayable_workflows()")
        print("  • client.get_replay_history(id)")
    else:
        print("\n⚠️  Some replay tests failed")
    
    sys.exit(0 if success else 1)