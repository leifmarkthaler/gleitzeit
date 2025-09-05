
import os
import time

attempt_file = '/tmp/retry_timing.txt'
timestamp_file = '/tmp/retry_timestamps.txt'

# Record timestamp
current_time = time.time()
if os.path.exists(timestamp_file):
    with open(timestamp_file, 'a') as tf:
        tf.write(f",{current_time}")
else:
    with open(timestamp_file, 'w') as tf:
        tf.write(str(current_time))

# Track attempts
attempts = 1 if not os.path.exists(attempt_file) else int(open(attempt_file).read()) + 1
with open(attempt_file, 'w') as f:
    f.write(str(attempts))

# Fail first 3 attempts
if attempts < 4:
    raise Exception(f"Failure {attempts}")

# Read all timestamps
with open(timestamp_file, 'r') as tf:
    timestamps = [float(t) for t in tf.read().split(',')]

# Calculate delays between attempts
delays = []
for i in range(1, len(timestamps)):
    delays.append(timestamps[i] - timestamps[i-1])

result = {"attempts": attempts, "delays": delays}
print(f"Result: {result}")

# Clean up
os.remove(attempt_file)
os.remove(timestamp_file)
