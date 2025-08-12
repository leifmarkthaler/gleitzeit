#!/usr/bin/env python3
"""
Debug script to trace execution flow step by step
"""

import asyncio
import logging
import time
from gleitzeit_v2.client.gleitzeit_client import GleitzeitClient
from gleitzeit_v2.core.models import Task, TaskType, TaskParameters, Workflow

# Enable detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def debug_execution_flow():
    """Debug the execution flow step by step"""
    
    print("=== DEBUGGING EXECUTION FLOW ===")
    
    # 1. Create client and connect
    print("\n1. Creating client...")
    client = GleitzeitClient("http://localhost:8020")  # Assuming central server on 8020
    
    print("2. Connecting to central server...")
    await client.connect()
    
    if not client.connected:
        print("❌ Failed to connect to central server")
        return
    
    print("✅ Connected to central server")
    
    # 2. Create simple task
    print("\n3. Creating simple task...")
    task = Task(
        name="Debug Task",
        task_type=TaskType.LLM_GENERATE,
        parameters=TaskParameters(
            prompt="Say exactly: Hello Debug",
            model="llama3"
        )
    )
    
    print(f"   Task ID: {task.id}")
    print(f"   Task Type: {task.task_type.value}")
    
    # 3. Create workflow
    print("\n4. Creating workflow...")
    workflow = Workflow(name="Debug Workflow")
    workflow.add_task(task)
    
    print(f"   Workflow ID: {workflow.id}")
    print(f"   Task workflow_id after add_task: {task.workflow_id}")
    
    # 4. Submit workflow and trace what happens
    print("\n5. Submitting workflow...")
    
    # Create future manually to trace
    future = asyncio.Future()
    client.workflow_futures[workflow.id] = future
    
    # Emit the workflow
    await client.sio.emit('workflow:submit', {
        'workflow': workflow.to_dict()
    })
    
    print("   Workflow submitted, waiting for events...")
    
    # Wait with timeout and show what happens
    try:
        result = await asyncio.wait_for(future, timeout=10.0)
        print(f"✅ Workflow completed: {result}")
    except asyncio.TimeoutError:
        print("❌ Workflow timed out after 10 seconds")
        print("   Checking what events were received...")
    
    # Clean up
    await client.disconnect()
    print("\n=== DEBUG COMPLETE ===")

if __name__ == '__main__':
    asyncio.run(debug_execution_flow())