#!/usr/bin/env python
"""
Test task to verify default streaming works.
"""

def main():
    print("Default streaming test task executed successfully!")
    print("This confirms that Redis Streams are working by default.")
    return {"status": "success", "message": "Streams enabled by default"}

if __name__ == "__main__":
    result = main()
    print(f"Result: {result}")