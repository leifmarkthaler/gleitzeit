#!/usr/bin/env python3
"""
Process the response from Ollama LLM task.
"""

def main(task_results=None):
    """Process Ollama response from task results."""
    if task_results is None:
        task_results = {}

    # Get the result from the ask_ollama task
    result = task_results.get('ask_ollama', {})
    response = result.get('response', 'No response')

    print(f"Ollama answered: {response}")

    return {"answer": response}

if __name__ == "__main__":
    # For testing
    print(main())