#!/usr/bin/env python3
"""
Test workflow with scheduled timer tasks
"""
import asyncio
import os
from datetime import datetime, timedelta

# Set the API port
os.environ['GLEITZEIT_API_PORT'] = '8200'

from gleitzeit.client.client import GleitzeitClient

# Define scheduled tasks that run at specific times
scheduled_task1 = """
import datetime
print(f"Scheduled task 1 executed at {datetime.datetime.now()}")
print("This task was scheduled to run after 2 seconds")
return {"task": "scheduled_1", "executed_at": str(datetime.datetime.now())}
"""

scheduled_task2 = """
import datetime
print(f"Scheduled task 2 executed at {datetime.datetime.now()}")
print("This task was scheduled to run after 5 seconds")
return {"task": "scheduled_2", "executed_at": str(datetime.datetime.now())}
"""

scheduled_task3 = """
import datetime
print(f"Scheduled task 3 executed at {datetime.datetime.now()}")
print("This task was scheduled to run after 8 seconds")
print("All scheduled tasks completed!")
return {"task": "scheduled_3", "executed_at": str(datetime.datetime.now())}
"""

async def main():
    """Test scheduled workflow execution"""
    print("\nTesting scheduled timer workflow...")
    print("="*50)
    
    client = GleitzeitClient(api_url='http://localhost:8200')
    await client.initialize()
    
    # Create workflow with scheduled tasks
    workflow_config = {
        "name": f"scheduled-workflow-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "tasks": [
            {
                "id": "init_task",
                "name": "init_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
import datetime
print(f"Workflow initialized at {datetime.datetime.now()}")
print("Starting scheduled tasks...")
return {"status": "initialized", "time": str(datetime.datetime.now())}
"""
                }
            },
            {
                "id": "scheduled_task_1",
                "name": "scheduled_task_1",
                "protocol": "timer/v1",
                "method": "timer/wait",
                "params": {
                    "duration": "2"  # Wait 2 seconds
                },
                "dependencies": ["init_task"]
            },
            {
                "id": "exec_task_1",
                "name": "exec_task_1",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": scheduled_task1
                },
                "dependencies": ["scheduled_task_1"]
            },
            {
                "id": "scheduled_task_2",
                "name": "scheduled_task_2",
                "protocol": "timer/v1",
                "method": "timer/wait",
                "params": {
                    "duration": "5"  # Wait 5 seconds from start
                },
                "dependencies": ["init_task"]
            },
            {
                "id": "exec_task_2",
                "name": "exec_task_2",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": scheduled_task2
                },
                "dependencies": ["scheduled_task_2"]
            },
            {
                "id": "scheduled_task_3",
                "name": "scheduled_task_3",
                "protocol": "timer/v1",
                "method": "timer/wait",
                "params": {
                    "duration": "8"  # Wait 8 seconds from start
                },
                "dependencies": ["init_task"]
            },
            {
                "id": "exec_task_3",
                "name": "exec_task_3",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": scheduled_task3
                },
                "dependencies": ["scheduled_task_3"]
            },
            {
                "id": "final_task",
                "name": "final_task",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {
                    "code": """
import datetime
print(f"\\nAll scheduled tasks completed at {datetime.datetime.now()}")
print("Workflow finished successfully!")
return {"status": "completed", "time": str(datetime.datetime.now())}
"""
                },
                "dependencies": ["exec_task_1", "exec_task_2", "exec_task_3"]
            }
        ]
    }
    
    # Submit workflow
    print(f"Submitting scheduled workflow: {workflow_config['name']}")
    workflow = await client.submit_workflow(workflow_config)
    print(f"Workflow submitted: {workflow}")
    workflow_id = workflow.get('workflow_id')
    
    # Monitor workflow progress
    print("\nMonitoring workflow execution...")
    print("Tasks will execute at scheduled times:")
    print("- Task 1: after 2 seconds")
    print("- Task 2: after 5 seconds")  
    print("- Task 3: after 8 seconds")
    print("")
    
    start_time = datetime.now()
    last_status = None
    completed_tasks = set()
    
    for i in range(60):  # Check for up to 60 seconds
        await asyncio.sleep(1)
        
        # Get workflow status
        workflow_obj = await client.get_workflow(workflow_id)
        
        # Track completed tasks
        for task in workflow_obj.tasks:
            task_result = await client.get_task_result(task.id)
            if task_result.status == 'completed' and task.id not in completed_tasks:
                elapsed = (datetime.now() - start_time).total_seconds()
                print(f"[{elapsed:.1f}s] Task completed: {task.name}")
                if task_result.result:
                    print(f"       Result: {task_result.result}")
                completed_tasks.add(task.id)
        
        # Check if workflow completed
        if workflow_obj.status != last_status:
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"[{elapsed:.1f}s] Workflow status: {workflow_obj.status}")
            last_status = workflow_obj.status
            
        if workflow_obj.status == 'completed':
            print(f"\n✅ Workflow completed successfully!")
            print(f"Total execution time: {elapsed:.1f} seconds")
            
            # Get all results
            print("\nTask Results:")
            print("-" * 40)
            for task in workflow_obj.tasks:
                result = await client.get_task_result(task.id)
                if result.result:
                    print(f"{task.name}: {result.result}")
            break
            
        if workflow_obj.status == 'failed':
            print(f"\n❌ Workflow failed!")
            # Get error details
            for task in workflow_obj.tasks:
                result = await client.get_task_result(task.id)
                if result.error:
                    print(f"Error in {task.name}: {result.error}")
            break
    else:
        print("\n⏱️ Workflow timed out after 60 seconds")
    
    # Cleanup
    # Note: client doesn't have close() method, sessions handled internally

if __name__ == "__main__":
    asyncio.run(main())