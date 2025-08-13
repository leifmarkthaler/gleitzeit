#!/usr/bin/env python3
"""
Debug workflow submission with MCP provider
"""

import asyncio
import subprocess
import time
import sys

async def debug_with_mcp():
    """Debug the workflow submission with MCP provider"""
    
    print("🔍 Debug Workflow with MCP Provider")
    print("=" * 40)
    
    processes = []
    
    try:
        # Start central server
        central = subprocess.Popen([
            sys.executable, "-m", "gleitzeit_v2.communication.socketio_server",
            "--port", "9950"
        ], env={"PYTHONPATH": "."}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(central)
        time.sleep(2)
        
        # Start workflow server  
        workflow = subprocess.Popen([
            sys.executable, "-m", "gleitzeit_v2.orchestration.workflow_server",
            "--socketio-url", "http://localhost:9950"
        ], env={"PYTHONPATH": "."}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(workflow)
        time.sleep(2)
        
        # Start MCP provider with verbose logging
        mcp = subprocess.Popen([
            sys.executable, "-m", "gleitzeit_v2.providers.mcp_provider",
            "--server-url", "http://localhost:9950", "--verbose"
        ], env={"PYTHONPATH": "."})
        processes.append(mcp)
        time.sleep(3)
        
        # Test workflow submission
        from gleitzeit_v2.client.gleitzeit_client import GleitzeitClient
        from gleitzeit_v2.core.models import Workflow, Task, TaskType, TaskParameters
        
        print("Creating client...")
        client = GleitzeitClient("http://localhost:9950")
        
        print("Connecting...")
        await client.connect()
        print("✅ Connected")
        
        # Create workflow
        workflow = Workflow(name="MCP Test")
        task = Task(
            name="MCP Task",
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
        
        print("Submitting workflow...")
        try:
            result = await client.run_mcp_function(
                server="filesystem",
                function="list_files",
                arguments={"path": ".", "show_hidden": False},
                timeout=8.0
            )
            print(f"✅ MCP FUNCTION SUCCESS: {result}")
        except Exception as e:
            print(f"❌ MCP FUNCTION FAILED: {e}")
        
        await client.disconnect()
        print("✅ Disconnected")
        
    finally:
        print("Stopping processes...")
        for p in processes:
            if p.poll() is None:
                p.terminate()
                time.sleep(0.5)
                if p.poll() is None:
                    p.kill()

if __name__ == '__main__':
    asyncio.run(debug_with_mcp())