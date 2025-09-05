import datetime
import json

result = {
    "task_id": "task3",
    "message": "Task 3 finalized workflow",
    "timestamp": datetime.datetime.now().isoformat(),
    "data": {"value": 126, "status": "completed", "workflow_status": "SUCCESS"}
}

print(json.dumps(result, indent=2))
print("\n=== WORKFLOW COMPLETED SUCCESSFULLY ===")
result