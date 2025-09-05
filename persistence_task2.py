import datetime
import json
import time

time.sleep(1)  # Simulate some processing time

result = {
    "task_id": "task2",
    "message": "Task 2 processed data",
    "timestamp": datetime.datetime.now().isoformat(),
    "data": {"value": 84, "status": "processed", "previous_value": 42}
}

print(json.dumps(result, indent=2))
result