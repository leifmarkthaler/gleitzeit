
import os
attempt_file = '/tmp/retry_test_task2.txt'
attempts = 1 if not os.path.exists(attempt_file) else int(open(attempt_file).read()) + 1
with open(attempt_file, 'w') as f: f.write(str(attempts))
if attempts < 3:
    raise Exception(f"Task 2 failure {attempts}")
result = "Task 2 success"
os.remove(attempt_file)
