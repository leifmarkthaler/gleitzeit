import os
import json

# Check if this is the first attempt
attempt_file = "/tmp/gleitzeit_retry_test.json"

if os.path.exists(attempt_file):
    with open(attempt_file, 'r') as f:
        data = json.load(f)
        attempts = data.get('attempts', 0) + 1
else:
    attempts = 1

# Save the attempt count
with open(attempt_file, 'w') as f:
    json.dump({'attempts': attempts}, f)

# Fail on first two attempts, succeed on third
if attempts < 3:
    print(f"Attempt {attempts}: Failing intentionally to test retry")
    raise Exception(f"Test failure on attempt {attempts}")
else:
    print(f"Attempt {attempts}: Success!")
    # Clean up
    os.remove(attempt_file)
    print({"result": "Task succeeded after retries", "attempts": attempts})