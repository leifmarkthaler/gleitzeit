#!/usr/bin/env python3
"""Start task for signal test workflow."""

def main():
    print("Workflow started - waiting for approval signal")
    return {"status": "waiting", "message": "Ready to wait for signal"}

if __name__ == "__main__":
    result = main()
    print(f"Result: {result}")