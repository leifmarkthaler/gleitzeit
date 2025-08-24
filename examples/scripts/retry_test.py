#!/usr/bin/env python3
"""
Test script for retry functionality.
Fails on first 2 attempts, succeeds on 3rd.
"""

import os
import sys

# Create a file to track attempts
attempt_file = "/tmp/retry_test_attempts.txt"

# Read current attempt count
if os.path.exists(attempt_file):
    with open(attempt_file, "r") as f:
        attempts = int(f.read().strip())
else:
    attempts = 0

attempts += 1

# Write new attempt count
with open(attempt_file, "w") as f:
    f.write(str(attempts))

print(f"Attempt {attempts}")

# Fail on first 2 attempts, succeed on 3rd
if attempts < 3:
    print(f"Failing attempt {attempts}...")
    sys.exit(1)  # Exit with error code
else:
    print(f"Success on attempt {attempts}!")
    # Clean up the file
    os.remove(attempt_file)
    print("Test completed successfully after retries")
    print(f"Result: Task succeeded after {attempts} attempts")
