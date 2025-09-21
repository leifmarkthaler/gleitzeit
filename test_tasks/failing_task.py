"""Task that fails on first attempts but succeeds after retries."""
import os
import json

# Read retry attempt from environment
attempt_file = "/tmp/gleitzeit_retry_attempt.txt"

if os.path.exists(attempt_file):
    with open(attempt_file, "r") as f:
        attempt = int(f.read().strip())
else:
    attempt = 0

# Increment attempt
attempt += 1
with open(attempt_file, "w") as f:
    f.write(str(attempt))

# Fail first 2 attempts, succeed on 3rd
if attempt < 3:
    print(f"Attempt {attempt}: Simulating failure...")
    raise Exception(f"Simulated failure on attempt {attempt}")
else:
    print(f"Attempt {attempt}: Success!")
    # Clean up
    os.remove(attempt_file)
    print(json.dumps({"result": "Task succeeded after retries", "attempts": attempt}))
