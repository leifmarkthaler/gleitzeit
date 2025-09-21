import asyncio
import json
from gleitzeit.client import GleitzeitClient

# Create Python task files
with open("timer_test_start.py", "w") as f:
    f.write("""
print("Timer test starting!")
result = "Started"
""")

with open("timer_test_end.py", "w") as f:
    f.write("""
print("Timer completed successfully!")
result = "Timer worked!"
""")

async def main():
    client = GleitzeitClient()
    await client.initialize()
    
    # Simple workflow: task -> timer -> task
    workflow = {
        "name": "timer-simple-test",
        "tasks": [
            {
                "id": "start",
                "name": "Start",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"file": "timer_test_start.py"}
            },
            {
                "id": "wait",
                "name": "Wait 2 seconds",
                "protocol": "timer/v1", 
                "method": "timer/sleep",
                "params": {"seconds": 2},
                "dependencies": ["start"]
            },
            {
                "id": "end",
                "name": "End",
                "protocol": "python/v1",
                "method": "python/execute",
                "params": {"file": "timer_test_end.py"},
                "dependencies": ["wait"]
            }
        ]
    }
    
    print(f"Submitting workflow...")
    result = await client.submit_workflow(workflow)
    print(f"Workflow submitted: {result['workflow_id']}")
    
    # Wait and check status
    await asyncio.sleep(5)
    
    # Check results
    import redis
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    
    workflow_data = r.hgetall(f"gleitzeit:workflow:{result['workflow_id']}")
    print(f"\nWorkflow status: {workflow_data.get('status', 'unknown')}")
    
    tasks_json = workflow_data.get('tasks', '[]')
    tasks = json.loads(tasks_json)
    print("\nTask statuses:")
    for task in tasks:
        task_data = r.hgetall(f"gleitzeit:task:{task['id']}")
        print(f"  {task['name']}: {task_data.get('status', 'unknown')}")
    
    await client.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
