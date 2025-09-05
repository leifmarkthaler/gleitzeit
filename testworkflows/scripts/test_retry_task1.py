
import os
attempt_file = '/tmp/retry_test_task1.txt'
attempts = 1 if not os.path.exists(attempt_file) else int(open(attempt_file).read()) + 1
with open(attempt_file, 'w') as f: f.write(str(attempts))
if attempts < 2:
    raise Exception(f"Task 1 failure {attempts}")
result = "Task 1 success"
os.remove(attempt_file)
