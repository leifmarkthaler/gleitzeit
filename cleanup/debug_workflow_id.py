#!/usr/bin/env python3
"""
Debug workflow_id assignment
"""

import asyncio
import subprocess
import time
import sys

async def debug_workflow_assignment():
    """Test workflow_id assignment"""
    
    print("🔍 Debug Workflow ID Assignment")
    print("=" * 40)
    
    processes = []
    
    try:
        # Start minimal system
        central = subprocess.Popen([
            sys.executable, "-m", "gleitzeit_v2.communication.socketio_server",
            "--port", "9700"
        ], env={"PYTHONPATH": "."}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(central)
        time.sleep(2)
        
        workflow = subprocess.Popen([
            sys.executable, "-m", "gleitzeit_v2.orchestration.workflow_server",
            "--socketio-url", "http://localhost:9700"
        ], env={"PYTHONPATH": "."}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(workflow)
        time.sleep(2)
        
        # Test workflow and task creation
        from gleitzeit_v2.client.gleitzeit_client import GleitzeitClient
        from gleitzeit_v2.core.models import Workflow, Task, TaskType, TaskParameters
        
        client = GleitzeitClient("http://localhost:9700")
        await client.connect()
        
        # Create single task workflow
        workflow = Workflow(name="Debug Test")
        task = Task(
            name="Debug Task",
            task_type=TaskType.MCP_FUNCTION,
            parameters=TaskParameters(
                server="filesystem",
                function="list_files",
                arguments={"path": ".", "show_hidden": False}
            )
        )
        
        print(f"Before add_task: task.workflow_id = {task.workflow_id}")
        print(f"Workflow ID = {workflow.id}")
        
        workflow.add_task(task)
        
        print(f"After add_task: task.workflow_id = {task.workflow_id}")
        
        # Convert to dict to see what gets sent
        workflow_dict = workflow.to_dict()
        print(f"Workflow tasks in dict:")
        for task_dict in workflow_dict.get('tasks', []):
            print(f"  Task {task_dict.get('id')}: workflow_id = {task_dict.get('workflow_id')}")
        
        await client.disconnect()
        
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()

if __name__ == '__main__':
    asyncio.run(debug_workflow_assignment())