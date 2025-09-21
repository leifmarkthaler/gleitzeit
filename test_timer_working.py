import asyncio
import json
from gleitzeit.client import GleitzeitClient

# First, create the Python task files
with open("print_start.py", "w") as f:
    f.write("""
print("Starting timer test workflow!")
result = "Started successfully"
""")

with open("print_after_timer.py", "w") as f:
    f.write("""
print("Timer completed! Task resumed after sleep.")
result = "Timer workflow completed successfully!"
""")

async def main():
    client = GleitzeitClient(base_url="http://localhost:8090")
    await client.initialize()
    
    # Submit timer workflow with file-based Python tasks
    workflow = {
        "name": "timer-test-working",
        "tasks": [
            {
                "id": "start_task",
                "name": "Print start message",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"file": "print_start.py"}
            },
            {
                "id": "sleep_task",
                "name": "Sleep for 3 seconds",
                "protocol": "timer/v1", 
                "method": "timer/sleep",
                "params": {"seconds": 3},
                "dependencies": ["start_task"]
            },
            {
                "id": "after_sleep",
                "name": "Print after timer",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"file": "print_after_timer.py"},
                "dependencies": ["sleep_task"]
            }
        ]
    }
    
    print(f"Submitting workflow: {json.dumps(workflow, indent=2)}")
    result = await client.submit_workflow(workflow)
    print(f"\nWorkflow submitted: {result['workflow_id']}")
    
    # Wait for workflow to complete
    print("\nWaiting for workflow to complete...")
    await asyncio.sleep(10)
    
    # Check workflow status
    print("\nChecking workflow status...")
    try:
        # Get workflow info from Redis directly since API might not have the endpoint
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        
        workflow_data = r.hgetall(f"gleitzeit:workflow:{result['workflow_id']}")
        print(f"Workflow status: {workflow_data.get('status', 'unknown')}")
        
        # Check tasks
        tasks_json = workflow_data.get('tasks', '[]')
        tasks = json.loads(tasks_json)
        print("\nTask statuses:")
        for task in tasks:
            task_id = task['id']
            task_data = r.hgetall(f"gleitzeit:task:{task_id}")
            print(f"  {task['name']}: {task_data.get('status', 'unknown')}")
            
    except Exception as e:
        print(f"Error checking status: {e}")
    
    await client.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
