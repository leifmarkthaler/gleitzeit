#!/usr/bin/env python3
"""
Simple calculation task for testing.
"""

def calculate_sum(a=5, b=3):
    """Calculate the sum of two numbers."""
    result = a + b
    print(f"Calculating {a} + {b} = {result}")
    return result

def calculate_product(a=5, b=3):
    """Calculate the product of two numbers."""
    result = a * b
    print(f"Calculating {a} * {b} = {result}")
    return result

# Main execution
if __name__ == "__main__":
    # Get parameters from environment if available
    import os
    import json

    # Check if parameters were passed via environment
    params_str = os.environ.get('TASK_PARAMS', '{}')
    params = json.loads(params_str) if params_str else {}

    # Extract values with defaults
    a = params.get('a', 5)
    b = params.get('b', 3)
    operation = params.get('operation', 'sum')

    # Perform the requested operation
    if operation == 'sum':
        result = calculate_sum(a, b)
    elif operation == 'product':
        result = calculate_product(a, b)
    else:
        result = f"Unknown operation: {operation}"

    # Output the result
    print(f"Result: {result}")

    # Store result for workflow
    output = {
        "result": result,
        "operation": operation,
        "inputs": {"a": a, "b": b}
    }

    # Write to output file if specified
    output_file = os.environ.get('TASK_OUTPUT_FILE')
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(output, f)

    # Also print as JSON for capture
    print(f"OUTPUT_JSON: {json.dumps(output)}")