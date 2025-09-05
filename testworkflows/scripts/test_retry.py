
import os

# Use a file to track attempts
attempt_file = '/tmp/retry_test_attempts.txt'

# Read current attempt count
if os.path.exists(attempt_file):
    with open(attempt_file, 'r') as rf:
        attempts = int(rf.read().strip())
else:
    attempts = 0

# Increment attempt count
attempts += 1
with open(attempt_file, 'w') as wf:
    wf.write(str(attempts))

# Fail first 2 attempts
if attempts < 3:
    raise Exception(f"Deliberate failure on attempt {attempts}")

# Succeed on 3rd attempt
result = f"Success after {attempts} attempts"
print(result)

# Clean up
os.remove(attempt_file)
