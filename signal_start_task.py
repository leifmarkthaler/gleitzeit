"""
Start task for signal test workflow.
"""

def main():
    print("Workflow started - waiting for approval signal")
    return {"status": "waiting_for_approval"}

if __name__ == "__main__":
    result = main()
    print(f"Result: {result}")