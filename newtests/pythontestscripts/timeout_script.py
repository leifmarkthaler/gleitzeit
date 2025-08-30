#!/usr/bin/env python3
"""
Script that takes a long time to execute for timeout testing
"""

import time
import sys

def main():
    """Sleep for a configurable amount of time"""
    sleep_time = 10  # Default 10 seconds
    
    if len(sys.argv) > 1:
        try:
            sleep_time = int(sys.argv[1])
        except ValueError:
            pass
    
    print(f"Starting long task, will sleep for {sleep_time} seconds...")
    sys.stdout.flush()
    
    time.sleep(sleep_time)
    
    print("Task completed successfully!")
    return 0

if __name__ == "__main__":
    sys.exit(main())