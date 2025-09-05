import datetime
import json

result = {
    "task_id": "task1",
    "message": "Task 1 completed successfully",
    "timestamp": datetime.datetime.now().isoformat(),
    "data": {"value": 42, "status": "initialized"}
}

print(json.dumps(result, indent=2))
result