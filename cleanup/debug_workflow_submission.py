#!/usr/bin/env python3
"""
Debug workflow submission process
"""

import asyncio
import subprocess
import time
import sys

async def debug_submission():
    """Debug the workflow submission"""
    
    print("🔍 Debug Workflow Submission")
    print("=" * 40)
    
    processes = []
    
    try:
        # Start central server
        central = subprocess.Popen([
            sys.executable, "-m", "gleitzeit_v2.communication.socketio_server",
            "--port", "9900", "--log-level", "INFO"
        ], env={"PYTHONPATH": "."})
        processes.append(central)
        time.sleep(2)
        
        # Start workflow server  
        workflow = subprocess.Popen([
            sys.executable, "-m", "gleitzeit_v2.orchestration.workflow_server",
            "--socketio-url", "http://localhost:9900", "--log-level", "INFO"
        ], env={"PYTHONPATH": "."})
        processes.append(workflow)
        time.sleep(3)
        
        # Test client connection and workflow submission
        from gleitzeit_v2.client.gleitzeit_client import GleitzeitClient
        from gleitzeit_v2.core.models import Workflow, Task, TaskType, TaskParameters
        
        print("Creating client...")
        client = GleitzeitClient("http://localhost:9900")
        
        print("Connecting...")
        await client.connect()
        print("✅ Connected")
        
        # Create workflow
        workflow = Workflow(name="Debug Submission")
        task = Task(
            name="Debug Task",
            task_type=TaskType.MCP_FUNCTION,
            parameters=TaskParameters(
                server="filesystem",
                function="list_files",
                arguments={"path": ".", "show_hidden": False}
            )
        )
        workflow.add_task(task)
        
        print(f"Created workflow: {workflow.id}")
        print(f"Task: {task.id} with workflow_id: {task.workflow_id}")
        
        # Submit workflow with event listener
        @client.sio.on('workflow:submitted')
        async def on_submitted(data):
            print(f"🎯 WORKFLOW SUBMITTED EVENT: {data}")
        
        @client.sio.on('workflow:completed')
        async def on_completed(data):
            print(f"🎯 WORKFLOW COMPLETED EVENT: {data}")
        
        print("Submitting workflow...")
        try:
            result = await client.submit_workflow(workflow, timeout=8.0)
            print(f"Workflow result: {result}")
        except Exception as e:
            print(f"Error submitting workflow: {e}")
        
        await client.disconnect()
        print("✅ Disconnected")
        
    finally:
        print("Stopping processes...")
        for p in processes:
            if p.poll() is None:
                p.terminate()
                p.wait()

if __name__ == '__main__':
    asyncio.run(debug_submission())